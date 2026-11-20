"""Local append-only checkpoint anchor + `audit verify --anchor [--strict]`.

The anchor is a second copy of the signed checkpoints outside the database. It catches what the in-database
checkpoints cannot: an attacker who deletes the newest audit entries AND their checkpoints together. A file on the
same machine is NOT immutable storage (a root user rewrites both): see docs/THREAT_MODEL.md.
"""
import json
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest

from actionproof import anchor, audit
from actionproof import db as dbmod
from actionproof.signing import Signer


@pytest.fixture
def signer(signing_key_path):
    return Signer.from_path(signing_key_path, "k1")


def _entries(conn, signer, n=5, tag=0):
    for i in range(n):
        audit.append(conn, "test", decision="ALLOW", rules=[], detail={"i": i, "tag": tag})
        audit.checkpoint(conn, signer)
        conn.commit()


def _tamper(pg, *statements):
    with dbmod.connect(url=pg) as su:
        su.execute("SET session_replication_role = replica")  # skips the append-only trigger, like a superuser
        for q in statements:
            su.execute(q)


def _publish_latest(db, path, pub):
    env = audit.latest_checkpoint(db)
    db.commit()
    return anchor.LocalAnchor(path).publish(env, pub)


def test_publish_is_idempotent_and_monotonic(db, signer, tmp_path):
    _entries(db, signer, 3)
    a, pub = tmp_path / "a.jsonl", signer.public_key_b64()
    assert _publish_latest(db, a, pub) is True
    assert _publish_latest(db, a, pub) is False            # same seq, same head: no-op
    assert len(a.read_text().splitlines()) == 1
    _entries(db, signer, 2)
    assert _publish_latest(db, a, pub) is True
    assert [e["checkpoint"]["payload"]["seq"] for e in anchor.LocalAnchor(a).entries(pub)] == [3, 5]


def test_conflicting_or_older_checkpoint_is_refused(db, signer, tmp_path):
    _entries(db, signer, 3)
    a, pub = tmp_path / "a.jsonl", signer.public_key_b64()
    _publish_latest(db, a, pub)
    good = audit.latest_checkpoint(db)
    db.commit()
    forged = {**good, "payload": {**good["payload"], "head_hash": "0" * 64}}      # same seq, other head
    with pytest.raises(anchor.AnchorError):
        anchor.LocalAnchor(a).publish(forged, pub)
    older = {"payload": {**good["payload"], "seq": 2}, "sig": good["sig"], "kid": good["kid"]}
    with pytest.raises(anchor.AnchorError):
        anchor.LocalAnchor(a).publish(older, pub)
    assert len(a.read_text().splitlines()) == 1


def test_unsigned_or_wrong_key_checkpoint_is_refused(db, signer, tmp_path):
    _entries(db, signer, 2)
    env = audit.latest_checkpoint(db)
    db.commit()
    with pytest.raises(anchor.AnchorError):
        anchor.LocalAnchor(tmp_path / "a.jsonl").publish({**env, "sig": "AAAA"}, signer.public_key_b64())
    with pytest.raises(anchor.AnchorError):
        anchor.LocalAnchor(tmp_path / "a.jsonl").publish(env, {"k9": signer.public_key_b64()})  # unknown kid


def test_fully_anchored_verifies_strict(db, pg, signer, tmp_path):
    _entries(db, signer)
    a, pub = tmp_path / "a.jsonl", signer.public_key_b64()
    _publish_latest(db, a, pub)
    code, line = audit.run_verify(pg, pub, anchor=a, strict=True)
    assert code == 0 and "anchored through seq 5" in line and "fully anchored" in line


def test_unanchored_tail_is_reported_and_fails_only_in_strict(db, pg, signer, tmp_path):
    _entries(db, signer, 3)
    a, pub = tmp_path / "a.jsonl", signer.public_key_b64()
    _publish_latest(db, a, pub)
    _entries(db, signer, 2)                                  # seq 4..5 never anchored
    code, line = audit.run_verify(pg, pub, anchor=a, strict=False)
    assert code == 0 and "anchored through seq 3" in line and "unanchored 4..5" in line
    code, line = audit.run_verify(pg, pub, anchor=a, strict=True)
    assert code == 1 and "unanchored tail" in line and "4..5" in line


def test_tail_deleted_with_its_checkpoints_is_caught_by_the_anchor(db, pg, signer, tmp_path):
    """The attack the in-database checkpoints cannot see: delete the newest entries AND their checkpoints."""
    _entries(db, signer)
    a, pub = tmp_path / "a.jsonl", signer.public_key_b64()
    _publish_latest(db, a, pub)
    _tamper(pg, "DELETE FROM audit_checkpoints WHERE seq >= 4", "DELETE FROM audit_log WHERE seq >= 4")
    assert audit.run_verify(pg, pub)[0] == 0                 # the database alone is blind to it
    code, line = audit.run_verify(pg, pub, anchor=a)
    assert code == 1 and "older than the external anchor" in line


def test_rewritten_history_is_caught_by_the_anchor(db, pg, signer, tmp_path):
    _entries(db, signer, 4)
    a, pub = tmp_path / "a.jsonl", signer.public_key_b64()
    _publish_latest(db, a, pub)
    # rewrite the whole history consistently (fresh chain + fresh checkpoints signed by the real key)
    _tamper(pg, "TRUNCATE audit_checkpoints, audit_log")
    _entries(db, signer, 4, tag=1)
    code, line = audit.run_verify(pg, pub, anchor=a)
    assert code == 1 and "does not match" in line


