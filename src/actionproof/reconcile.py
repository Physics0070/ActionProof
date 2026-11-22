"""Operator CLI for unresolved executions (ADR-019/022/024/029).

  python -m actionproof.reconcile check
      the explicit migration validation: lists legacy unresolved markers (unknown amount), exit 1 if any, else 0.
  python -m actionproof.reconcile release --record R --reviewer LOGIN [--executed --reservation JSON]
      the audited reconciliation (Gate.release_quarantine). --executed on a legacy marker REQUIRES --reservation,
      a JSON object {idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount}: the facts the old
      marker never recorded. Without --executed the human attests the execution did not happen.
  python -m actionproof.reconcile journal verify
      the execution journal's hash chain (ADR-029); exit 1 if it does not verify.
  python -m actionproof.reconcile journal list [--all]
      journaled executions still UNKNOWN or RECONCILING (all with --all). Nothing ever resolves by elapsed time.
  python -m actionproof.reconcile journal resolve --execution ID --reviewer LOGIN (--executed | --not-executed | --evidence JSON)
      resolve one journaled execution through Gate.release_quarantine: a human decision, or downstream evidence
      {source, idempotency_key, status: APPLIED|NOT_APPLIED, amount, counterparty} that must match the execution.
      Markers from before the journal have no events: reconcile them with `release` (they are not backfilled).
Same environment as the API (DATABASE_URL, OPA_URL, SIGNING_KEY_PATH, DOCS_DIR, ...). Exit 2 = bad input/config.
"""
import argparse
import json
import os
import sys

import psycopg

from actionproof import db, journal
from actionproof.config import ConfigError, load_settings


def _journal_read(url: str, cmd: str, show_all: bool) -> int:
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            conn.read_only = True
            if cmd == "verify":
                print(f"journal: OK ({journal.verify(conn)} events)")
                return 0
            xs = [x for x in journal.executions(conn) if show_all or x["status"] in journal.UNRESOLVED]
    except journal.JournalFailure as f:
        print(f"journal: FAILED at seq {f.seq}: {f.reason}")
        return 1
    except Exception as e:  # not verified = failed
        print(f"journal: FAILED, cannot read the journal ({type(e).__name__})")
        return 1
    for x in xs:
        print(f"{x['execution_id']} {x['status']} nonce={x['nonce']} record={x['record_id']} amount={x['amount']} "
              f"idempotency_key={x['idempotency_key']} counterparty={x['vendor_id']} actor={x['actor']}")
    print(f"journal: {len(xs)} " + ("execution(s)" if show_all else "unresolved execution(s)"))
    return 0


def main(argv=None, env=os.environ) -> int:
    ap = argparse.ArgumentParser(prog="python -m actionproof.reconcile")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="list legacy unresolved markers (exit 1 if any)")
    r = sub.add_parser("release", help="audited reconciliation of an unresolved execution")
    r.add_argument("--record", required=True)
    r.add_argument("--reviewer", required=True)
    r.add_argument("--executed", action="store_true", help="the human confirms the execution DID happen")
    r.add_argument("--reservation", help="JSON {idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount}")
    j = sub.add_parser("journal", help="execution journal (ADR-029)").add_subparsers(dest="jcmd", required=True)
    j.add_parser("verify", help="verify the journal hash chain")
    jl = j.add_parser("list", help="unresolved journaled executions")
    jl.add_argument("--all", action="store_true")
    jr = j.add_parser("resolve", help="resolve one journaled execution (human decision or evidence)")
    jr.add_argument("--execution", required=True)
    jr.add_argument("--reviewer", required=True)
    how = jr.add_mutually_exclusive_group(required=True)
    how.add_argument("--executed", action="store_true", dest="did")
    how.add_argument("--not-executed", action="store_true", dest="did_not")
    how.add_argument("--evidence", help="JSON {source, idempotency_key, status, amount, counterparty}")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        settings = load_settings(env)
        url = settings.database_url
        reservation = evidence = None
        if args.cmd == "release" and args.reservation is not None:
            reservation = json.loads(args.reservation)
            if not isinstance(reservation, dict):
                raise ValueError("--reservation must be a JSON object")
        if args.cmd == "journal" and args.jcmd == "resolve" and args.evidence is not None:
            evidence = json.loads(args.evidence)
            if not isinstance(evidence, dict):
                raise ValueError("--evidence must be a JSON object")
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
    if args.cmd == "journal" and args.jcmd in ("verify", "list"):
        return _journal_read(url, args.jcmd, getattr(args, "all", False))
    from actionproof.server import build_app, load_server_settings
    try:
        gate = build_app(settings, load_server_settings(env, need_principal=False)).gate
        if args.cmd == "release":
            done = gate.release_quarantine(args.record, args.reviewer, executed=args.executed, reservation=reservation)
        else:
            with psycopg.connect(url, connect_timeout=5) as conn:
                x = next((x for x in journal.executions(conn) if x["execution_id"] == args.execution), None)
            if x is None:
                raise ValueError("no journaled execution with that id")
            if evidence is not None:
                done = gate.release_quarantine(x["record_id"], args.reviewer, evidence=evidence)
            else:
                done = gate.release_quarantine(x["record_id"], args.reviewer, executed=args.did)
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
