"""Execution outbox worker (ADR-035): resolve UNKNOWN executions on signed adapter evidence, never by redispatch.

    python -m actionproof.reconcile auto --once | --run [--min-age S] [--interval S]

One cycle: (1) enqueue: every journaled execution whose DISPATCH_STARTED is older than `min_age` gets one
execution_outbox row, PENDING if it reads UNKNOWN, else DONE (nothing to do); (2) claim due rows with
FOR UPDATE SKIP LOCKED under a lease, in a short committed tx; (3) per row, with NO database transaction open, ask
the adapter `lookup(idempotency_key)` (read-only). Only evidence.lookup_outcome CONFIRMED (signed APPLIED) or
DEFINITE_FAILURE (signed NOT_APPLIED after the provider's window closed) resolves, and only while the lease is still
ours, through Gate.release_quarantine(evidence=...): the existing audited RECONCILIATION_* path with its existing
accounting (ADR-010/022/029). Anything else returns the row to PENDING with capped exponential backoff.

G2: the worker never calls `execute` (TLA+ NoRedispatch), writes no commits/tool_reached/quarantine row itself, and
cannot resolve an execution twice: release_quarantine refuses evidence once the execution is no longer unresolved on
its record, and every outbox write after the claim is fenced by the lease owner. A crashed worker's row is taken
over when its lease expires. A row that keeps failing is never dropped: `journal verify` reports it as stuck.
No exactly-once claim: a provider that signs a false statement, or offers no lookup, is the residual (THREAT_MODEL).
"""
import time

from psycopg.types.json import Jsonb

from actionproof import evidence, journal

LEASE = 30            # seconds a claim is held; a worker that dies loses its rows after this
BACKOFF_BASE = 5      # seconds; doubles per attempt
BACKOFF_CAP = 300
STUCK_ATTEMPTS = 10   # surfaced by `journal verify` from this many attempts on
_COLS = ("execution_id", "nonce", "record_id", "tool", "attempts")


