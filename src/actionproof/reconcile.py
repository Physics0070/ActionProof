"""Operator CLI for unresolved executions (ADR-019/022/024/029).

  python -m actionproof.reconcile check
      the explicit migration validation: lists legacy unresolved markers (unknown amount), exit 1 if any, else 0.
  python -m actionproof.reconcile release --record R --reviewer LOGIN [--executed --reservation JSON]
      the audited reconciliation (Gate.release_quarantine). --executed on a legacy marker REQUIRES --reservation,
      a JSON object {idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount}: the facts the old
      marker never recorded. Without --executed the human attests the execution did not happen.
  python -m actionproof.reconcile journal verify [--anchor FILE] [--strict]
      the execution journal's hash chain (ADR-029) and its signed checkpoints (ADR-034); exit 1 if it does not verify.
      --anchor (default env JOURNAL_ANCHOR_PATH): the journal stream's LocalAnchor file; the journal must reach and
      match it. --strict: also fail on an unanchored tail (or no anchor). Keys: KEY_REGISTRY_PATH, else the gate's own.
  python -m actionproof.reconcile journal checkpoint [--anchor FILE]
      verify the chain, then sign its head with the gate's checkpoint signer (idempotent), and append that checkpoint
      to the anchor file if given. The journal anchor is never the audit anchor (AUDIT_ANCHOR_PATH): exit 2.
  python -m actionproof.reconcile journal list [--all]
      journaled executions still UNKNOWN or RECONCILING (all with --all). Nothing ever resolves by elapsed time.
  python -m actionproof.reconcile journal resolve --execution ID --reviewer LOGIN (--executed | --not-executed | --evidence JSON)
      resolve one journaled execution through Gate.release_quarantine: a human decision, or downstream evidence
      {source, idempotency_key, status: APPLIED|NOT_APPLIED, amount, counterparty} that must match the execution.
      Markers from before the journal have no events: reconcile them with `release` (they are not backfilled).
  python -m actionproof.reconcile auto (--once | --run) [--min-age S] [--interval S]
      the outbox worker (ADR-035, outbox.py): resolves UNKNOWN executions only on a SIGNED adapter lookup
      (ADAPTER_EVIDENCE_KEYS; unset = exit 2), never redispatches. --min-age (default 60): leave younger dispatches
      to the gate running them. --run repeats every --interval seconds (default 10) until interrupted.
Same environment as the API (DATABASE_URL, OPA_URL, SIGNING_KEY_PATH, DOCS_DIR, ...). Exit 2 = bad input/config.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

from actionproof import db, journal, outbox
from actionproof.config import ConfigError, load_settings


def _registry(settings):
    """Trusted checkpoint keys: KEY_REGISTRY_PATH, else the gate's own signer (as server.build_app). ValueError."""
    from actionproof.signing import KeyRegistry, Signer

    if settings.key_registry_path:
        return KeyRegistry.from_json(settings.key_registry_path)
    return KeyRegistry.for_signer(Signer.from_path(settings.signing_key_path, settings.signing_kid))


def _journal_anchor(arg, env, strict: bool):
    """The journal stream's anchor file: its own file, never the audit anchor (two streams, never mixed)."""
    path = arg or env.get("JOURNAL_ANCHOR_PATH", "").strip() or None
    if strict and not path:
        raise ValueError("--strict needs --anchor or JOURNAL_ANCHOR_PATH")
    other = env.get("AUDIT_ANCHOR_PATH", "").strip()
    if path and other and Path(path).resolve() == Path(other).resolve():
        raise ValueError("the journal anchor must be a different file from AUDIT_ANCHOR_PATH")
    return path


def _journal_checkpoint(url: str, signer, keys, path) -> int:
    from actionproof import anchor as anchor_mod

    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            journal.verify(conn, keys)                 # never sign the head of a chain that does not verify
            seq = journal.checkpoint(conn, signer)
            cp = journal.latest_checkpoint(conn)
    except journal.JournalFailure as f:
        print(f"journal: FAILED at seq {f.seq}: {f.reason}")
        return 1
    except Exception as e:  # unreachable DB, missing table, ...: nothing signed
        print(f"journal: checkpoint FAILED ({type(e).__name__})")
        return 1
    if seq is None:
        print("journal: nothing to checkpoint (no events)")
        return 0
    try:  # committed and closed: the anchor is written outside any database transaction
        done = anchor_mod.LocalAnchor(path).publish(cp, keys) if path else None
    except Exception as e:
        print(f"journal: checkpointed seq {seq}; anchor FAILED ({type(e).__name__}"
              + (f": {e}" if isinstance(e, anchor_mod.AnchorError) else "") + ")")
        return 1
    print(f"journal: checkpointed seq {seq}" + ("" if done is None else "; anchored" if done else "; already anchored"))
    return 0


