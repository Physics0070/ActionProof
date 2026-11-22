"""USP G2 (ADR-025): review tokens are stored only as sha256 digests; the old plaintext column migrates safely.

A raw token cannot be recovered from the database; an outstanding token minted before the migration still works once;
a token used before the migration stays used (replay still AP-REP-05). Real Postgres.
"""
import hashlib

from gatekit import rules

from actionproof import db
from actionproof.gate import token_digest

OLD_TABLE = """
    DROP TABLE review_tokens;
    CREATE TABLE review_tokens (
        token text PRIMARY KEY, request_hash text NOT NULL, submitter text NOT NULL, minted_by text NOT NULL,
        minted_by_person text NOT NULL, minted_at bigint, exp bigint NOT NULL, used_at bigint NULL, used_nonce text NULL,
        CONSTRAINT review_tokens_used_pair CHECK ((used_at IS NULL) = (used_nonce IS NULL)));
"""


def _prep(kit, inv):
    req, docs = kit.json_request(inv, "4800.00", "4300.00")
    return kit.gate.prepare(req, docs).receipt, req


def test_only_digest_is_stored_and_token_is_not_recoverable(kit):
    receipt, req = _prep(kit, "INV-7001")
    token = kit.mint(receipt, req)
    assert [c for (c,) in kit.sql("SELECT column_name FROM information_schema.columns WHERE table_name='review_tokens'")
            if c == "token"] == []
    stored = kit.sql("SELECT token_hash FROM review_tokens")[0][0]
    assert stored == hashlib.sha256(token.encode()).hexdigest() == token_digest(token) and stored != token
    assert token not in repr(kit.sql("SELECT * FROM review_tokens")) + repr(kit.sql("SELECT * FROM audit_log"))
    assert kit.gate.commit(receipt, req, review_token=token).outcome == "EXECUTED"


def test_digest_or_garbage_is_not_a_token(kit):
    receipt, req = _prep(kit, "INV-7002")
    token = kit.mint(receipt, req)
    digest = kit.sql("SELECT token_hash FROM review_tokens")[0][0]
    for bad in (digest, "", None, 5):  # presenting the stored digest must not approve
        assert rules(kit.gate.commit(receipt, req, review_token=bad)) == ["AP-REV-10"]
    assert kit.tool.calls == [] and kit.gate.commit(receipt, req, review_token=token).outcome == "EXECUTED"


def test_migration_keeps_outstanding_and_used_tokens(kit):
    receipt, req = _prep(kit, "INV-7003")
    kit.db.execute(OLD_TABLE); kit.db.commit()  # noqa: E702
    p = receipt["payload"]
    kit.sql("INSERT INTO review_tokens (token, request_hash, submitter, minted_by, minted_by_person, minted_at, exp) "
            "VALUES ('plain-outstanding', %s, 'agent-7', 'rev-alice', 'p-alice', 1, %s)", (p["request_hash"], p["exp"]))
    kit.sql("INSERT INTO review_tokens (token, request_hash, submitter, minted_by, minted_by_person, minted_at, exp, "
            "used_at, used_nonce) VALUES ('plain-used', 'h2', 'agent-7', 'rev-alice', 'p-alice', 1, 99999999999, 5, 'n0')")
    db.apply_schema(kit.db); kit.db.commit()  # noqa: E702  the real migration
    cols = {r[0] for r in kit.sql("SELECT column_name FROM information_schema.columns WHERE table_name='review_tokens'")}
    assert "token" not in cols and "token_hash" in cols  # plaintext column removed
    assert kit.sql("SELECT used_at, used_nonce FROM review_tokens WHERE token_hash = %s",
                   (token_digest("plain-used"),)) == [(5, "n0")]  # used-token replay protection preserved
    assert "plain-outstanding" not in repr(kit.sql("SELECT * FROM review_tokens"))
    assert kit.gate.commit(receipt, req, review_token="plain-outstanding").outcome == "EXECUTED"  # still valid, once
    db.apply_schema(kit.db); kit.db.commit()  # noqa: E702  idempotent
