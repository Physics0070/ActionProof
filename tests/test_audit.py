"""Deck S3.6 / S9.3: the audit chain. Append-only hash-chained log, signed checkpoints, verifier CLI.

A superuser (or the table owner) can always bypass the append-only trigger; these tests do exactly that and prove
the verifier still detects the edit, delete, truncation, reorder and forged checkpoint.
"""
import base64
import os
import subprocess
import sys
import threading
from pathlib import Path

import psycopg
import pytest
from gatekit import rules
from nacl.signing import SigningKey

from actionproof import audit
from actionproof import db as dbmod
from actionproof.config import ConfigError, load_settings
from actionproof.gate import ReviewRefused
from actionproof.signing import Signer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def signer(signing_key_path):
    return Signer.from_path(signing_key_path, "k1")


def _entries(conn, signer, n=5):
    for i in range(n):
        audit.append(conn, "test", decision="ALLOW", rules=[], detail={"i": i})
        audit.checkpoint(conn, signer)
        conn.commit()


def _check(pg, pub) -> tuple[int, str]:
    return audit.run_verify(pg, pub)


def _tamper(pg, *statements, params=()):
    """A superuser connection that skips the append-only trigger (session_replication_role = replica)."""
    with dbmod.connect(url=pg) as su:
        su.execute("SET session_replication_role = replica")
        for q in statements:
            su.execute(q, params if "%s" in q else ())


def _log(conn) -> list[tuple]:
    rows = conn.execute("SELECT kind, decision, rules, detail FROM audit_log ORDER BY seq").fetchall()
    conn.commit()
    return rows


# ------------------------------------------------------------------ append-only + chain


