"""USP G1/G2 (ADR-034): signed checkpoints and anchoring for the execution journal.

The journal (ADR-029) proves its own chain, but without a signed head someone with database write access can drop
its newest events (the shortened chain still links). A gate-signed checkpoint {seq, head_hash, ts} pins the head
(a truncated tail is detected by journal.verify), and a copy of it OFF the host (LocalAnchor file, HttpAnchor stream)
detects a truncation that also deletes the checkpoints. Real Postgres; the remote is `StubAnchorServer` (a STUB, not a
WORM provider: the HTTP adapter stays UNVERIFIED against any real provider).
"""
import inspect
import json
import time

import psycopg
import pytest
from test_anchor_remote import TOKEN, StubAnchorServer, _env, _registry

from actionproof import anchor, audit, journal, reconcile
from actionproof import anchor_publisher as ap
from actionproof import db as dbmod
from actionproof.signing import KeyRegistry, Signer, generate_key

REF = {"request_hash": "h" * 64, "idempotency_key": "idem", "record_id": "invoice:INV-1", "actor": "agent-7",
       "on_behalf_of": "user-123", "vendor_id": "V-ACME", "amount": "100.00"}


@pytest.fixture
def signer(signing_key_path):
    return Signer.from_path(signing_key_path, "k1")


@pytest.fixture
def stub():
    s = StubAnchorServer()
    yield s
    s.close()


@pytest.fixture
def cfg(pg, signer, stub, tmp_path):
    return ap.load_settings(_env(pg, signer, stub, tmp_path))


def _events(conn, n, tag="a"):
    base = conn.execute("SELECT count(*) FROM execution_journal").fetchone()[0]
    for i in range(n):
        journal.append(conn, "RESERVATION_CREATED", {**REF, "nonce": f"n-{tag}-{base + i}"})
        conn.commit()


def _checkpointed(conn, signer, n, tag="a"):
    for _ in range(n):
        _events(conn, 1, tag)
        journal.checkpoint(conn, signer)
        conn.commit()


def _audit_entries(conn, signer, n):
    for i in range(n):
        audit.append(conn, "test", decision="ALLOW", rules=[], detail={"i": i})
        audit.checkpoint(conn, signer)
        conn.commit()


def _tamper(pg, *statements):
    with dbmod.connect(url=pg) as su:
        su.execute("SET session_replication_role = replica")
        for q in statements:
            su.execute(q)


def _cps(conn, table="execution_journal_checkpoints"):
    rows = conn.execute(f"SELECT seq, head_hash, ts, sig, kid FROM {table} ORDER BY seq").fetchall()
    conn.commit()
    return [{"payload": {"seq": r[0], "head_hash": r[1], "ts": r[2]}, "sig": r[3], "kid": r[4]} for r in rows]


def _cli_env(pg, signing_key_path, **over):
    """The reconcile CLI's environment. The journal subcommands never call OPA or OCR (dummy but valid values)."""
    return {"DATABASE_URL": pg, "OPA_URL": "http://127.0.0.1:9", "TESSERACT_CMD": "tesseract",
            "SIGNING_KEY_PATH": str(signing_key_path), "SIGNING_KID": "k1", **over}


def _reg(signer):
    return KeyRegistry.for_signer(signer)


# ---- the checkpoint

def test_checkpoint_is_signed_recorded_and_idempotent(db, signer):
    assert journal.checkpoint(db, signer) is None                       # empty journal: nothing to sign
    db.commit()
    assert _cps(db) == []
    _events(db, 3)
    assert journal.checkpoint(db, signer) == 3
    db.commit()
    (cp,) = _cps(db)
    head = db.execute("SELECT entry_hash FROM execution_journal WHERE seq = 3").fetchone()[0]
    assert cp["payload"]["head_hash"] == head and cp["kid"] == "k1" and _reg(signer).verify(cp)
    assert journal.latest_checkpoint(db) == cp
    assert journal.checkpoint(db, signer) == 3                          # unchanged head: no new row
    db.commit()
    assert len(_cps(db)) == 1
    _events(db, 2)
    assert journal.checkpoint(db, signer) == 5
    db.commit()
    assert [c["payload"]["seq"] for c in _cps(db)] == [3, 5]
    for keys in (_reg(signer), signer.public_key_b64(), {"k1": signer.public_key_b64()}):
        assert journal.verify(db, keys) == 5
    db.commit()