def enqueue(conn, now: int, min_age: int) -> int:
    """Insert the outbox row of every dispatched execution that has none (in `conn`'s tx, committed). Returns how
    many PENDING rows this call created. A dispatch younger than `min_age` is left to the gate still running it."""
    rows = conn.execute(
        "SELECT d.execution_id, d.nonce, d.record_id, COALESCE(d.detail->>'tool', '') FROM execution_journal d "
        "WHERE d.event = 'DISPATCH_STARTED' AND d.ts <= %s AND NOT EXISTS "
        "(SELECT 1 FROM execution_outbox o WHERE o.execution_id = d.execution_id) ORDER BY d.seq",
        (now - min_age,)).fetchall()
    status = journal.of_nonces(conn, [r[1] for r in rows])
    n = 0
    for xid, nonce, record_id, tool in rows:
        st = status[nonce]["status"]
        pending = st == "UNKNOWN"
        cur = conn.execute(
            "INSERT INTO execution_outbox (execution_id, nonce, record_id, tool, state, next_attempt_at, last_result, "
            "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (xid, nonce, record_id, tool, "PENDING" if pending else "DONE", now, None if pending else st, now, now))
        n += pending and cur.rowcount == 1
    conn.commit()
    return n


def claim(conn, owner: str, now: int, lease: int = LEASE, limit: int = 10) -> list[dict]:
    """Lease up to `limit` due rows (PENDING and due, or IN_FLIGHT with an expired lease) to `owner`. Committed
    before it returns, so no lock or transaction is held while the caller does its lookups."""
    rows = conn.execute(
        "UPDATE execution_outbox o SET state = 'IN_FLIGHT', lease_owner = %s, lease_expires_at = %s, "
        "attempts = o.attempts + 1, updated_at = %s WHERE o.execution_id IN (SELECT execution_id FROM execution_outbox "
        "WHERE (state = 'PENDING' AND next_attempt_at <= %s) OR (state = 'IN_FLIGHT' AND lease_expires_at <= %s) "
        "ORDER BY next_attempt_at, execution_id LIMIT %s FOR UPDATE SKIP LOCKED) "
        f"RETURNING {', '.join('o.' + c for c in _COLS)}", (owner, now + lease, now, now, now, limit)).fetchall()
    conn.commit()
    return [dict(zip(_COLS, r)) for r in rows]


def _retry(factory, row: dict, owner: str, now: int, result: str) -> bool:
    delay = min(BACKOFF_CAP, BACKOFF_BASE * 2 ** min(max(row["attempts"] - 1, 0), 30))
    with factory() as conn:
        return conn.execute(
            "UPDATE execution_outbox SET state = 'PENDING', lease_owner = NULL, lease_expires_at = NULL, "
            "next_attempt_at = %s, last_result = %s, updated_at = %s "
            "WHERE execution_id = %s AND state = 'IN_FLIGHT' AND lease_owner = %s RETURNING 1",
            (now + delay, result, now, row["execution_id"], owner)).fetchone() is not None


def _done(factory, row: dict, now: int, result: str, env) -> None:
    with factory() as conn:
        conn.execute(
            "UPDATE execution_outbox SET state = 'DONE', lease_owner = NULL, lease_expires_at = NULL, last_result = %s, "
            "last_evidence = %s, updated_at = %s WHERE execution_id = %s AND state <> 'DONE'",
            (result, Jsonb(env) if env else None, now, row["execution_id"]))


def _execution(factory, nonce: str) -> dict | None:
    with factory() as conn:
        return journal.of_nonces(conn, [nonce]).get(nonce)


def process(factory, adapters, release, keys, row: dict, owner: str, now: int, lease: int = LEASE) -> str:
    """Look up one claimed row and resolve it if, and only if, the adapter signed conclusive evidence. Returns
    CONFIRMED | DEFINITE_FAILURE | AMBIGUOUS | LEASE_LOST | ALREADY_RESOLVED | REFUSED."""
    x = _execution(factory, row["nonce"])
    if x is None or x["status"] != "UNKNOWN":  # resolved meanwhile (human, another worker), or RECONCILING
        _done(factory, row, now, x["status"] if x else "NOT_JOURNALED", None)
        return "ALREADY_RESOLVED"
    lookup = getattr(adapters.get(row["tool"]), "lookup", None)
    try:
        env = lookup(x["idempotency_key"]) if callable(lookup) else None  # no DB transaction is open here
    except Exception:  # provider down, timeout, garbage: no evidence
        env = None
    outcome, p = evidence.lookup_outcome(env, x, keys, now)
    if outcome == evidence.AMBIGUOUS:
        return evidence.AMBIGUOUS if _retry(factory, row, owner, now, outcome) else "LEASE_LOST"
    with factory() as conn:  # fence: resolve only while the lease is still ours
        if conn.execute(
                "UPDATE execution_outbox SET lease_expires_at = %s, updated_at = %s WHERE execution_id = %s "
                "AND state = 'IN_FLIGHT' AND lease_owner = %s AND lease_expires_at > %s RETURNING 1",
                (now + lease, now, row["execution_id"], owner, now)).fetchone() is None:
            return "LEASE_LOST"
    ev = {"source": f"adapter.lookup:{env['kid']}:{p['response_digest']}", "idempotency_key": x["idempotency_key"],
          "status": p["status"], "amount": x["amount"], "counterparty": x["vendor_id"]}
    try:
        release(x["record_id"], f"outbox:{owner}", evidence=ev)
    except ValueError:  # refused: no longer exactly this one unresolved execution on its record
        again = _execution(factory, row["nonce"])
        if again is not None and again["status"] != "UNKNOWN":
            _done(factory, row, now, again["status"], None)
            return "ALREADY_RESOLVED"
        _retry(factory, row, owner, now, "REFUSED")
        return "REFUSED"
    _done(factory, row, now, outcome, env)
    return outcome


_COUNT = {evidence.CONFIRMED: "resolved", evidence.DEFINITE_FAILURE: "resolved", evidence.AMBIGUOUS: "ambiguous",
          "LEASE_LOST": "lost", "ALREADY_RESOLVED": "already", "REFUSED": "refused"}


def run_once(factory, adapters, release, keys, owner: str, now: int | None = None, min_age: int = 60,
             lease: int = LEASE, limit: int = 10) -> dict:
    """One enqueue + claim + process cycle. `adapters`: {tool: adapter}; `release`: Gate.release_quarantine;
    `keys`: the adapter evidence KeyRegistry. A row whose processing raises keeps its lease and is retried after it."""
    now = int(time.time()) if now is None else now
    out = {"enqueued": 0, "claimed": 0, "resolved": 0, "ambiguous": 0, "lost": 0, "already": 0, "refused": 0,
           "errors": 0}
    with factory() as conn:
        out["enqueued"] = enqueue(conn, now, min_age)
        rows = claim(conn, owner, now, lease, limit)
    out["claimed"] = len(rows)
    for row in rows:
        try:
            out[_COUNT[process(factory, adapters, release, keys, row, owner, now, lease)]] += 1
        except Exception:
            out["errors"] += 1
    return out


def health(conn) -> dict:
    """Counts for `journal verify` and the console: rows not DONE, and the stuck ones (never silently dropped)."""
    r = conn.execute("SELECT count(*) FILTER (WHERE state = 'PENDING'), count(*) FILTER (WHERE state = 'IN_FLIGHT'), "
                     "count(*) FILTER (WHERE state <> 'DONE' AND attempts >= %s) FROM execution_outbox",
                     (STUCK_ATTEMPTS,)).fetchone()
    return {"pending": r[0], "in_flight": r[1], "stuck": r[2]}