def test_anchor_file_tampering_is_detected(db, pg, signer, tmp_path):
    _entries(db, signer, 2)
    a, pub = tmp_path / "a.jsonl", signer.public_key_b64()
    _publish_latest(db, a, pub)
    _entries(db, signer, 2)
    _publish_latest(db, a, pub)
    _entries(db, signer, 2)
    _publish_latest(db, a, pub)
    lines = a.read_text().splitlines()
    assert len(lines) == 3
    cases = {
        "deleted middle": [lines[0], lines[2]],
        "reordered": [lines[1], lines[0], lines[2]],
        "edited": [lines[0], lines[1].replace('"seq":4', '"seq":3'), lines[2]],
        "garbage": [lines[0], "not json"],
    }
    assert cases["edited"] != lines
    for name, body in cases.items():
        a.write_text("\n".join(body) + "\n")
        code, line = audit.run_verify(pg, pub, anchor=a)
        assert code == 1, name


def test_strict_fails_closed_when_the_anchor_is_missing_or_empty(db, pg, signer, tmp_path):
    _entries(db, signer, 2)
    pub = signer.public_key_b64()
    assert audit.run_verify(pg, pub, anchor=tmp_path / "none.jsonl", strict=True)[0] == 1
    (tmp_path / "empty.jsonl").write_text("")
    assert audit.run_verify(pg, pub, anchor=tmp_path / "empty.jsonl", strict=True)[0] == 1
    code, line = audit.run_verify(pg, pub, anchor=tmp_path / "empty.jsonl", strict=False)
    assert code == 0 and "0 of 2" in line


def test_cli_anchor_then_strict_verify(db, pg, signer, tmp_path, capsys):
    _entries(db, signer)
    a, key = tmp_path / "a.jsonl", tmp_path / "pub"
    key.write_text(signer.public_key_b64())
    env = {"DATABASE_URL": pg, "AUDIT_PUBLIC_KEY_PATH": str(key)}
    assert audit.main(["anchor", "--anchor", str(a)], env=env) == 0
    assert audit.main(["anchor", "--anchor", str(a)], env=env) == 0          # idempotent
    assert audit.main(["verify", "--anchor", str(a), "--strict"], env=env) == 0
    assert "fully anchored" in capsys.readouterr().out
    assert audit.main(["verify", "--strict"], env=env) == 2                  # --strict needs an anchor
    assert audit.main(["verify", "--anchor", str(tmp_path / "x"), "--strict"], env=env) == 1


# ---- concurrent publishers (separate OS processes) must not corrupt the chain

CHILD = Path(__file__).with_name("anchor_child.py")


def _spawn_all(tmp_path, anchor_file, pub, envelopes):
    """Start one process per envelope, all blocked on a go-file, release them together, collect (code, stdout)."""
    go = tmp_path / "go"
    procs = []
    for i, env in enumerate(envelopes):
        ep = tmp_path / f"env{i}.json"
        ep.write_text(json.dumps(env))
        procs.append(subprocess.Popen([sys.executable, str(CHILD), str(anchor_file), str(ep), pub, str(go)],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
    time.sleep(1.0)  # let every interpreter reach its wait loop (a start-up barrier, not a race mechanism)
    go.write_text("go")
    out = []
    for pr in procs:
        so, se = pr.communicate(timeout=60)
        out.append((pr.returncode, so.strip(), se.strip()))
    return out


def _all_checkpoints(db):
    rows = db.execute("SELECT seq, head_hash, ts, sig, kid FROM audit_checkpoints ORDER BY seq").fetchall()
    db.commit()
    return [{"payload": {"seq": r[0], "head_hash": r[1], "ts": r[2]}, "sig": r[3], "kid": r[4]} for r in rows]


def test_concurrent_publish_of_the_same_checkpoint_appends_exactly_once(db, signer, tmp_path):
    _entries(db, signer, 3)
    pub, a = signer.public_key_b64(), tmp_path / "a.jsonl"
    res = _spawn_all(tmp_path, a, pub, [audit.latest_checkpoint(db)] * 8)
    db.commit()
    assert all(code == 0 for code, _, _ in res), res
    assert sorted(o for _, o, _ in res) == ["noop"] * 7 + ["published"]
    assert len(a.read_text().splitlines()) == 1
    assert len(anchor.LocalAnchor(a).entries(pub)) == 1


def test_concurrent_publish_of_different_checkpoints_keeps_one_valid_chain(db, pg, signer, tmp_path):
    _entries(db, signer, 6)
    pub, a = signer.public_key_b64(), tmp_path / "a.jsonl"
    envs = _all_checkpoints(db)
    random.Random(7).shuffle(envs)
    res = _spawn_all(tmp_path, a, pub, envs)
    assert all(code in (0, 3) for code, _, _ in res), res  # 3 = refused as older than a newer one that won the lock
    ok = sum(code == 0 for code, _, _ in res)
    entries = anchor.LocalAnchor(a).entries(pub)            # raises if any line is torn, forked or unsigned
    seqs = [e["checkpoint"]["payload"]["seq"] for e in entries]
    assert len(entries) == ok and seqs == sorted(set(seqs)) and ok >= 1
    assert len(a.read_text().splitlines()) == ok            # no lost update, no duplicate, no forked prev link
    assert audit.run_verify(pg, pub, anchor=a)[0] == 0