def test_checkpoint_never_takes_the_audit_lock(db, pg, signer):
    _events(db, 2)
    holder = psycopg.connect(pg)
    holder.execute("LOCK TABLE audit_log IN EXCLUSIVE MODE")           # a commit tx holding the audit lock
    holder.execute("LOCK TABLE audit_checkpoints IN EXCLUSIVE MODE")
    try:
        db.execute("SET lock_timeout = '2s'")
        assert journal.checkpoint(db, signer) == 2                      # would time out if it waited on audit
        db.commit()
    finally:
        holder.rollback()
        holder.close()
    src = inspect.getsource(journal.checkpoint)
    assert "audit." not in src and "LOCK TABLE" not in src and "_LOCK" in src  # journal advisory lock only


def test_checkpoint_append_only(db, signer):
    _checkpointed(db, signer, 1)
    for q in ("UPDATE execution_journal_checkpoints SET ts = 0", "DELETE FROM execution_journal_checkpoints",
              "TRUNCATE execution_journal_checkpoints"):
        with pytest.raises(psycopg.errors.RaiseException):
            db.execute(q)
        db.rollback()


# ---- verify: truncation, tamper, untrusted keys

def test_truncated_tail_is_detected_via_the_checkpoint(db, pg, signer, signing_key_path):
    _checkpointed(db, signer, 5)
    env = _cli_env(pg, signing_key_path)
    assert reconcile.main(["journal", "verify"], env=env) == 0
    _tamper(pg, "DELETE FROM execution_journal WHERE seq >= 4")         # tail dropped, checkpoints kept
    with pytest.raises(journal.JournalFailure, match="truncated") as f:
        journal.verify(db, _reg(signer))
    assert f.value.seq == 4
    db.rollback()
    with pytest.raises(journal.JournalFailure, match="beyond the journal head"):
        journal.checkpoint(db, signer)                                 # never signs over a truncated tail
    db.rollback()
    assert reconcile.main(["journal", "verify"], env=env) == 1


def test_truncation_that_also_deletes_the_checkpoints_is_detected_via_the_anchor(db, pg, signer, signing_key_path,
                                                                                 tmp_path, capsys):
    a = tmp_path / "journal-anchor.jsonl"
    env = _cli_env(pg, signing_key_path)
    _events(db, 5)
    assert reconcile.main(["journal", "checkpoint", "--anchor", str(a)], env=env) == 0
    assert anchor.LocalAnchor(a).latest(_reg(signer))["payload"]["seq"] == 5
    assert reconcile.main(["journal", "verify", "--anchor", str(a), "--strict"], env=env) == 0
    _tamper(pg, "DELETE FROM execution_journal WHERE seq >= 4", "DELETE FROM execution_journal_checkpoints")
    assert journal.verify(db, _reg(signer)) == 3                        # the database alone is blind to it
    db.commit()
    with pytest.raises(journal.JournalFailure, match="older than the external anchor"):
        journal.anchor_report(db, a, _reg(signer), 3, strict=False)
    db.rollback()
    capsys.readouterr()
    assert reconcile.main(["journal", "verify", "--anchor", str(a)], env=env) == 1
    assert "older than the external anchor" in capsys.readouterr().out


def test_rewritten_history_is_detected_via_the_anchor(db, pg, signer, signing_key_path, tmp_path):
    a = tmp_path / "journal-anchor.jsonl"
    env = _cli_env(pg, signing_key_path)
    _events(db, 3)
    assert reconcile.main(["journal", "checkpoint", "--anchor", str(a)], env=env) == 0
    _tamper(pg, "TRUNCATE execution_journal_checkpoints, execution_journal")  # consistent rewrite, real key
    _events(db, 3, tag="forged")
    assert reconcile.main(["journal", "checkpoint"], env=env) == 0
    assert reconcile.main(["journal", "verify"], env=env) == 0          # internally consistent
    assert reconcile.main(["journal", "verify", "--anchor", str(a)], env=env) == 1
    assert reconcile.main(["journal", "checkpoint", "--anchor", str(a)], env=env) == 1  # anchor refuses the conflict


