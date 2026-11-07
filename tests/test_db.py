"""Schema constraints against real Postgres: G2 lives in UNIQUE/CHECK, money never as float."""
from decimal import Decimal

import psycopg
import pytest

from actionproof import db as dbmod

COMMIT = ("INSERT INTO commits (nonce, idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount,"
          " record_id, created_at) VALUES (%s, %s, 'h', 'agent-7', 'user-123', 'V-ACME', %s, 'invoice:INV-2048', 1)")


def test_schema_applies_twice(db):
    dbmod.apply_schema(db)
    dbmod.apply_schema(db)
    tables = {r[0] for r in db.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()}
    assert set(dbmod.TABLES) <= tables


def test_seed_hero_values(db):
    rows = dict(db.execute("SELECT record_id, data FROM records").fetchall())
    assert rows["invoice:INV-2048"] == {"vendor_id": "V-ACME", "total": "4800.00", "status": "open"}
    assert rows["po:PO-2048"] == {"vendor_id": "V-ACME", "total": "4300.00"}
    assert db.execute("SELECT DISTINCT version FROM records").fetchall() == [(1,)]
    assert db.execute("SELECT max_amount, vendors FROM delegations WHERE on_behalf_of='user-123'").fetchone() \
        == (Decimal("5000.00"), ["V-ACME"])


def test_seed_idempotent(db):
    dbmod.seed_hero(db)
    dbmod.seed_hero(db)
    assert db.execute("SELECT count(*) FROM records").fetchone() == (2,)
    assert db.execute("SELECT count(*) FROM delegations").fetchone() == (1,)


def test_amount_round_trips_as_decimal(db):
    db.execute(COMMIT, ("n1", "k1", "4800.00"))
    assert db.execute("SELECT amount FROM commits").fetchone() == (Decimal("4800.00"),)
    db.execute(COMMIT, ("n2", "k2", Decimal("0.10")))
    assert db.execute("SELECT amount FROM commits WHERE nonce='n2'").fetchone() == (Decimal("0.10"),)


def test_duplicate_nonce_rejected(db):
    db.execute(COMMIT, ("n1", "k1", "1.00"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(COMMIT, ("n1", "k2", "1.00"))


def test_duplicate_idempotency_key_rejected(db):
    db.execute(COMMIT, ("n1", "k1", "1.00"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(COMMIT, ("n2", "k1", "1.00"))


def test_negative_amount_rejected(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(COMMIT, ("n1", "k1", "-0.01"))


def test_negative_version_rejected(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO records VALUES ('x', 'invoice', '{}', -1)")


def test_review_token_used_fields_paired(db):
    ins = "INSERT INTO review_tokens (token, request_hash, submitter, minted_by, minted_by_person, exp, used_at, " \
          "used_nonce) VALUES (%s, 'h', 'agent-7', 'rev-alice', 'p-alice', 10, %s, %s)"
    db.execute(ins, ("t-ok", None, None))
    db.execute(ins, ("t-used", 5, "n1"))
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(ins, ("t-bad", 5, None))


def test_review_token_consumed_once(db):
    db.execute("INSERT INTO review_tokens (token, request_hash, submitter, minted_by, minted_by_person, exp) "
               "VALUES ('t', 'h', 'agent-7', 'rev-alice', 'p-alice', 100)")
    use = "UPDATE review_tokens SET used_at=%s, used_nonce=%s WHERE token='t' AND request_hash='h' " \
          "AND used_at IS NULL AND exp > %s RETURNING token"
    assert db.execute(use, (50, "n1", 50)).fetchone() == ("t",)
    assert db.execute(use, (51, "n2", 51)).fetchone() is None


@pytest.mark.parametrize("value", [4800.0, 0.1])
def test_float_amount_rejected(db, value):
    with pytest.raises(TypeError, match="float"):
        db.execute(COMMIT, ("n1", "k1", value))


def test_float_in_jsonb_rejected(db):
    with pytest.raises(TypeError, match="float"):
        db.execute("INSERT INTO records VALUES ('x', 'invoice', %s, 1)", (dbmod.Jsonb({"total": 4800.0}),))
