"""Execution journal (ADR-029): an append-only, hash-chained record of every execution the gate dispatches.

Events (exact names): RESERVATION_CREATED, DISPATCH_STARTED, EXECUTION_CONFIRMED, EXECUTION_FAILED, EXECUTION_UNKNOWN,
RECONCILIATION_STARTED, RECONCILIATION_COMPLETED. Every event carries the execution's full reference: execution_id,
receipt nonce, request_hash, request idempotency_key, record_id, principal (actor, on_behalf_of), counterparty
(vendor_id) and the exact amount (numeric(18,2); a 2dp decimal string in the hash, never a float).

- execution_id = "ex-" + sha256("actionproof.execution:" + nonce)[:32]: one per receipt (a receipt dispatches at most
  once), stable across processes, recomputed by `verify`.
- Its own chain: entry_hash = sha256(RFC 8785 of every column but entry_hash, prev_hash included); seq = head + 1 under
  a journal-only advisory lock. Same approach as audit.py, separate table, separate lock.
- Lock order: the journal is written ONLY on its own short connections and never takes the audit lock, so a tx that
  holds the audit lock (commit, release_quarantine) may write it; nothing holding the journal lock ever waits for
  the audit lock. Order: audit (optional) -> journal. Never journal -> audit.
- Status of an execution = its latest event: DISPATCH_STARTED with no outcome (a crash) reads as UNKNOWN. Elapsed time
  never changes a status; only a journaled reconciliation does.
- No exactly-once claim for arbitrary downstreams: the journal makes an ambiguous outcome visible and keeps the gate
  from redispatching it; resolving it takes trustworthy evidence or an audited human decision.

    python -m actionproof.reconcile journal verify|list|resolve ...
"""
import hashlib
import time
from decimal import Decimal, InvalidOperation

import rfc8785
from psycopg.types.json import Jsonb

from actionproof.contracts import MONEY

EVENTS = ("RESERVATION_CREATED", "DISPATCH_STARTED", "EXECUTION_CONFIRMED", "EXECUTION_FAILED", "EXECUTION_UNKNOWN",
          "RECONCILIATION_STARTED", "RECONCILIATION_COMPLETED")
GENESIS = "0" * 64
REF = ("nonce", "request_hash", "idempotency_key", "record_id", "actor", "on_behalf_of", "vendor_id", "amount")
FIELDS = ("seq", "ts", "execution_id", "event") + REF + ("detail", "prev_hash")
_LOCK = 0x4A524E4C  # journal-only advisory lock key ("JRNL"); the audit lock is a table lock, never this
_HEAD = "SELECT seq, entry_hash FROM execution_journal ORDER BY seq DESC LIMIT 1"
_STATUS = {"RESERVATION_CREATED": "UNKNOWN", "DISPATCH_STARTED": "UNKNOWN", "EXECUTION_CONFIRMED": "CONFIRMED",
           "EXECUTION_FAILED": "FAILED", "EXECUTION_UNKNOWN": "UNKNOWN", "RECONCILIATION_STARTED": "RECONCILING"}
UNRESOLVED = ("UNKNOWN", "RECONCILING")
EVIDENCE_KEYS = ("source", "idempotency_key", "status", "amount", "counterparty")


class DefiniteFailure(Exception):
    """Raised by an adapter ONLY when the downstream definitively reports the effect was NOT applied (e.g. a decline
    with no state change). Any other exception from a tool is an UNKNOWN outcome."""


class JournalFailure(Exception):
    def __init__(self, seq: int, reason: str):
        super().__init__(f"seq {seq}: {reason}")
        self.seq, self.reason = seq, reason


def execution_id(nonce: str) -> str:
    return "ex-" + hashlib.sha256(f"actionproof.execution:{nonce}".encode()).hexdigest()[:32]


def _money(v) -> str:
    """The exact 2dp string of an amount: Decimal or 2dp string only (invariant 4)."""
    if isinstance(v, Decimal):
        v = str(v)
    if not isinstance(v, str):
        raise TypeError("journal amounts are Decimal or 2dp strings, never float/int")
    if not MONEY.match(v):
        raise ValueError("journal amount is not a 2dp decimal string")
    return v


def _no_float(v) -> None:
    if isinstance(v, float):
        raise TypeError("floats are not allowed in the journal")
    for x in v.values() if isinstance(v, dict) else v if isinstance(v, (list, tuple)) else ():
        _no_float(x)


def ref(row) -> dict:
    """The reference of an execution from the gate's reservation row (the tool_reached / commits column order)."""
    return {"nonce": row[0], "idempotency_key": row[1], "request_hash": row[2], "actor": row[3], "on_behalf_of": row[4],
            "vendor_id": row[5], "amount": _money(row[6]), "record_id": row[7]}


def entry_hash(e: dict) -> str:
    return hashlib.sha256(rfc8785.dumps({k: e[k] for k in FIELDS})).hexdigest()