def test_a_tampered_checkpoint_row_is_detected(db, pg, signer):
    _checkpointed(db, signer, 3)
    good = _cps(db)
    for stmt, why in (("UPDATE execution_journal_checkpoints SET head_hash = repeat('f', 64) WHERE seq = 2",
                       "head_hash does not match"),
                      ("UPDATE execution_journal_checkpoints SET ts = ts + 1 WHERE seq = 2", "signature invalid"),
                      ("UPDATE execution_journal_checkpoints SET sig = 'AAAA' WHERE seq = 2", "signature invalid"),
                      ("UPDATE execution_journal_checkpoints SET seq = 9 WHERE seq = 3", "truncated")):
        db.execute("ALTER TABLE execution_journal_checkpoints DISABLE TRIGGER USER")
        db.execute(stmt)
        db.execute("ALTER TABLE execution_journal_checkpoints ENABLE TRIGGER USER")
        db.commit()
        with pytest.raises(journal.JournalFailure, match=why):
            journal.verify(db, _reg(signer))
        db.rollback()
        _tamper(pg, "DELETE FROM execution_journal_checkpoints")         # restore the honest rows
        with dbmod.connect(url=pg) as c:
            for cp in good:
                p = cp["payload"]
                c.execute("INSERT INTO execution_journal_checkpoints VALUES (%s, %s, %s, %s, %s)",
                          (p["seq"], p["head_hash"], p["ts"], cp["sig"], cp["kid"]))
        assert journal.verify(db, _reg(signer)) == 3
        db.commit()


def test_a_checkpoint_by_an_unknown_or_revoked_kid_fails(db, signer, tmp_path):
    other = tmp_path / "other.key"
    generate_key(other)
    k2 = Signer.from_path(other, "k2")
    _events(db, 2)
    journal.checkpoint(db, k2)                                         # signed, but by a key nobody trusts
    db.commit()
    for keys in (_reg(signer), {"k1": signer.public_key_b64()}):
        with pytest.raises(journal.JournalFailure, match="unknown kid"):
            journal.verify(db, keys)
        db.rollback()
    with pytest.raises(journal.JournalFailure, match="signature invalid"):
        journal.verify(db, signer.public_key_b64())                     # one key: checks every kid against it
    db.rollback()
    revoked = KeyRegistry({"k1": (signer.public_key_b64(), "active"), "k2": (k2.public_key_b64(), "revoked")})
    with pytest.raises(journal.JournalFailure, match="revoked"):
        journal.verify(db, revoked)
    db.rollback()
    imposter = Signer.from_path(other, "k1")                            # another key claiming the trusted kid
    _events(db, 1)
    journal.checkpoint(db, imposter)
    db.commit()
    with pytest.raises(journal.JournalFailure):
        journal.verify(db, KeyRegistry({"k1": (signer.public_key_b64(), "active"),
                                        "k2": (k2.public_key_b64(), "retired")}))
    db.rollback()


def test_checkpoints_without_a_trusted_key_fail_closed(db, signer):
    _events(db, 2)
    assert journal.verify(db) == 2                                      # chain only: no checkpoint to check yet
    journal.checkpoint(db, signer)
    db.commit()
    with pytest.raises(journal.JournalFailure, match="no trusted public key"):
        journal.verify(db)
    db.rollback()


# ---- two streams, never mixed

