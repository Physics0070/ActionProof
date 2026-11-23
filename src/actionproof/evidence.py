"""Adapter outcome evidence (ADR-035): what an adapter may claim about an execution, and when the gate believes it.

An adapter result is one of:
- CONFIRMED: `execute` returned (the gate journals EXECUTION_CONFIRMED), or a lookup says APPLIED;
- DEFINITE_FAILURE: the provider rejected the call and states that no effect happened;
- AMBIGUOUS: a timeout, a transport error, anything else. Anything unrecognised is AMBIGUOUS (fail closed).

A failure or a lookup is believed only as a SIGNED statement (signing.Signer envelope over RFC 8785) whose kid is
trusted (active or retired) in the gate's adapter KeyRegistry (`ADAPTER_EVIDENCE_KEYS`, the policy-authority file
format; unset = no adapter is trusted, so every failure claim is AMBIGUOUS) and which names THIS execution: same
idempotency key, exact amount and counterparty, and carries the provider response digest. A lookup NOT_APPLIED is a
definite failure only once the provider's window has closed: the statement was made at or after
`window_closes_at` and the worker's clock is past it; before that the provider could still apply the request.
Never raises: a malformed claim is simply not evidence.
"""
import hashlib
import re
import time
from decimal import Decimal

from actionproof import journal, signing
from actionproof.contracts import MONEY

KIND = "actionproof.adapter-evidence.v1"
FIELDS = ("kind", "op", "idempotency_key", "status", "amount", "counterparty", "reason", "provider_ref",
          "response_digest", "ts", "window_closes_at")
_INTS = ("ts", "window_closes_at")
STATUSES = ("APPLIED", "NOT_APPLIED", "UNKNOWN")
CONFIRMED, DEFINITE_FAILURE, AMBIGUOUS = "CONFIRMED", "DEFINITE_FAILURE", "AMBIGUOUS"
CLOCK_SKEW = 300  # seconds a statement may be ahead of the worker's clock
_HEX64 = re.compile(r"^[0-9a-f]{64}\Z")
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{1,63}\Z")


def load_keys(path) -> signing.KeyRegistry:
    """ADAPTER_EVIDENCE_KEYS: the strict policy-authority format (public keys + status only). Raises ValueError."""
    from actionproof.policy import PolicyAuthorityError, load_authority_keys

    try:
        return load_authority_keys(path)
    except PolicyAuthorityError:
        raise ValueError("adapter evidence keys file is unreadable or malformed") from None


def statement(op: str, idempotency_key: str, status: str, amount: str, counterparty: str, response: bytes, *,
              reason: str = "", provider_ref: str = "", window_closes_at: int = 0, ts: int | None = None) -> dict:
    """The payload an adapter signs. `op`: "execute" (a rejection at dispatch) or "lookup" (status by key)."""
    return {"kind": KIND, "op": op, "idempotency_key": idempotency_key, "status": status, "amount": amount,
            "counterparty": counterparty, "reason": reason, "provider_ref": provider_ref,
            "response_digest": hashlib.sha256(response).hexdigest(),
            "ts": int(time.time()) if ts is None else ts, "window_closes_at": window_closes_at}


def verified(env, execution: dict, keys, op: str) -> dict | None:
    """The payload of `env` if it is a trusted adapter statement of kind `op` about `execution` (a journal reference:
    idempotency_key, amount, vendor_id), else None."""
    try:
        if not isinstance(keys, signing.KeyRegistry) or not keys.verify(env):
            return None
        p = env["payload"]
        if set(p) != set(FIELDS) or p["kind"] != KIND or p["op"] != op or p["status"] not in STATUSES:
            return None
        if any(type(p[k]) is not int or p[k] < 0 for k in _INTS) \
                or not all(isinstance(p[k], str) for k in FIELDS if k not in _INTS):
            return None
        if not _HEX64.match(p["response_digest"]) or not MONEY.match(p["amount"]):
            return None
        if p["idempotency_key"] != execution["idempotency_key"] or p["counterparty"] != execution["vendor_id"] \
                or Decimal(p["amount"]) != Decimal(execution["amount"]):
            return None
        if p["status"] == "NOT_APPLIED" and not _REASON.match(p["reason"]):
            return None
        if p["status"] == "APPLIED" and not p["provider_ref"].strip():
            return None
        return p
    except Exception:
        return None


def dispatch_failure(exc: Exception, execution: dict, keys) -> tuple[str, dict]:
    """The journal outcome event and detail for an exception from `execute`. EXECUTION_FAILED only for a
    journal.DefiniteFailure carrying a verified "execute" NOT_APPLIED statement; the detail then records its kid,
    response digest and reason code. Everything else is EXECUTION_UNKNOWN."""
    why = {"error": type(exc).__name__}
    if not isinstance(exc, journal.DefiniteFailure):
        return "EXECUTION_UNKNOWN", why
    p = verified(exc.evidence, execution, keys, "execute")
    if p is None or p["status"] != "NOT_APPLIED":
        return "EXECUTION_UNKNOWN", {**why, "evidence": "unverified"}
    return "EXECUTION_FAILED", {**why, "evidence": {"kid": exc.evidence["kid"], "digest": p["response_digest"],
                                                    "reason": p["reason"]}}


def lookup_outcome(env, execution: dict, keys, now: int) -> tuple[str, dict | None]:
    """(CONFIRMED | DEFINITE_FAILURE | AMBIGUOUS, verified payload or None) for an adapter lookup answer."""
    p = verified(env, execution, keys, "lookup")
    if p is None or p["ts"] > now + CLOCK_SKEW:
        return AMBIGUOUS, None
    if p["status"] == "APPLIED":
        return CONFIRMED, p
    if p["status"] == "NOT_APPLIED" and 0 < p["window_closes_at"] <= p["ts"] and p["window_closes_at"] <= now:
        return DEFINITE_FAILURE, p
    return AMBIGUOUS, p
