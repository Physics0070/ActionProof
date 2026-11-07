"""Demo state in one command (ADR-009): python scripts/demo_seed.py --reset

--reset wipes every table (commits, review tokens, quarantine, records, people, the audit chain: db.reset), so each
take starts from the same state and its audit chain verifies from seq 1. Then, idempotently, it seeds:
- the invoice hero (INV-2048 / PO-2048, user-123's delegation, the people directory): db.seed_hero
- the refund connector: PAY-7731 (CUST-311, 450.00, pm_card_4242) and the benign payments: db.seed_refunds
- 4800.00 of earlier committed refunds for (agent-7, CUST-311) across PAY-7001..7004 (1200.00 each, fully refunded)

so that: REF-311 (injected destination) -> DENY AP-VER-01 (taint on refund_to); the clean 250.00 retry ->
DENY AP-CUM-03 (4800 + 250 > 5000); REF-312 (150.00) -> executes exactly once.
Without --reset it only upserts (existing commits are kept). DATABASE_URL comes from the environment (invariant 7).
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from psycopg.types.json import Jsonb  # noqa: E402

from actionproof import db  # noqa: E402

ACTOR, ON_BEHALF_OF, CUSTOMER, METHOD = "agent-7", "user-123", "CUST-311", "pm_card_4242"
PRIOR_REFUNDS = tuple((f"PAY-700{i}", "1200.00") for i in range(1, 5))  # 4 x 1200.00 = 4800.00


def seed(conn, reset: bool) -> None:
    db.apply_schema(conn)
    if reset:
        db.reset(conn)
    db.seed_hero(conn)
    db.seed_refunds(conn)
    now = int(time.time())
    for payment_id, amount in PRIOR_REFUNDS:
        conn.execute(
            "INSERT INTO records (record_id, kind, data, version) VALUES (%s, 'payment', %s, 2) "
            "ON CONFLICT (record_id) DO UPDATE SET data = EXCLUDED.data, version = 2",
            (f"payment:{payment_id}", Jsonb({"customer_id": CUSTOMER, "amount": amount, "method_id": METHOD,
                                             "status": "captured", "refunded": amount})))
        conn.execute(
            "INSERT INTO commits (nonce, idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount, "
            "record_id, created_at) VALUES (%s, %s, 'demo-seed', %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (f"seed-refund-{payment_id}", f"seed-refund-{payment_id}", ACTOR, ON_BEHALF_OF, CUSTOMER, amount,
             f"payment:{payment_id}", now))
    conn.commit()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reset", action="store_true", help="wipe all demo state first (including the audit chain)")
    args = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    with db.connect(url=url) as conn:
        seed(conn, args.reset)
    print(f"demo seeded{' (reset)' if args.reset else ''}: INV-2048 hero, PAY-7731, "
          f"{len(PRIOR_REFUNDS)} prior refunds for ({ACTOR}, {CUSTOMER})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