def test_append_only_trigger_refuses_update_delete_truncate(db, signer):
    _entries(db, signer, 2)
    for q in ("UPDATE audit_log SET decision = 'DENY' WHERE seq = 1", "DELETE FROM audit_log WHERE seq = 2",
              "TRUNCATE audit_log", "UPDATE audit_checkpoints SET sig = 'x'", "DELETE FROM audit_checkpoints",
              "TRUNCATE audit_checkpoints"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            db.execute(q)
        db.rollback()
    assert db.execute("SELECT count(*) FROM audit_log").fetchone() == (2,)


def test_chain_links_and_verifies(db, pg, signer):
    _entries(db, signer, 3)
    rows = db.execute("SELECT seq, prev_hash, entry_hash FROM audit_log ORDER BY seq").fetchall()
    assert [r[0] for r in rows] == [1, 2, 3]
    assert rows[0][1] == audit.GENESIS and rows[1][1] == rows[0][2] and rows[2][1] == rows[1][2]
    assert _check(pg, signer.public_key_b64()) == (0, "audit: OK (3 entries, 3 checkpoints)")


def test_empty_log_verifies(db, pg, signer):
    assert _check(pg, signer.public_key_b64()) == (0, "audit: OK (0 entries, 0 checkpoints)")


# ------------------------------------------------------------------ tamper detection (superuser bypasses the trigger)


def test_edited_row_detected(db, pg, signer):
    _entries(db, signer)
    _tamper(pg, "UPDATE audit_log SET decision = 'DENY' WHERE seq = 3")
    assert _check(pg, signer.public_key_b64()) == (1, "audit: FAILED at seq 3: entry_hash does not recompute (entry edited)")


def test_edited_row_with_rehashed_chain_detected_by_checkpoint(db, pg, signer):
    """The attacker recomputes every hash after the edit; only the signed checkpoint still remembers."""
    _entries(db, signer)
    rows = db.execute(f"SELECT {', '.join(audit.FIELDS)} FROM audit_log ORDER BY seq").fetchall()
    db.commit()
    chain = [dict(zip(audit.FIELDS, r)) for r in rows]
    chain[2]["decision"] = "DENY"
    prev = audit.GENESIS
    for e in chain:  # entries 1-2 rehash to the same values; 3-5 get a new, self-consistent chain
        e["prev_hash"] = prev
        e["entry_hash"] = prev = audit.entry_hash(e)
    with dbmod.connect(url=pg) as su:
        su.execute("SET session_replication_role = replica")
        for e in chain[2:]:
            su.execute("UPDATE audit_log SET decision = %s, prev_hash = %s, entry_hash = %s WHERE seq = %s",
                       (e["decision"], e["prev_hash"], e["entry_hash"], e["seq"]))
    code, line = _check(pg, signer.public_key_b64())
    assert (code, line) == (1, "audit: FAILED at seq 3: checkpoint head_hash does not match the entry")


def test_deleted_middle_row_detected(db, pg, signer):
    _entries(db, signer)
    _tamper(pg, "DELETE FROM audit_log WHERE seq = 3")
    assert _check(pg, signer.public_key_b64()) == (1, "audit: FAILED at seq 3: entry missing or out of order (found seq 4)")


def test_deleted_tail_row_detected_via_checkpoint(db, pg, signer):
    _entries(db, signer)
    _tamper(pg, "DELETE FROM audit_log WHERE seq = 5")
    assert _check(pg, signer.public_key_b64()) == (
        1, "audit: FAILED at seq 5: checkpoint refers to a missing entry (log truncated)")


def test_reordered_rows_detected(db, pg, signer):
    _entries(db, signer)
    _tamper(pg, "UPDATE audit_log SET seq = 1000 WHERE seq = 2", "UPDATE audit_log SET seq = 2 WHERE seq = 3",
            "UPDATE audit_log SET seq = 3 WHERE seq = 1000")
    assert _check(pg, signer.public_key_b64()) == (1, "audit: FAILED at seq 2: prev_hash does not link to the previous entry")


def test_forged_checkpoint_signature_detected(db, pg, signer):
    _entries(db, signer)
    seq, head, ts = db.execute("SELECT seq, head_hash, ts FROM audit_checkpoints WHERE seq = 2").fetchone()
    db.commit()
    forged = Signer(SigningKey.generate(), "k1").sign({"seq": seq, "head_hash": head, "ts": ts})["sig"]
    _tamper(pg, "UPDATE audit_checkpoints SET sig = %s WHERE seq = 2", params=(forged,))
    assert _check(pg, signer.public_key_b64()) == (1, "audit: FAILED at seq 2: checkpoint signature invalid")


def test_wrong_public_key_fails(db, pg, signer):
    _entries(db, signer, 2)
    other = base64.b64encode(bytes(SigningKey.generate().verify_key)).decode()
    assert _check(pg, other) == (1, "audit: FAILED at seq 1: checkpoint signature invalid")


# ------------------------------------------------------------------ concurrency


def test_concurrent_appends_are_gap_free(db, pg, signer):
    n = 20
    barrier = threading.Barrier(n)
    errs = []

    def worker(i):
        try:
            with dbmod.connect(url=pg) as c:
                barrier.wait()
                audit.append(c, "test", detail={"i": i})
                audit.checkpoint(c, signer)
        except Exception as e:  # pragma: no cover - surfaced below
            errs.append(repr(e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errs == []
    assert [r[0] for r in db.execute("SELECT seq FROM audit_log ORDER BY seq").fetchall()] == list(range(1, n + 1))
    db.commit()
    assert _check(pg, signer.public_key_b64()) == (0, f"audit: OK ({n} entries, {n} checkpoints)")


# ------------------------------------------------------------------ gate integration


def _review(kit, inv="INV-AUD1"):
    req, docs = kit.json_request(inv, "1000.00", "500.00", idem=f"aud-{inv}")
    p = kit.gate.prepare(req, docs)
    assert p.decision == "REVIEW", p.reasons
    return req, p.receipt


def test_chain_grows_with_prepare_and_commit(kit):
    req, docs = kit.hero_allow()
    p = kit.gate.prepare(req, docs)
    assert p.decision == "ALLOW"
    c = kit.gate.commit(p.receipt, req)
    assert c.outcome == "EXECUTED"
    log = _log(kit.db)
    assert [(k, d) for k, d, *_ in log] == [("prepare", "ALLOW"), ("commit", "EXECUTED")]
    pay = p.receipt["payload"]
    row = kit.sql("SELECT request_hash, actor, on_behalf_of, record_id, detail FROM audit_log WHERE seq = 2")[0]
    assert row[:4] == (pay["request_hash"], "agent-7", "user-123", "invoice:INV-2048")
    assert row[4]["nonce"] == pay["nonce"] and row[4]["amount"] == "4800.00"
    assert audit.run_verify(kit.pg, kit.signer.public_key_b64()) == (0, "audit: OK (2 entries, 2 checkpoints)")


def test_denies_and_refusals_are_audited(kit):
    kit.gate.prepare({"tool": "nope"}, {})
    req, receipt = _review(kit)
    with pytest.raises(ReviewRefused):
        kit.mint(receipt, req, "admin-ops")
    token = kit.mint(receipt, req, "rev-alice")
    assert kit.gate.commit(receipt, req, review_token=token).outcome == "EXECUTED"
    assert rules(kit.gate.commit(receipt, req, review_token=token)) == ["AP-REP-05"]
    kit.sql("INSERT INTO quarantine (record_id, nonce, created_at) VALUES ('invoice:INV-Q', 'n', 1)")
    assert kit.gate.release_quarantine("invoice:INV-Q", "rev-bob") is True
    log = _log(kit.db)
    assert [(k, d) for k, d, *_ in log] == [
        ("prepare", "DENY"), ("prepare", "REVIEW"), ("mint", "REFUSED"), ("mint", "MINTED"),
        ("commit", "EXECUTED"), ("commit", "DENY"), ("release_quarantine", "RELEASED")]
    assert log[0][2][0]["rule"] == "AP-VER-01"
    assert log[2][2][0]["rule"] == "AP-SEP-12" and log[2][3]["reviewer_login"] == "admin-ops"
    assert log[3][3] == {"reviewer_login": "rev-alice", "reviewer_person": "p-alice"}
    assert log[4][3]["reviewer"] == "rev-alice"
    assert log[5][2][0]["rule"] == "AP-REP-05"
    assert log[6][3] == {"reviewer": "rev-bob"}
    assert audit.run_verify(kit.pg, kit.signer.public_key_b64())[0] == 0


def test_audit_failure_inside_commit_denies(kit, monkeypatch):
    """Fail closed: the EXECUTED entry is written in the commit tx BEFORE the tool; if it fails, nothing runs."""
    req, docs = kit.json_request("INV-AUD2", "100.00")
    p = kit.gate.prepare(req, docs)
    assert p.decision == "ALLOW"
    real = audit.append

    def flaky(conn, kind, **f):
        if kind == "commit" and f.get("decision") == "EXECUTED":
            raise RuntimeError("disk full")
        return real(conn, kind, **f)

    monkeypatch.setattr(audit, "append", flaky)
    c = kit.gate.commit(p.receipt, req)
    assert c.outcome == "DENY" and rules(c) == ["AP-ERR-11"] and c.tool_result is None
    assert kit.tool.calls == [] and kit.executes == 0 and kit.commits() == 0
    assert kit.version("invoice:INV-AUD2") == 1
    assert [(k, d) for k, d, *_ in _log(kit.db)][-1] == ("commit", "DENY")
    monkeypatch.setattr(audit, "append", real)
    assert kit.gate.commit(p.receipt, req).outcome == "EXECUTED"  # the failed attempt rolled back cleanly
    assert audit.run_verify(kit.pg, kit.signer.public_key_b64())[0] == 0


def test_audit_failure_at_prepare_withholds_the_receipt(kit, monkeypatch):
    real = audit.append

    def flaky(conn, kind, **f):
        if kind == "prepare" and f.get("decision") != "DENY":
            raise RuntimeError("disk full")
        return real(conn, kind, **f)

    monkeypatch.setattr(audit, "append", flaky)
    req, docs = kit.json_request("INV-AUD3", "100.00")
    p = kit.gate.prepare(req, docs)
    assert p.decision == "DENY" and rules(p) == ["AP-ERR-11"] and p.receipt is None


def test_audit_failure_never_turns_a_deny_into_an_execution(kit, monkeypatch):
    def broken(conn, kind, **f):
        raise RuntimeError("disk full")

    monkeypatch.setattr(audit, "append", broken)
    req, docs = kit.json_request("INV-AUD4", "100.00")
    assert kit.gate.prepare(req, docs).decision == "DENY"
    assert rules(kit.gate.commit({"payload": {}, "sig": "x", "kid": "k1"}, req)) == ["AP-SIG-09"]
    assert kit.tool.calls == []


def test_checkpoint_cadence_from_settings(kit):
    kit.gate._settings = kit.settings.model_copy(update={"audit_checkpoint_every": 2})
    for i in range(5):
        kit.gate.prepare({"tool": f"nope{i}"}, {})
    assert kit.sql("SELECT seq FROM audit_checkpoints ORDER BY seq") == [(2,), (4,)]
    assert audit.run_verify(kit.pg, kit.signer.public_key_b64()) == (0, "audit: OK (5 entries, 2 checkpoints)")


def test_entries_hold_no_secrets(kit, signing_key_path):
    seed = signing_key_path.read_bytes()
    req, receipt = _review(kit, "INV-AUD5")
    token = kit.mint(receipt, req, "rev-alice")
    assert kit.gate.commit(receipt, req, review_token=token).outcome == "EXECUTED"
    req2, docs2 = kit.json_request("INV-AUD6", "100.00")
    p2 = kit.gate.prepare(req2, docs2)

    def hostile(*a, **kw):
        raise RuntimeError(f"boom {seed.hex()} Traceback")

    kit.tool.execute = hostile
    assert kit.gate.commit(p2.receipt, req2).outcome == "DENY"
    blob = "\n".join(r[0] for r in kit.sql(
        "SELECT row_to_json(a)::text FROM audit_log a UNION ALL SELECT row_to_json(c)::text FROM audit_checkpoints c"))
    for secret in (seed.hex(), seed.hex().upper(), base64.b64encode(seed).decode(),
                   base64.urlsafe_b64encode(seed).decode(), token, receipt["sig"], p2.receipt["sig"], "Traceback"):
        assert secret not in blob


def test_checkpoint_every_config():
    good = {"DATABASE_URL": "postgresql://x", "OPA_URL": "http://x", "TESSERACT_CMD": "t", "SIGNING_KEY_PATH": "k"}
    assert load_settings(good).audit_checkpoint_every == 1
    assert load_settings({**good, "AUDIT_CHECKPOINT_EVERY": "10"}).audit_checkpoint_every == 10
    for bad in ("0", "-1", "1.5", "x"):
        with pytest.raises(ConfigError):
            load_settings({**good, "AUDIT_CHECKPOINT_EVERY": bad})


# ------------------------------------------------------------------ verifier CLI


def _cli(env: dict, *args) -> subprocess.CompletedProcess:
    base = {k: os.environ[k] for k in ("SYSTEMROOT", "PATH") if k in os.environ}
    return subprocess.run([sys.executable, "-m", "actionproof.audit", "verify", *args], capture_output=True,
                          text=True, timeout=60, env={**base, "PYTHONPATH": str(ROOT / "src"), **env})


def test_cli_needs_only_database_url_and_public_key(db, pg, signer, tmp_path):
    _entries(db, signer, 3)
    pub = tmp_path / "audit.pub"
    pub.write_text(signer.public_key_b64() + "\n", encoding="ascii")
    ok = _cli({"DATABASE_URL": pg, "AUDIT_PUBLIC_KEY_PATH": str(pub)})
    assert (ok.returncode, ok.stdout.strip()) == (0, "audit: OK (3 entries, 3 checkpoints)"), ok.stderr
    _tamper(pg, "DELETE FROM audit_log WHERE seq = 2")
    bad = _cli({"DATABASE_URL": pg}, "--public-key", signer.public_key_b64())
    assert (bad.returncode, bad.stdout.strip()) == (1, "audit: FAILED at seq 2: entry missing or out of order (found seq 3)")


def test_cli_main_config_errors(pg, capsys, signing_key_path):
    assert audit.main(["verify"], env={"DATABASE_URL": pg}) == 2  # no public key at all
    assert audit.main(["verify", "--public-key", "not-base64!"], env={"DATABASE_URL": pg}) == 2
    assert audit.main(["verify", "--public-key", base64.b64encode(b"x" * 32).decode()], env={}) == 2  # no DB url
    # the raw seed file is not a public key (and is never read as one)
    assert audit.main(["verify"], env={"DATABASE_URL": pg, "AUDIT_PUBLIC_KEY_PATH": str(signing_key_path)}) == 2
    err = capsys.readouterr().err
    assert "audit: config error" in err and signing_key_path.read_bytes().hex() not in err


# ------------------------------------------------------------------ key rotation: kid -> public key map


def _rotated(db, signer):
    """Entries 1-2 checkpointed by k1, entries 3-4 by k2 (a rotation in the middle of the chain)."""
    k2 = Signer(SigningKey.generate(), "k2")
    _entries(db, signer, 2)
    _entries(db, k2, 2)
    return k2


def test_rotation_full_chain_verifies_with_kid_map(db, pg, signer):
    k2 = _rotated(db, signer)
    keys = {"k1": signer.public_key_b64(), "k2": k2.public_key_b64()}
    assert _check(pg, keys) == (0, "audit: OK (4 entries, 4 checkpoints)")
    # the single-key form still works and still fails at the first checkpoint it cannot verify
    assert _check(pg, signer.public_key_b64()) == (1, "audit: FAILED at seq 3: checkpoint signature invalid")
    # a kid mapped to the wrong key is a signature failure, not a pass
    assert _check(pg, {**keys, "k2": signer.public_key_b64()}) == (1, "audit: FAILED at seq 3: checkpoint signature invalid")


def test_unknown_kid_fails(db, pg, signer):
    k2 = _rotated(db, signer)
    assert _check(pg, {"k1": signer.public_key_b64()}) == (1, "audit: FAILED at seq 3: checkpoint signed by an unknown kid")
    assert k2.kid == "k2"


def test_cli_keys_dir(db, pg, signer, tmp_path):
    k2 = _rotated(db, signer)
    d = tmp_path / "pubs"
    d.mkdir()
    (d / "k1.pub").write_text(signer.public_key_b64() + "\n", encoding="ascii")
    (d / "k2.pub").write_text(k2.public_key_b64() + "\n", encoding="ascii")
    ok = _cli({"DATABASE_URL": pg, "AUDIT_PUBLIC_KEYS_DIR": str(d)})
    assert (ok.returncode, ok.stdout.strip()) == (0, "audit: OK (4 entries, 4 checkpoints)"), ok.stderr
    (d / "k2.pub").unlink()
    bad = _cli({"DATABASE_URL": pg, "AUDIT_PUBLIC_KEYS_DIR": str(d)})
    assert (bad.returncode, bad.stdout.strip()) == (1, "audit: FAILED at seq 3: checkpoint signed by an unknown kid")
    (d / "k1.pub").unlink()
    assert audit.main(["verify"], env={"DATABASE_URL": pg, "AUDIT_PUBLIC_KEYS_DIR": str(d)}) == 2  # empty dir
    (d / "k3.pub").write_text("not-base64!", encoding="ascii")
    assert audit.main(["verify"], env={"DATABASE_URL": pg, "AUDIT_PUBLIC_KEYS_DIR": str(d)}) == 2
