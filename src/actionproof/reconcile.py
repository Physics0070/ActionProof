"""Operator CLI for unresolved executions (ADR-019/022/024).

  python -m actionproof.reconcile check
      the explicit migration validation: lists legacy unresolved markers (unknown amount), exit 1 if any, else 0.
  python -m actionproof.reconcile release --record R --reviewer LOGIN [--executed --reservation JSON]
      the audited reconciliation (Gate.release_quarantine). --executed on a legacy marker REQUIRES --reservation,
      a JSON object {idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount}: the facts the old
      marker never recorded. Without --executed the human attests the execution did not happen.
Same environment as the API (DATABASE_URL, OPA_URL, SIGNING_KEY_PATH, DOCS_DIR, ...). Exit 2 = bad input/config.
"""
import argparse
import json
import os
import sys

import psycopg

from actionproof import db
from actionproof.config import ConfigError, load_settings


def main(argv=None, env=os.environ) -> int:
    ap = argparse.ArgumentParser(prog="python -m actionproof.reconcile")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="list legacy unresolved markers (exit 1 if any)")
    r = sub.add_parser("release", help="audited reconciliation of an unresolved execution")
    r.add_argument("--record", required=True)
    r.add_argument("--reviewer", required=True)
    r.add_argument("--executed", action="store_true", help="the human confirms the execution DID happen")
    r.add_argument("--reservation", help="JSON {idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount}")
    args = ap.parse_args(argv)
    try:
        settings = load_settings(env)
        url = settings.database_url
        reservation = None
        if args.cmd == "release" and args.reservation is not None:
            reservation = json.loads(args.reservation)
            if not isinstance(reservation, dict):
                raise ValueError("--reservation must be a JSON object")
    except (ConfigError, ValueError) as e:
        print(f"reconcile: config error: {e}", file=sys.stderr)
        return 2
    if args.cmd == "check":
        try:
            with psycopg.connect(url, connect_timeout=5) as conn:
                legacy = db.legacy_markers(conn)
        except Exception as e:
            print(f"reconcile: cannot read the database ({type(e).__name__})")
            return 1
        for nonce, record in legacy:
            print(f"legacy unresolved marker: nonce={nonce} record={record} (amount unknown)")
        print(f"reconcile: {len(legacy)} legacy unresolved marker(s)" + (": cap-sensitive writes are blocked" if legacy else ""))
        return 1 if legacy else 0
    from actionproof.server import build_app, load_server_settings
    try:
        gate = build_app(settings, load_server_settings(env, need_principal=False)).gate
        done = gate.release_quarantine(args.record, args.reviewer, executed=args.executed, reservation=reservation)
    except (ConfigError, ValueError) as e:
        print(f"reconcile: refused: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # the audit entry or the release failed: nothing was released
        print(f"reconcile: FAILED, nothing released ({type(e).__name__})")
        return 1
    print("reconcile: released" if done else "reconcile: nothing to release for that record")
    return 0


if __name__ == "__main__":
    sys.exit(main())