def test_streams_never_collide_in_the_local_anchor(db, pg, signer, signing_key_path, tmp_path):
    _audit_entries(db, signer, 3)
    _checkpointed(db, signer, 3)                                         # both streams hold seq 1..3
    audit_file, journal_file = tmp_path / "audit-anchor.jsonl", tmp_path / "journal-anchor.jsonl"
    for cp in _cps(db, "audit_checkpoints"):
        anchor.LocalAnchor(audit_file).publish(cp, _reg(signer))
    env = _cli_env(pg, signing_key_path, AUDIT_ANCHOR_PATH=str(audit_file))
    assert reconcile.main(["journal", "checkpoint", "--anchor", str(audit_file)], env=env) == 2  # same file refused
    assert reconcile.main(["journal", "checkpoint", "--anchor", str(journal_file)], env=env) == 0
    assert reconcile.main(["journal", "verify", "--anchor", str(journal_file), "--strict"], env=env) == 0
    a = [e["checkpoint"] for e in anchor.LocalAnchor(audit_file).entries(_reg(signer))]
    j = [e["checkpoint"] for e in anchor.LocalAnchor(journal_file).entries(_reg(signer))]
    assert [c["payload"]["seq"] for c in a] == [1, 2, 3] and [c["payload"]["seq"] for c in j] == [3]
    assert a == _cps(db, "audit_checkpoints") and j == _cps(db)[-1:]
    assert {c["payload"]["head_hash"] for c in a}.isdisjoint({c["payload"]["head_hash"] for c in j})
    # a mixed-up anchor (the audit file handed to the journal verifier) is caught, not accepted
    assert reconcile.main(["journal", "verify", "--anchor", str(audit_file)], env={**env, "AUDIT_ANCHOR_PATH": ""}) == 1
    assert audit.run_verify(pg, signer.public_key_b64(), anchor=audit_file, strict=True)[0] == 0


def test_streams_never_collide_in_the_remote(db, signer, stub, cfg):
    _audit_entries(db, signer, 3)
    _checkpointed(db, signer, 3)
    code, lines = ap.cycle(cfg, *ap.build(cfg), publish=True)
    assert code == 0, lines
    assert stub.accepted == [1, 2, 3] and stub.journal.accepted == [1, 2, 3]
    assert [stub.store[s] for s in (1, 2, 3)] == _cps(db, "audit_checkpoints")
    assert [stub.journal.store[s] for s in (1, 2, 3)] == _cps(db)
    assert {c["payload"]["head_hash"] for c in stub.store.values()}.isdisjoint(
        {c["payload"]["head_hash"] for c in stub.journal.store.values()})
    assert any(x.startswith("anchor-remote[journal]: OK") and "through seq 3" in x for x in lines), lines
    code, lines = ap.cycle(cfg, *ap.build(cfg), publish=False)
    assert code == 0, lines
    # a journal checkpoint served on the audit stream (a mixed-up or lying remote) is flagged as a conflict
    stub.store[3] = stub.journal.store[3]
    code, lines = ap.cycle(cfg, *ap.build(cfg), publish=False)
    assert code == 1 and any(x.startswith("anchor-remote: FAILED") and "seq 3" in x for x in lines), lines


# ---- the publisher: both streams, in order, recovery, monitoring

def test_publisher_publishes_both_streams_in_order_and_recovers(db, signer, stub, cfg):
    _audit_entries(db, signer, 2)
    _checkpointed(db, signer, 2)
    assert ap.cycle(cfg, *ap.build(cfg), publish=True)[0] == 0
    assert stub.order == [("audit", 1), ("audit", 2), ("journal", 1), ("journal", 2)]   # audit first, each in seq order
    assert ap.cycle(cfg, *ap.build(cfg), publish=True)[0] == 0 and len(stub.order) == 4  # idempotent
    stub.down = True                                                     # outage
    _checkpointed(db, signer, 3)
    code, lines = ap.cycle(cfg, *ap.build(cfg), publish=True)
    assert code == 0 and any(x.startswith("anchor-remote[journal]: WARN") for x in lines), lines
    assert stub.journal.accepted == [1, 2]
    code, lines = ap.cycle(cfg, *ap.build(cfg), publish=True, now=time.time() + 1000)
    assert code == 1 and any(x.startswith("anchor-remote[journal]: LAG") for x in lines), lines  # lag per stream
    stub.down, stub.journal.fail_after = False, 3                        # back, fails again mid-backlog
    code, lines = ap.cycle(cfg, *ap.build(cfg), publish=True)
    assert code == 0 and stub.journal.accepted == [1, 2, 3], lines
    stub.journal.fail_after = None
    assert ap.cycle(cfg, *ap.build(cfg), publish=True)[0] == 0
    assert stub.journal.accepted == [1, 2, 3, 4, 5] == [c["payload"]["seq"] for c in _cps(db)]
    assert stub.accepted == [1, 2]                                       # the audit stream was never disturbed
    assert ap.cycle(cfg, *ap.build(cfg), publish=False)[0] == 0
    remote, reg = ap.build(cfg)
    assert ap.run(cfg, remote, reg, iterations=1, sleep=lambda s: None) == 0


