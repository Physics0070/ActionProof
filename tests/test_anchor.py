"""Local append-only checkpoint anchor + `audit verify --anchor [--strict]`.

The anchor is a second copy of the signed checkpoints outside the database. It catches what the in-database
checkpoints cannot: an attacker who deletes the newest audit entries AND their checkpoints together. A file on the
same machine is NOT immutable storage (a root user rewrites both): see docs/THREAT_MODEL.md.
"""
import json
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
