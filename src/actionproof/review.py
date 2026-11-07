"""Human side of a REVIEW decision (deck slide 3 step 4; ADR-008, ADR-012). Called by the console backend with the
authenticated session subject as `reviewer_login`; it is NOT an MCP tool and no agent-facing path reaches it.

complete_review either mints a one-use token for the stored receipt (Gate.mint_review_token, which enforces
AP-SEP-12) and commits with it in the same call, or marks the review rejected with the reviewer's typed reason.
The pending row is locked (FOR UPDATE) for the whole call, so two reviewers cannot complete one review twice; the
gate's single-use receipt and token (G2) hold regardless. Every outcome is an audit entry: mint and commit are
audited by the gate, a rejection or a refused completion by this module (kind 'review').
"""
import time
from dataclasses import asdict, dataclass

from psycopg.types.json import Jsonb

from actionproof.gate import Principal, ReviewRefused
from actionproof.verify import Reason


def park(conn_factory, req, receipt: dict, reasons) -> tuple[str, list[dict]]:
    """Store one REVIEW (idempotent per request_hash). Returns (status, reasons) of the stored row: 'pending' for a
    new one; for a request parked earlier, its current status and that outcome's reasons. Raises on a DB failure
    (the caller must then DENY: no REVIEW is reported that a reviewer cannot find)."""
    h = receipt["payload"]["request_hash"]
    rules = [asdict(r) if isinstance(r, Reason) else dict(r) for r in reasons]
    with conn_factory() as conn:
        conn.execute(
            "INSERT INTO pending_reviews (request_hash, request, receipt, actor, on_behalf_of, created_at, reasons) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (request_hash) DO NOTHING",
            (h, Jsonb(req.model_dump(mode="json")), Jsonb(receipt), req.actor, req.on_behalf_of, int(time.time()),
             Jsonb(rules)))
        status, stored = conn.execute("SELECT status, reasons FROM pending_reviews WHERE request_hash = %s",
                                      (h,)).fetchone()
    return status, stored


@dataclass(frozen=True)
class ReviewOutcome:
    status: str  # the review's status after this call: pending | executed | denied | rejected | not_found
    reasons: list[Reason]


def complete_review(gate, conn_factory, request_hash: str, reviewer_login: str, approve: bool,
                    reason: str) -> ReviewOutcome:
    """`reviewer_login` MUST be the console's authenticated session subject, never a form or body field.
    `reason` is the reviewer's typed note (required). Raises ValueError on missing inputs; never returns a token."""
    if not isinstance(reviewer_login, str) or not reviewer_login.strip():
        raise ValueError("reviewer_login is required")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("a typed reason is required")
    if not isinstance(approve, bool):
        raise ValueError("approve must be a bool")
    note = reason.strip()[:500]
    with conn_factory() as conn:
        row = conn.execute("SELECT request, receipt, actor, on_behalf_of, status FROM pending_reviews "
                           "WHERE request_hash = %s FOR UPDATE", (request_hash,)).fetchone()
        detail = {"reviewer_login": reviewer_login, "reason": note, "approve": approve}
        if row is None:
            r = Reason("AP-REV-10", "G2", "no review is pending for this request")
            gate._audit(conn, "review", decision="DENY", rules=[asdict(r)], detail=detail)
            return ReviewOutcome("not_found", [r])
        request, receipt, actor, on_behalf_of, status = row
        who = {"request_hash": request_hash, "actor": actor, "on_behalf_of": on_behalf_of}
        if status != "pending":
            r = Reason("AP-REP-05", "G2", f"review already completed ({status})")
            gate._audit(conn, "review", decision="DENY", rules=[asdict(r)], detail=detail, **who)
            return ReviewOutcome(status, [r])

        if not approve:
            reasons = [Reason("AP-REV-10", "G2", f"rejected by reviewer: {note}")]
            final = "rejected"
        else:
            try:
                token = gate.mint_review_token(receipt, request, reviewer_login=reviewer_login)
            except ReviewRefused as e:  # audited by the gate; the review stays pending for another reviewer
                return ReviewOutcome("pending", [e.reason])
            # The submitter's Principal as the transport established it when the request was parked (ADR-012).
            c = gate.commit(receipt, request, token, principal=Principal(actor, on_behalf_of))
            final, reasons = ("executed", []) if c.outcome == "EXECUTED" else ("denied", c.reasons)
        rules = [asdict(r) for r in reasons]
        conn.execute("UPDATE pending_reviews SET status = %s, reasons = %s, reviewer = %s, decided_at = %s "
                     "WHERE request_hash = %s", (final, Jsonb(rules), reviewer_login, int(time.time()), request_hash))
        gate._audit(conn, "review", decision=final.upper(), rules=rules, detail=detail, **who)
        return ReviewOutcome(final, reasons)
