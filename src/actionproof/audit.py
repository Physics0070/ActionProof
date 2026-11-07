"""Audit chain (deck slide 3 step 5, S9.3): an append-only, hash-chained log with gate-signed checkpoints, and a
verifier CLI that needs only the database and the PUBLIC key.

    python -m actionproof.audit verify [--public-key <base64>]      (else env AUDIT_PUBLIC_KEY_PATH)

- `append` sets entry_hash = sha256(RFC 8785 of every field but entry_hash, prev_hash included) and assigns
  seq = head + 1 under the audit lock, so the chain is gap-free under concurrency.
- The audit lock is `LOCK TABLE audit_log IN EXCLUSIVE MODE`, not pg_advisory_xact_lock: the gate's commit tx is
  SERIALIZABLE and must hold the lock BEFORE its snapshot (a SELECT pg_advisory_xact_lock() takes the snapshot
  first, so the head it then reads could be stale). LOCK is not snapshot-taking; readers (the verifier) still pass.
- `checkpoint` signs {seq, head_hash, ts} with the gate Signer; the key never leaves signing.py (ADR-007).
- Entries never hold secrets: no key material, review tokens, receipt signatures or exception text.
"""
import argparse
import base64
import hashlib
import os
import sys
import time
from pathlib import Path

import psycopg
import rfc8785
from psycopg.types.json import Jsonb

from actionproof import signing

GENESIS = "0" * 64
# Hashed columns, in table order. entry_hash covers all of them.
FIELDS = ("seq", "ts", "kind", "request_hash", "actor", "on_behalf_of", "record_id", "decision", "rules", "detail",
          "prev_hash")
_OPTIONAL = ("request_hash", "actor", "on_behalf_of", "record_id", "decision")
_HEAD = "SELECT seq, entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"


class AuditFailure(Exception):
    def __init__(self, seq: int, reason: str):
        super().__init__(f"seq {seq}: {reason}")
        self.seq, self.reason = seq, reason


def entry_hash(entry: dict) -> str:
    return hashlib.sha256(rfc8785.dumps({k: entry[k] for k in FIELDS})).hexdigest()


def lock(conn) -> None:
    """Serializes appenders. The commit tx calls it before its first snapshot-taking statement."""
    conn.execute("LOCK TABLE audit_log IN EXCLUSIVE MODE")


def append(conn, kind: str, **fields) -> int:
    """Append one entry in the caller's transaction (it commits or rolls back with it). Returns its seq."""
    rules, detail = list(fields.pop("rules", [])), dict(fields.pop("detail", {}))
    if set(fields) - set(_OPTIONAL):
        raise TypeError(f"unknown audit fields: {sorted(set(fields) - set(_OPTIONAL))}")
    lock(conn)
    head = conn.execute(_HEAD).fetchone()
    e = {f: fields.get(f) for f in _OPTIONAL}
    e.update(seq=head[0] + 1 if head else 1, ts=int(time.time()), kind=kind, rules=rules, detail=detail,
             prev_hash=head[1] if head else GENESIS)
    e["entry_hash"] = entry_hash(e)
    cols = FIELDS + ("entry_hash",)
    conn.execute(f"INSERT INTO audit_log ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                 [Jsonb(e[c]) if c in ("rules", "detail") else e[c] for c in cols])
    return e["seq"]


def checkpoint(conn, signer) -> int:
    """Sign the current head in the caller's transaction. Returns the checkpointed seq."""
    lock(conn)
    seq, head = conn.execute(_HEAD).fetchone()
    signed = signer.sign({"seq": seq, "head_hash": head, "ts": int(time.time())})
    conn.execute("INSERT INTO audit_checkpoints (seq, head_hash, ts, sig, kid) VALUES (%s, %s, %s, %s, %s)",
                 (seq, head, signed["payload"]["ts"], signed["sig"], signed["kid"]))
    return seq


def verify(conn, public_key_b64: str) -> tuple[int, int]:
    """(entries, checkpoints) if the chain and every checkpoint check out, else raises AuditFailure.
    # ponytail: holds every entry hash in memory; upgrade path is a server-side cursor merged with checkpoints."""
    prev, n, heads = GENESIS, 0, {}
    for row in conn.execute(f"SELECT {', '.join(FIELDS)}, entry_hash FROM audit_log ORDER BY seq"):
        e = dict(zip(FIELDS + ("entry_hash",), row))
        n += 1
        if e["seq"] != n:
            raise AuditFailure(n, f"entry missing or out of order (found seq {e['seq']})")
        if e["prev_hash"] != prev:
            raise AuditFailure(n, "prev_hash does not link to the previous entry")
        if entry_hash(e) != e["entry_hash"]:
            raise AuditFailure(n, "entry_hash does not recompute (entry edited)")
        prev = heads[n] = e["entry_hash"]
    m = 0
    for seq, head, ts, sig, kid in conn.execute(
            "SELECT seq, head_hash, ts, sig, kid FROM audit_checkpoints ORDER BY seq"):
        m += 1
        if seq not in heads:
            raise AuditFailure(seq, "checkpoint refers to a missing entry (log truncated)")
        if heads[seq] != head:
            raise AuditFailure(seq, "checkpoint head_hash does not match the entry")
        if not signing.verify({"payload": {"seq": seq, "head_hash": head, "ts": ts}, "sig": sig, "kid": kid},
                              public_key_b64):
            raise AuditFailure(seq, "checkpoint signature invalid")
    return n, m


def run_verify(database_url: str, public_key_b64: str) -> tuple[int, str]:
    """(exit code, output line). Read-only, one consistent snapshot of both tables. Fails closed."""
    try:
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            conn.read_only = True
            n, m = verify(conn, public_key_b64)
    except AuditFailure as f:
        return 1, f"audit: FAILED at seq {f.seq}: {f.reason}"
    except Exception as e:  # unreachable DB, missing tables, ...: not verified = failed
        return 1, f"audit: FAILED at seq 0: cannot read the audit log ({type(e).__name__})"
    return 0, f"audit: OK ({n} entries, {m} checkpoints)"


def _public_key(arg: str | None, env) -> str:
    """The base64 Ed25519 PUBLIC key (Signer.public_key_b64()). Never the private key file: raw bytes are not base64."""
    if arg is None:
        path = env.get("AUDIT_PUBLIC_KEY_PATH", "").strip()
        if not path:
            raise ValueError("set --public-key or AUDIT_PUBLIC_KEY_PATH")
        try:
            arg = Path(path).read_bytes().decode("ascii").strip()
        except (OSError, UnicodeDecodeError):
            raise ValueError("AUDIT_PUBLIC_KEY_PATH is not a readable base64 public key") from None
    try:
        if len(base64.b64decode(arg, validate=True)) != 32:
            raise ValueError
    except ValueError:
        raise ValueError("public key is not base64 of 32 bytes") from None
    return arg


def main(argv=None, env=os.environ) -> int:
    ap = argparse.ArgumentParser(prog="python -m actionproof.audit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="verify the hash chain and the signed checkpoints")
    v.add_argument("--public-key", help="base64 Ed25519 public key (default: file at AUDIT_PUBLIC_KEY_PATH)")
    args = ap.parse_args(argv)
    try:
        pub = _public_key(args.public_key, env)
        url = env.get("DATABASE_URL", "").strip()
        if not url:
            raise ValueError("DATABASE_URL is not set")
    except ValueError as e:
        print(f"audit: config error: {e}", file=sys.stderr)
        return 2
    code, line = run_verify(url, pub)
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