def append(conn, event: str, reference: dict, detail: dict | None = None) -> tuple[int, str]:
    """Append one event in the caller's tx, on a connection that holds NO audit lock. Returns (seq, entry_hash)."""
    if event not in EVENTS:
        raise ValueError(f"unknown journal event {event!r}")
    detail = dict(detail or {})
    _no_float(detail)
    e = {k: reference[k] for k in REF}
    e["amount"] = _money(e["amount"])
    if not all(isinstance(e[k], str) and e[k] for k in REF):
        raise ValueError("journal reference fields must be non-empty strings")
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
    head = conn.execute(_HEAD).fetchone()
    e.update(seq=head[0] + 1 if head else 1, ts=int(time.time()), execution_id=execution_id(e["nonce"]), event=event,
             detail=detail, prev_hash=head[1] if head else GENESIS)
    e["entry_hash"] = entry_hash(e)
    cols = FIELDS + ("entry_hash",)
    conn.execute(f"INSERT INTO execution_journal ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                 [Jsonb(e[c]) if c == "detail" else e[c] for c in cols])
    return e["seq"], e["entry_hash"]


def record(factory, event: str, reference: dict, detail: dict | None = None) -> tuple[int, str]:
    """Append on a NEW connection and commit it (durable before this returns)."""
    conn = factory()  # explicit commit/close, like the gate's marker connection (works for any connection wrapper)
    try:
        out = append(conn, event, reference, detail)
        conn.commit()
        return out
    finally:
        conn.close()


def verify(conn) -> int:
    """Number of events if the chain checks out, else raises JournalFailure."""
    prev, n = GENESIS, 0
    for row in conn.execute(f"SELECT {', '.join(FIELDS)}, entry_hash FROM execution_journal ORDER BY seq"):
        e = dict(zip(FIELDS + ("entry_hash",), row))
        n += 1
        if e["seq"] != n:
            raise JournalFailure(n, f"event missing or out of order (found seq {e['seq']})")
        if e["prev_hash"] != prev:
            raise JournalFailure(n, "prev_hash does not link to the previous event")
        e["amount"] = str(e["amount"])
        if entry_hash(e) != e["entry_hash"]:
            raise JournalFailure(n, "entry_hash does not recompute (event edited)")
        if e["execution_id"] != execution_id(e["nonce"]):
            raise JournalFailure(n, "execution_id does not derive from the nonce")
        prev = e["entry_hash"]
    return n


def executions(conn, nonces=None) -> list[dict]:
    """Every journaled execution (or those of `nonces`) with its status (from its latest event), oldest first."""
    rows = conn.execute(
        "SELECT DISTINCT ON (execution_id) execution_id, event, detail, seq, entry_hash, "
        f"{', '.join(REF)} FROM execution_journal " + ("WHERE nonce = ANY(%s) " if nonces is not None else "")
        + "ORDER BY execution_id, seq DESC", (list(nonces),) if nonces is not None else ()).fetchall()
    out = []
    for xid, event, detail, seq, h, *r in sorted(rows, key=lambda x: x[3]):
        x = dict(zip(REF, r), execution_id=xid, last_event=event, seq=seq, entry_hash=h)
        x["amount"] = str(x["amount"])
        x["status"] = f"RESOLVED_{detail['resolution']}" if event == "RECONCILIATION_COMPLETED" else _STATUS[event]
        out.append(x)
    return out


def of_nonces(conn, nonces) -> dict:
    """{nonce: execution} for the journaled ones among `nonces` (a legacy marker has no journal: not backfilled)."""
    return {x["nonce"]: x for x in executions(conn, nonces)} if nonces else {}


def evidence_executed(evidence, execution: dict) -> bool:
    """Downstream evidence (the adapter's lookup-by-idempotency-key result) -> did the execution happen? Trusted only
    when it names this exact execution: same idempotency key, same exact amount, same counterparty. Raises ValueError.
    # ponytail: the evidence's authenticity is the operator's (the CLI caller's) responsibility; upgrade path is a
    signed lookup response from the adapter, verified here."""
    if not isinstance(evidence, dict) or set(evidence) != set(EVIDENCE_KEYS) \
            or not all(isinstance(evidence[k], str) and evidence[k].strip() for k in EVIDENCE_KEYS):
        raise ValueError(f"evidence needs exactly {', '.join(EVIDENCE_KEYS)} as non-empty strings")
    if evidence["status"] not in ("APPLIED", "NOT_APPLIED"):
        raise ValueError("evidence status must be APPLIED or NOT_APPLIED")
    if not MONEY.match(evidence["amount"]):
        raise ValueError("evidence amount is not a 2dp decimal string")
    try:
        same_amount = Decimal(evidence["amount"]) == Decimal(execution["amount"])
    except InvalidOperation:
        same_amount = False
    if evidence["idempotency_key"] != execution["idempotency_key"] or not same_amount \
            or evidence["counterparty"] != execution["vendor_id"]:
        raise ValueError("evidence does not match the execution (idempotency key, amount or counterparty)")
    return evidence["status"] == "APPLIED"
