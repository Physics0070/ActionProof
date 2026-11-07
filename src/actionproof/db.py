"""Postgres access (ADR-001). Money crosses this boundary only as Decimal/str (invariant 4)."""
import json
from pathlib import Path

import psycopg
from psycopg.adapt import Dumper
from psycopg.types.json import Jsonb, set_json_dumps

from actionproof.config import load_settings

SCHEMA = Path(__file__).with_name("schema.sql")
TABLES = ("records", "delegations", "commits", "review_tokens", "quarantine", "people")
AUDIT_TABLES = ("audit_log", "audit_checkpoints")


class _NoFloatDumper(Dumper):
    """Python floats are refused as query parameters: a float can never reach a money column."""

    def dump(self, obj):
        raise TypeError("floats are not allowed as DB parameters; use Decimal or str")


def _json_dumps_no_float(obj) -> str:
    def walk(v):
        if isinstance(v, float):
            raise TypeError("floats are not allowed in jsonb; use Decimal strings")
        for x in v.values() if isinstance(v, dict) else v if isinstance(v, (list, tuple)) else ():
            walk(x)

    walk(obj)
    return json.dumps(obj)


def connect(autocommit: bool = False, url: str | None = None) -> psycopg.Connection:
    """`url` defaults to the validated DATABASE_URL (raises ConfigError if config is bad)."""
    conn = psycopg.connect(url or load_settings().database_url, autocommit=autocommit, connect_timeout=5)
    conn.adapters.register_dumper(float, _NoFloatDumper)
    set_json_dumps(_json_dumps_no_float, context=conn)
    return conn


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


HERO_RECORDS = (
    ("invoice:INV-2048", "invoice", {"vendor_id": "V-ACME", "total": "4800.00", "status": "open"}),
    ("po:PO-2048", "po", {"vendor_id": "V-ACME", "total": "4300.00"}),
)


# ADR-008 directory. agent-7 maps to its operator, the same human as user-123. Test-only logins (rev-user123, a
# second reviewer login of p-user123) are inserted by the tests, never seeded.
PEOPLE = (
    ("rev-alice", "p-alice", ("reviewer",)),
    ("rev-bob", "p-bob", ("reviewer",)),
    ("sub-user123", "p-user123", ("submitter",)),
    ("admin-ops", "p-ops", ("admin",)),
    ("user-123", "p-user123", ()),
    ("agent-7", "p-user123", ("agent",)),
)


def seed_hero(conn: psycopg.Connection) -> None:
    """Idempotent upsert of the hero scenario (records at version 1, delegation for user-123, people)."""
    for record_id, kind, data in HERO_RECORDS:
        conn.execute(
            "INSERT INTO records (record_id, kind, data, version) VALUES (%s, %s, %s, 1) "
            "ON CONFLICT (record_id) DO UPDATE SET kind = EXCLUDED.kind, data = EXCLUDED.data, version = 1",
            (record_id, kind, Jsonb(data)),
        )
    conn.execute(
        "INSERT INTO delegations (on_behalf_of, max_amount, vendors) VALUES (%s, %s::numeric, %s) "
        "ON CONFLICT (on_behalf_of) DO UPDATE SET max_amount = EXCLUDED.max_amount, vendors = EXCLUDED.vendors",
        ("user-123", "5000.00", ["V-ACME"]),
    )
    for login, person, roles in PEOPLE:
        conn.execute(
            "INSERT INTO people (login, person_id, roles) VALUES (%s, %s, %s) "
            "ON CONFLICT (login) DO UPDATE SET person_id = EXCLUDED.person_id, roles = EXCLUDED.roles",
            (login, person, list(roles)))
    conn.commit()


# Refund connector (ADR-009): original payments (payment_id, customer_id, amount, method_id). PAY-7731 is the demo
# payment; the others back the benign refund-request fixtures (fixtures/make.py REFUNDS).
PAYMENTS = (
    ("PAY-7731", "CUST-311", "450.00", "pm_card_4242"),
    ("PAY-8101", "CUST-420", "1500.00", "pm_card_5555"),
    ("PAY-8102", "CUST-512", "300.00", "pm_card_1881"),
)


def seed_refunds(conn: psycopg.Connection) -> None:
    """Idempotent upsert of the payment records (version 1, nothing refunded) and user-123's refund customer
    scope. Separate from seed_hero so the invoice hero state stays exactly as it was."""
    for payment_id, customer, amount, method in PAYMENTS:
        conn.execute(
            "INSERT INTO records (record_id, kind, data, version) VALUES (%s, 'payment', %s, 1) "
            "ON CONFLICT (record_id) DO UPDATE SET kind = EXCLUDED.kind, data = EXCLUDED.data, version = 1",
            (f"payment:{payment_id}", Jsonb({"customer_id": customer, "amount": amount, "method_id": method,
                                             "status": "captured"})),
        )
    conn.execute("UPDATE delegations SET customers = %s WHERE on_behalf_of = %s",
                 (sorted({p[1] for p in PAYMENTS}), "user-123"))
    conn.commit()


def reset(conn: psycopg.Connection) -> None:
    """Truncate every table. Tests only: the audit tables are append-only, so their triggers are switched off for
    this one transaction (owner privilege; exactly the tampering the audit verifier exists to detect)."""
    for t in AUDIT_TABLES:
        conn.execute(f"ALTER TABLE {t} DISABLE TRIGGER USER")
    conn.execute(f"TRUNCATE {', '.join(TABLES + AUDIT_TABLES)} RESTART IDENTITY")
    for t in AUDIT_TABLES:
        conn.execute(f"ALTER TABLE {t} ENABLE TRIGGER USER")
    conn.commit()