def _journal_read(url: str, cmd: str, show_all: bool, keys=None, path=None, strict=False) -> int:
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            conn.read_only = True
            if cmd == "verify":
                n = journal.verify(conn, keys)
                m = conn.execute("SELECT count(*) FROM execution_journal_checkpoints").fetchone()[0]
                extra = journal.anchor_report(conn, path, keys, n, strict) if path else None
                h = outbox.health(conn)  # ADR-035: a stuck outbox row is surfaced here, never silently dropped
                print(f"journal: OK ({n} events, {m} checkpoints)" + (f"; {extra}" if extra else "")
                      + f"; outbox: {h['pending']} pending, {h['in_flight']} in flight, {h['stuck']} stuck")
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


def _auto(settings, env, args, build_app, load_server_settings) -> int:
    """The outbox worker loop. The gate (adapters, release_quarantine, adapter trust) is the API's own wiring."""
    import secrets
    import socket
    import time

    if args.min_age < 0 or args.interval < 1:
        print("reconcile: config error: --min-age must be >= 0 and --interval >= 1", file=sys.stderr)
        return 2
    try:
        gate = build_app(settings, load_server_settings(env, need_principal=False)).gate
    except (ConfigError, ValueError) as e:
        print(f"reconcile: config error: {e}", file=sys.stderr)
        return 2
    if gate._adapter_keys is None:  # fail closed: without trusted adapter keys no lookup could ever resolve
        print("reconcile: config error: auto needs ADAPTER_EVIDENCE_KEYS (trusted adapter keys)", file=sys.stderr)
        return 2
    owner = f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}"
    while True:
        try:
            out = outbox.run_once(gate._conn_factory, gate._tools, gate.release_quarantine, gate._adapter_keys,
                                  owner, min_age=args.min_age)
        except Exception as e:  # unreachable DB, ...: nothing resolved this cycle
            print(f"reconcile: auto cycle FAILED ({type(e).__name__})")
            if args.once:
                return 1
        else:
            print("reconcile: auto " + ", ".join(f"{v} {k}" for k, v in out.items()))
        if args.once:
            return 0
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
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
    jv = j.add_parser("verify", help="verify the journal hash chain and its signed checkpoints")
    jv.add_argument("--anchor", help="journal anchor file (default: env JOURNAL_ANCHOR_PATH)")
    jv.add_argument("--strict", action="store_true", help="also fail if the newest events are not anchored yet")
    jc = j.add_parser("checkpoint", help="sign the journal head (idempotent), optionally append it to the anchor")
    jc.add_argument("--anchor", help="journal anchor file (default: env JOURNAL_ANCHOR_PATH)")
    jl = j.add_parser("list", help="unresolved journaled executions")
    jl.add_argument("--all", action="store_true")
    jr = j.add_parser("resolve", help="resolve one journaled execution (human decision or evidence)")
    jr.add_argument("--execution", required=True)
    jr.add_argument("--reviewer", required=True)
    how = jr.add_mutually_exclusive_group(required=True)
    how.add_argument("--executed", action="store_true", dest="did")
    how.add_argument("--not-executed", action="store_true", dest="did_not")
    how.add_argument("--evidence", help="JSON {source, idempotency_key, status, amount, counterparty}")
    au = sub.add_parser("auto", help="outbox worker: resolve UNKNOWN executions by signed adapter lookup")
    once = au.add_mutually_exclusive_group(required=True)
    once.add_argument("--once", action="store_true")
    once.add_argument("--run", action="store_true")
    au.add_argument("--min-age", type=int, default=60)
    au.add_argument("--interval", type=int, default=10)
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
        if args.cmd == "journal" and args.jcmd in ("verify", "checkpoint"):
            keys = _registry(settings)
            path = _journal_anchor(args.anchor, env, getattr(args, "strict", False))
            if args.jcmd == "checkpoint":
                from actionproof.signing import Signer
                signer = Signer.from_path(settings.signing_key_path, settings.signing_kid)
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
    if args.cmd == "journal" and args.jcmd == "checkpoint":
        return _journal_checkpoint(url, signer, keys, path)
    if args.cmd == "journal" and args.jcmd == "verify":
        return _journal_read(url, "verify", False, keys, path, args.strict)
    if args.cmd == "journal" and args.jcmd == "list":
        return _journal_read(url, "list", args.all)
    from actionproof.server import build_app, load_server_settings
    if args.cmd == "auto":
        return _auto(settings, env, args, build_app, load_server_settings)
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