def test_journal_rewind_rollback_and_gap_are_detected_by_the_remote(db, pg, signer, stub, cfg, tmp_path):
    _checkpointed(db, signer, 5)
    assert ap.cycle(cfg, *ap.build(cfg), publish=True)[0] == 0
    _tamper(pg, "DELETE FROM execution_journal_checkpoints WHERE seq >= 4", "DELETE FROM execution_journal WHERE seq >= 4")
    assert journal.verify(db, _reg(signer)) == 3                        # the database alone is blind to it
    db.commit()
    code, lines = ap.cycle(cfg, *ap.build(cfg), publish=False)
    assert code == 1 and any(x.startswith("anchor-remote[journal]: FAILED") and "rewound" in x for x in lines), lines
    assert not any(x.startswith("anchor-remote: FAILED") for x in lines)  # the audit stream is fine
    _tamper(pg, "TRUNCATE execution_journal_checkpoints, execution_journal")
    _checkpointed(db, signer, 5, tag="b")                                 # rebuilt honestly-shaped, different events
    assert ap.cycle(cfg, *ap.build(cfg), publish=False)[0] == 1           # conflicting heads
    stub.journal.store.clear()
    stub.journal.accepted.clear()
    fresh = cfg.model_copy(update={"anchor_state_path": str(tmp_path / "fresh-state.json")})
    assert ap.cycle(fresh, *ap.build(fresh), publish=True)[0] == 0
    del stub.journal.store[5], stub.journal.store[4]                     # remote journal stream rolled back
    code, lines = ap.cycle(fresh, *ap.build(fresh), publish=False)
    assert code == 1 and any("[journal]" in x and "rolled back" in x for x in lines), lines
    stub.journal.store[4], stub.journal.store[5] = (c for c in _cps(db)[3:])
    del stub.journal.store[2]
    code, lines = ap.cycle(fresh, *ap.build(fresh), publish=False)
    assert code == 1 and any("[journal]" in x and "missing checkpoint seq 2" in x for x in lines), lines


def test_check_verifies_the_full_journal_chain(db, pg, signer, stub, cfg):
    _checkpointed(db, signer, 3)
    assert ap.cycle(cfg, *ap.build(cfg), publish=True)[0] == 0
    _tamper(pg, "UPDATE execution_journal SET amount = 1.00 WHERE seq = 2")
    code, lines = ap.cycle(cfg, *ap.build(cfg), publish=False)
    assert code == 1 and any(x.startswith("anchor-remote[journal]: FAILED") and "seq 2" in x for x in lines), lines


def test_no_http_request_while_a_database_transaction_is_open_journal_stream(db, signer, stub, cfg, monkeypatch):
    opened, seen = [], []
    real = psycopg.connect

    def tracked(*a, **kw):
        c = real(*a, **kw)
        opened.append(c)
        return c

    def guard(request):
        seen.append((request.method, request.url.path))
        assert all(c.closed or c.info.transaction_status == psycopg.pq.TransactionStatus.IDLE for c in opened), \
            f"HTTP {request.method} while a database transaction is open"

    monkeypatch.setattr(ap.psycopg, "connect", tracked)
    _audit_entries(db, signer, 2)
    _checkpointed(db, signer, 3)
    hooks = {"request": [guard]}
    remote, reg = ap.build(cfg, event_hooks=hooks)
    jremote = ap.build_journal(cfg, event_hooks=hooks)
    assert ap.cycle(cfg, remote, reg, publish=True, journal_remote=jremote)[0] == 0
    assert ap.cycle(cfg, remote, reg, publish=False, journal_remote=jremote)[0] == 0
    assert [m for m, p in seen if p.startswith("/journal/")].count("PUT") == 3
    assert [m for m, p in seen if not p.startswith("/journal/")].count("PUT") == 2
    c = tracked(cfg.database_url.get_secret_value())                    # control: the guard really fires
    c.execute("SELECT 1")
    with pytest.raises(AssertionError, match="transaction is open"):
        jremote.entries(reg)
    c.close()


def test_gate_commits_with_the_anchor_unreachable(kit, signer, stub, cfg, pg, signing_key_path, tmp_path):
    stub.down = True
    req, docs = kit.json_request("INV-7302", "100.00")
    r = kit.gate.prepare(req, docs)
    assert r.receipt is not None, r.reasons
    assert kit.gate.commit(r.receipt, req).outcome == "EXECUTED" and kit.executes == 1
    env = _cli_env(pg, signing_key_path, SIGNING_KID=kit.settings.signing_kid)
    dead = tmp_path / "no-such-dir" / "journal-anchor.jsonl"           # the local anchor is unreachable too
    assert reconcile.main(["journal", "checkpoint", "--anchor", str(dead)], env=env) == 1
    assert kit.sql("SELECT count(*) FROM execution_journal_checkpoints")[0][0] == 1  # the signed head is kept
    code, lines = ap.cycle(cfg, *ap.build(cfg), publish=True)
    assert code == 0 and any(x.startswith("anchor-remote[journal]: WARN") for x in lines), lines
    req2, docs2 = kit.json_request("INV-7303", "100.00")
    r2 = kit.gate.prepare(req2, docs2)
    assert kit.gate.commit(r2.receipt, req2).outcome == "EXECUTED" and kit.executes == 2


# ---- CLI

def test_cli_journal_checkpoint_and_verify(db, pg, signer, signing_key_path, tmp_path, capsys):
    env = _cli_env(pg, signing_key_path)
    a = tmp_path / "journal-anchor.jsonl"
    assert reconcile.main(["journal", "checkpoint"], env=env) == 0       # empty: nothing to sign, not an error
    assert "nothing to checkpoint" in capsys.readouterr().out
    _events(db, 2)
    assert reconcile.main(["journal", "checkpoint", "--anchor", str(a)], env=env) == 0
    assert reconcile.main(["journal", "checkpoint", "--anchor", str(a)], env=env) == 0   # idempotent
    out = capsys.readouterr().out
    assert "checkpointed seq 2" in out and "already anchored" in out
    assert reconcile.main(["journal", "verify"], env=env) == 0
    assert "journal: OK (2 events, 1 checkpoints)" in capsys.readouterr().out
    assert reconcile.main(["journal", "verify", "--strict"], env=env) == 2          # strict needs an anchor
    _events(db, 1)
    assert reconcile.main(["journal", "verify", "--anchor", str(a)], env=env) == 0
    assert "unanchored 3..3" in capsys.readouterr().out
    assert reconcile.main(["journal", "verify", "--anchor", str(a), "--strict"], env=env) == 1
    assert reconcile.main(["journal", "verify", "--anchor", str(a)], env={**env, "JOURNAL_ANCHOR_PATH": str(a)}) == 0
    assert reconcile.main(["journal", "verify", "--strict"], env={**env, "JOURNAL_ANCHOR_PATH": str(a)}) == 1
    reg = _registry(tmp_path, {"k1": (signer.public_key_b64(), "revoked")})
    assert reconcile.main(["journal", "verify"], env={**env, "KEY_REGISTRY_PATH": str(reg)}) == 1  # k1 distrusted
    assert reconcile.main(["journal", "verify"], env={**env, "KEY_REGISTRY_PATH": str(tmp_path / "nope.json")}) == 2
    assert reconcile.main(["journal", "checkpoint"], env={**env, "SIGNING_KEY_PATH": str(tmp_path / "nope.key")}) == 2
    out = capsys.readouterr()
    assert pg not in out.out + out.err and TOKEN not in out.out + out.err
    assert json.loads(a.read_text().splitlines()[0])["checkpoint"]["payload"]["seq"] == 2
