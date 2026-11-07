"""The gate: prepare (verify + authorize + sign) and commit (re-check + execute once). Deck slides 3-4.

Protocol, rule ids and order: .superpowers/sdd/phase3/design.md and docs/ARCHITECTURE.md.
- One gate, several connectors (ADR-009): the adapter is chosen by req.tool; TARGETS (here, not in the adapter)
  fixes the record each tool acts on and the record field that is the AP-CUM-03 counterparty (ADR-015). Every other
  step (verify, policy, receipt, commit lane, tokens, burn/quarantine, audit) is the same code for every tool.
- prepare never raises; any failure is DENY AP-ERR-11 / G1 (invariant 1). DENY never carries a receipt.
- commit runs ONE SERIALIZABLE transaction and calls tool.execute at most once, only after every check passed,
  and never on a DENY. A receipt or idempotency key is single-use (UNIQUE constraints, G2).
- The signing key lives only inside the Signer (ADR-007); reasons carry exception type names, never messages.
- Identity comes from the transport as a Principal and must equal the request's actor/on_behalf_of (ADR-012).
- commit re-derives the policy decision from fresh state under the commit lock (ADR-014); a commit that reached the
  tool and rolled back quarantines its record until Gate.release_quarantine (ADR-014).
- mint_review_token and release_quarantine are Gate methods for the human/admin side only: no tool-facing path
  (MCP, adapter) may expose them. The reviewer must be a different directory PERSON from the submitter
  (AP-SEP-12 / G2, ADR-008), checked at mint and again inside the commit tx.
- Every prepare, commit, mint and release_quarantine outcome is an audit.py chain entry. The commit EXECUTED entry
  is written inside the commit tx BEFORE the tool runs (it rolls back with the tx; if it fails the tool is never
  reached: DENY AP-ERR-11). DENY/refusal entries get their own short tx; an audit failure never changes a DENY.
  A prepare ALLOW/REVIEW whose entry cannot be written is DENY AP-ERR-11 (no unaudited receipt leaves the gate).
"""

import hashlib
import logging
import secrets
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal

import psycopg
import rfc8785
from psycopg import errors

from actionproof import audit, policy, signing
from actionproof.contracts import MONEY, ActionRequest, ContractError, parse_request, request_hash
from actionproof.verify import Reason, VerifyResult, verify_request

TOOL = "payments.approve_invoice"
REFUND_TOOL = "payments.refund_payment"  # second connector (ADR-009): same prepare/commit, no parallel path


@dataclass(frozen=True)
class Target:
    """What a tool acts on, fixed by the gate (not the adapter): the argument naming the record, the record kind
    (record_id = '<kind>:<value>'), the status the record must have, the record field holding the counterparty
    (the AP-CUM-03 key, ADR-015) and its word in reasons."""
    arg: str
    kind: str
    status: str
    counterparty: str
    word: str


TARGETS = {
    TOOL: Target("invoice_id", "invoice", "open", "vendor_id", "vendor"),
    REFUND_TOOL: Target("payment_id", "payment", "captured", "customer_id", "customer"),
}
# Mirrors cap_cents in policy/actionproof.rego (tests/test_commit.py asserts they agree).
# ponytail: one global cap; per-tenant caps belong in data.json + the delegations table.
CAP = Decimal("5000.00")
CENT = Decimal("0.01")
MAX_RETRIES = 3
LOCK_TIMEOUT = "5s"
PAYLOAD_KEYS = {"request_hash", "decision", "reasons", "diff_hash", "record_id", "version", "nonce", "exp",
                "tool", "actor", "on_behalf_of", "idempotency_key"}
# Only for "the audit write itself failed" (exception type name only); decisions go to the audit chain.
_log = logging.getLogger("actionproof.audit")


def _now() -> int:
    return int(time.time())


def _r(rule: str, guarantee: str, msg: str) -> Reason:
    return Reason(rule, guarantee, msg)


def _err(msg: str) -> Reason:
    return _r("AP-ERR-11", "G1", msg)


def _ver(msg: str) -> Reason:
    return _r("AP-VER-01", "G1", msg)


def _diff_hash(diff: dict, before: dict) -> str:
    """Binds the approved change AND the record state it applies to (any data change = AP-STALE-07)."""
    return hashlib.sha256(rfc8785.dumps({"diff": diff, "before": before})).hexdigest()


def _same_money(a, b) -> bool:
    return isinstance(a, str) and isinstance(b, str) and bool(MONEY.match(a) and MONEY.match(b)) and Decimal(a) == Decimal(b)


def _sor_variance(data: dict, sor: dict) -> str | None:
    """ADR-011/ADR-013: the only variance that counts is invoice.total - po.total from the system of record."""
    inv, po = data.get("total"), sor.get("po.total")
    if not (isinstance(inv, str) and isinstance(po, str) and MONEY.match(inv) and MONEY.match(po)):
        return None
    return str((Decimal(inv) - Decimal(po)).quantize(CENT))


def _sor_mismatches(req: ActionRequest, data: dict, sor: dict) -> list[Reason]:
    """A document the agent supplied only proves it says a value; money claims must also agree with the records."""
    out = []
    for name, want in (("amount", data.get("total")), ("invoice.total", data.get("total")),
                       ("po.total", sor.get("po.total")), ("variance", _sor_variance(data, sor))):
        c = req.args.get(name)
        if c is not None and not _same_money(c.value, want):
            out.append(_ver(f"{name}: disagrees with the system of record"))
    return out


def _refund_mismatches(req: ActionRequest, data: dict, refunded: Decimal) -> list[Reason]:
    """ADR-009, against the payment record itself: the customer and the destination must be the original
    payment's, and the amount must fit the refundable balance (payment amount - refunds already committed)."""
    out = []
    for name, key in (("customer_id", "customer_id"), ("refund_to", "method_id")):
        c = req.args.get(name)
        if c is None or not isinstance(data.get(key), str) or c.value != data[key]:
            out.append(_ver(f"{name}: disagrees with the system of record"))
    amount, paid = req.args.get("amount"), data.get("amount")
    if amount is None or not _money(amount.value) or not _money(paid):
        out.append(_ver("amount: not comparable with the payment record"))
    elif Decimal(amount.value) > Decimal(paid) - refunded:
        out.append(_ver("amount: exceeds the refundable balance of the payment"))
    return out


def _money(v) -> bool:
    return isinstance(v, str) and bool(MONEY.match(v))


def _refunded(conn, record_id: str, exclude_nonce: str | None = None) -> Decimal:
    """Refunds committed against one payment (burned ones included: unknown outcome = spent, ADR-010)."""
    return conn.execute("SELECT COALESCE(SUM(amount), 0) FROM commits WHERE record_id = %s "
                        "AND nonce IS DISTINCT FROM %s", (record_id, exclude_nonce)).fetchone()[0]


def _merge(d: policy.Decision, v_ok: bool, v_reasons: list[Reason]) -> list[Reason]:
    return list(d.reasons) + ([r for r in v_reasons if r not in d.reasons] if not v_ok else [])


@dataclass(frozen=True)
class Principal:
    """Who is calling, as established by the transport (MCP session / adapter), never by the request (ADR-012)."""
    actor: str
    on_behalf_of: str


def _bound(req: ActionRequest, principal) -> bool:
    return isinstance(principal, Principal) and req.actor == principal.actor and req.on_behalf_of == principal.on_behalf_of


def _sep(msg: str) -> Reason:
    return _r("AP-SEP-12", "G2", msg)


def _separation(conn, reviewer_login: str, actor: str, on_behalf_of: str) -> tuple[Reason | None, str | None]:
    """ADR-008 / AP-SEP-12: the reviewer login must hold 'reviewer' and resolve to a person who is neither the
    actor's person (an agent maps to its operator) nor the on_behalf_of person. A missing lookup or a team
    on_behalf_of fails closed. FOR SHARE: a concurrent directory edit waits for this tx (or aborts it, retried
    before the tool). Returns (deny reason, reviewer person_id)."""
    ids = (reviewer_login, actor, on_behalf_of)
    rows = {login: (person, roles) for login, person, roles in conn.execute(
        "SELECT login, person_id, roles FROM people WHERE login = ANY(%s) FOR SHARE", (list(ids),)).fetchall()}
    if not all(x in rows for x in ids):
        return _sep("identity not in the people directory (fail closed)"), None
    person, roles = rows[reviewer_login]
    if "reviewer" not in roles:
        return _sep("reviewer login lacks the reviewer role"), None
    # ponytail: a team on_behalf_of is DENY; upgrade path is a team_members expansion.
    if any("team" in rows[x][1] for x in (actor, on_behalf_of)):
        return _sep("submitter is a team, not a single person"), None
    if person in (rows[actor][0], rows[on_behalf_of][0]):
        return _sep("reviewer is the same person as the submitter (separation of duties)"), None
    return None, person


class ReviewRefused(Exception):
    """mint_review_token refused; `.reason` names the rule and guarantee (ADR-008)."""

    def __init__(self, reason: Reason):
        super().__init__(f"{reason.rule} [{reason.guarantee}] {reason.msg}")
        self.reason = reason


_UNBOUND = Reason("AP-SCOPE-02", "G1", "identity not bound to caller")
_QUARANTINED = Reason("AP-REP-05", "G2", "unknown outcome from a previous attempt; reconcile")
_NOT_VERIFIED = VerifyResult(False, {}, [])


# The card shows ONE rule line: the highest-priority reason (evidence failures before limits), then the first.
CARD_PRIORITY = ("AP-VER-01", "AP-SCOPE-02", "AP-SEP-12", "AP-REF-13", "AP-INV-04", "AP-CUM-03")


def _card_rank(r: Reason) -> int:
    return CARD_PRIORITY.index(r.rule) if r.rule in CARD_PRIORITY else len(CARD_PRIORITY)


@dataclass
class PrepareResult:
    decision: str
    reasons: list[Reason]
    verify: VerifyResult
    diff: dict | None
    receipt: dict | None
    request: ActionRequest | None = field(default=None, repr=False, compare=False)

    def card(self) -> str:
        """Deck slide 1 text shape."""
        lines = ["ACTION INTERCEPTED"]
        tool = self.request.tool if self.request is not None else "unknown"
        lines.append(f"action: {tool.rsplit('.', 1)[-1]}")
        for name in ("amount", "refund_to") if tool == REFUND_TOOL else ("amount", "variance"):
            c = self.request.args.get(name) if self.request is not None else None
            if c is None:
                lines.append(f"{name}: missing [FAILED]")
                continue
            if c.claim.value == "ASSERTED":
                status = "ASSERTED"
            else:
                res = self.verify.claims.get(name)
                status = f"{c.claim.value} {'ok' if res is not None and res.ok else 'FAILED'}"
            lines.append(f"{name}: {c.value} [{status}]")
        top = min(self.reasons, key=_card_rank) if self.reasons else None
        if top is None:
            lines.append("rule: none")
        elif top.rule == "AP-INV-04":
            lines.append("rule: AP-INV-04 (> 100)")
        elif top.rule == "AP-REF-13":
            lines.append("rule: AP-REF-13 (> 1000)")
        else:
            lines.append(f"rule: {top.rule} [{top.guarantee}]")
        lines.append(f"decision: {self.decision}")
        return "\n".join(lines)


@dataclass
class CommitResult:
    outcome: str  # "EXECUTED" | "DENY"
    reasons: list[Reason]
    tool_result: dict | None


def _deny(*reasons: Reason) -> CommitResult:
    return CommitResult("DENY", list(reasons), None)


def _rules(reasons) -> list[dict]:
    return [asdict(r) for r in reasons]


def _who(req, p: dict | None = None) -> dict:
    """Audit identity fields: from the gate-signed receipt payload when verified, else the request's own claim.
    Never raises (an unparseable request just contributes nothing)."""
    f = {}
    if isinstance(req, ActionRequest):
        try:
            t = TARGETS.get(req.tool)
            tgt = req.args.get(t.arg) if t is not None else None
            f = {"request_hash": request_hash(req), "actor": req.actor, "on_behalf_of": req.on_behalf_of,
                 "record_id": f"{t.kind}:{tgt.value}" if tgt is not None else None}
        except Exception:
            f = {}
    if p:
        f.update({k: p[k] for k in ("request_hash", "actor", "on_behalf_of", "record_id")})
    return f


class _Attempt:
    """Per-attempt state: whether the tool was reached, and the commits row to burn if it was."""

    def __init__(self):
        self.invoked = False
        self.row: tuple | None = None


class Gate:
    def __init__(self, settings, signer, conn_factory, tool, docs_provider=None):
        """`tool`: {tool name: adapter} for every connector this gate serves, or a single invoice adapter.
        The adapter is chosen by req.tool; a tool with no adapter or no TARGETS entry is DENY (fail closed)."""
        self._settings = settings
        self._signer = signer
        self._verify_key = signer.public_key_b64()
        self._conn_factory = conn_factory
        self._tools = dict(tool) if isinstance(tool, dict) else {TOOL: tool}
        self._docs_provider = docs_provider

    def __repr__(self) -> str:
        return f"Gate(kid={self._signer.kid!r}, tools={sorted(self._tools)!r})"

    __str__ = __repr__

    # ------------------------------------------------------------------ audit

    def _audit(self, conn, kind: str, **fields) -> None:
        """Append in the caller's tx, plus a signed checkpoint every AUDIT_CHECKPOINT_EVERY entries."""
        if audit.append(conn, kind, **fields) % self._settings.audit_checkpoint_every == 0:
            audit.checkpoint(conn, self._signer)

    def _audit_tx(self, kind: str, **fields) -> None:
        with self._conn_factory() as conn:
            self._audit(conn, kind, **fields)

    def _audit_deny(self, kind: str, **fields) -> None:
        """DENY / refusal entries: own short tx. The outcome is already a DENY, so a failed write changes nothing."""
        try:
            self._audit_tx(kind, **fields)
        except Exception as e:
            _log.error("audit write failed for a %s %s: %s", kind, fields.get("decision"), type(e).__name__)

    # ------------------------------------------------------------------ prepare

    def prepare(self, req, docs=None, *, principal) -> PrepareResult:
        """`principal` is the caller identity from the transport; required (no default = no fail-open)."""
        try:
            res = self._prepare(req, docs, principal)
        except Exception as e:  # fail closed (invariant 1)
            res = PrepareResult("DENY", [_err(f"prepare failed: {type(e).__name__}")], _NOT_VERIFIED, None, None,
                                req if isinstance(req, ActionRequest) else None)
        p = res.receipt["payload"] if res.receipt else None
        entry = {"decision": res.decision, "rules": _rules(res.reasons), "detail": {"nonce": p and p["nonce"]},
                 **_who(res.request, p)}
        if res.decision == "DENY":
            self._audit_deny("prepare", **entry)
            return res
        try:
            self._audit_tx("prepare", **entry)
        except Exception as e:  # no unaudited receipt leaves the gate
            res = PrepareResult("DENY", [_err(f"audit write failed: {type(e).__name__}")], res.verify, None, None,
                                res.request)
            self._audit_deny("prepare", decision="DENY", rules=_rules(res.reasons), **_who(res.request))
        return res

    def _prepare(self, req, docs, principal) -> PrepareResult:
        if not isinstance(req, ActionRequest):
            try:
                req = parse_request(req)
            except ContractError:
                return PrepareResult("DENY", [_ver("request failed the strict contract")], _NOT_VERIFIED, None, None)

        def deny(*reasons: Reason, v: VerifyResult = _NOT_VERIFIED) -> PrepareResult:
            return PrepareResult("DENY", list(reasons), v, None, None, req)

        if not _bound(req, principal):  # ADR-012: the agent cannot name its own actor or principal
            return deny(_UNBOUND)
        t, tool = TARGETS.get(req.tool), self._tools.get(req.tool)
        if t is None or tool is None:
            return deny(_ver(f"unknown tool {req.tool!r} (fail closed)"))
        tgt = req.args.get(t.arg)
        if tgt is None:
            return deny(_ver(f"{t.arg}: required to target a record (evidence gap)"))
        record_id = f"{t.kind}:{tgt.value}"
        try:
            sor = dict(tool.sor_for(tgt.value))
        except KeyError:
            return deny(_ver(f"{t.arg}: target record not in the system of record"))
        if docs is None:
            docs = self._docs_provider(req) if self._docs_provider is not None else {}
        v = verify_request(req, docs, sor)

        data, version = tool.read_record(record_id)
        # The system of record, not the documents, decides what is owed (G1); variance is pinned to it (ADR-013).
        if req.tool == TOOL:
            extra = _sor_mismatches(req, data, sor)
            if extra:
                v = VerifyResult(False, v.claims, v.reasons + extra)
        if data.get("status") != t.status:
            return deny(_r("AP-STALE-07", "G2", f"target record is not {t.status} (already actioned)"), v=v)

        with self._conn_factory() as conn:
            if conn.execute("SELECT 1 FROM quarantine WHERE record_id = %s", (record_id,)).fetchone():
                return deny(_QUARANTINED, v=v)
            if req.tool == REFUND_TOOL:  # advisory here; authoritative again inside the commit tx (ADR-009)
                extra = _refund_mismatches(req, data, _refunded(conn, record_id))
                if extra:
                    v = VerifyResult(False, v.claims, v.reasons + extra)
            counterparty = data.get(t.counterparty)  # the record's, never the request's (ADR-009/015)
            committed = conn.execute(
                "SELECT COALESCE(SUM(amount), 0)::numeric(18,2)::text FROM commits WHERE actor = %s AND vendor_id = %s",
                (req.actor, counterparty)).fetchone()[0]
            payload = self._policy_input(conn, req, v.ok, v.reasons, counterparty, committed)
        d = policy.decide(payload, self._settings.opa_url, self._settings.opa_timeout_seconds)
        reasons = _merge(d, v.ok, v.reasons)
        if d.outcome not in ("ALLOW", "REVIEW"):
            return deny(*reasons, v=v)

        diff = tool.dry_run(req)
        receipt = self._signer.sign({
            "request_hash": request_hash(req),
            "decision": d.outcome,
            "reasons": [asdict(r) for r in reasons],
            "diff_hash": _diff_hash(diff, data),
            "record_id": record_id,
            "version": version,
            "nonce": secrets.token_urlsafe(16),
            "exp": _now() + self._settings.receipt_ttl_seconds,
            "tool": req.tool,
            "actor": req.actor,
            "on_behalf_of": req.on_behalf_of,
            "idempotency_key": req.idempotency_key,
        })
        return PrepareResult(d.outcome, reasons, v, diff, receipt, req)

    @staticmethod
    def _policy_input(conn, req: ActionRequest, v_ok: bool, v_reasons: list[Reason], counterparty,
                      committed: str) -> dict:
        """Policy input from the system of record (scope from delegations, counterparty from the record), never the
        agent. Invoices: args.vendor_id + scope.vendors; refunds: args.customer_id + scope.customers (ADR-009)."""
        scope = conn.execute("SELECT max_amount::text, vendors, customers FROM delegations WHERE on_behalf_of = %s",
                             (req.on_behalf_of,)).fetchone()
        refund = req.tool == REFUND_TOOL
        args = {name: req.args[name].value for name in (("amount",) if refund else ("amount", "variance"))
                if name in req.args}
        args["customer_id" if refund else "vendor_id"] = counterparty
        ids = "customers" if refund else "vendors"
        return {
            "tool": req.tool,
            "actor": req.actor,
            "on_behalf_of": req.on_behalf_of,
            "verify": {"ok": v_ok, "reasons": [asdict(r) for r in v_reasons]},
            "args": args,
            # No delegation = empty scope, so the policy denies AP-SCOPE-02 (never a default grant).
            "scope": {"max_amount": scope[0], ids: list(scope[2 if refund else 1])} if scope
            else {"max_amount": "0.00", ids: []},
            "cumulative": {"committed": committed},
        }

    # ------------------------------------------------------------------ quarantine

    def release_quarantine(self, record_id: str, reviewer: str) -> bool:
        """Reconcile path (admin, not tool-facing): a human checked the tool's real outcome for a record whose
        commit was burned and lifts the block. Returns whether a row was released. Raises on bad input.
        The release and its audit entry (who, what) commit together; if the entry cannot be written, nothing is
        released and the error propagates."""
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("record_id is required")
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("reviewer is required")
        with self._conn_factory() as conn:
            released = conn.execute("DELETE FROM quarantine WHERE record_id = %s RETURNING record_id",
                                    (record_id,)).fetchone() is not None
            self._audit(conn, "release_quarantine", record_id=record_id,
                        decision="RELEASED" if released else "NOT_QUARANTINED", detail={"reviewer": reviewer})
            return released

    # ------------------------------------------------------------------ review tokens

    def mint_review_token(self, receipt, req, *, reviewer_login: str) -> str:
        """A one-use human approval for one REVIEW receipt (AP-REV-10), refused unless the reviewer is a different
        person from the submitter (AP-SEP-12 / G2, ADR-008). Raises ReviewRefused (audited) on any refusal.

        `reviewer_login` MUST be the authenticated server-side console session subject, never a request body, form
        or query field. The submitter is read from the gate-signed receipt's request, never passed in."""
        login = reviewer_login if isinstance(reviewer_login, str) else None
        p = None

        def refuse(reason: Reason):  # every refusal is an audit entry (own tx); the token never is
            self._audit_deny("mint", decision="REFUSED", rules=_rules([reason]), detail={"reviewer_login": login},
                             **_who(req, p))
            raise ReviewRefused(reason)

        if not login:
            refuse(_sep("reviewer login is required"))
        reason, p, req = self._open(receipt, req)
        if reason:
            refuse(reason)
        if p["decision"] != "REVIEW":
            refuse(_r("AP-REV-10", "G2", "receipt does not call for a human review"))
        # ponytail: token stored as-is; store sha256(token) and compare digests once tokens leave the demo.
        token = secrets.token_urlsafe(32)
        now = _now()
        sep = None
        try:
            with self._conn_factory() as conn:
                sep, person = _separation(conn, login, req.actor, req.on_behalf_of)
                if not sep:
                    conn.execute(
                        "INSERT INTO review_tokens (token, request_hash, submitter, minted_by, minted_by_person, "
                        "minted_at, exp) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (token, p["request_hash"], req.actor, login, person, now,
                         now + self._settings.review_token_ttl_seconds))
                    # Same tx as the token row: no token exists without its audit entry.
                    self._audit(conn, "mint", decision="MINTED", detail={"reviewer_login": login,
                                                                         "reviewer_person": person}, **_who(None, p))
        except Exception as e:
            refuse(_err(f"mint failed: {type(e).__name__}"))
        if sep:
            refuse(sep)
        return token

    def _open(self, receipt, req):
        """Signature, shape, expiry and request hash of a receipt. Returns (deny reason, payload, strict request)."""
        if not signing.verify(receipt, self._verify_key):
            return _r("AP-SIG-09", "G2", "receipt signature invalid"), None, None
        p = receipt["payload"]
        if set(p) != PAYLOAD_KEYS:
            return _r("AP-SIG-09", "G2", "receipt payload malformed"), None, None
        if not isinstance(p["exp"], int) or _now() >= p["exp"]:
            return _r("AP-EXP-06", "G2", "receipt expired"), None, None
        # Always re-validate, even an ActionRequest instance: model_construct/model_copy skip validation, and the
        # hash and the tool must see the same strictly-typed data.
        try:
            req = parse_request(req.model_dump(mode="json") if isinstance(req, ActionRequest) else req)
        except Exception:
            return _r("AP-HASH-08", "G2", "request does not match the receipt"), None, None
        if request_hash(req) != p["request_hash"]:
            return _r("AP-HASH-08", "G2", "request changed after prepare"), None, None
        return None, p, req

    # ------------------------------------------------------------------ commit

    def commit(self, receipt, req, review_token=None, *, principal) -> CommitResult:
        """`principal` is the caller identity from the transport; required (no default = no fail-open)."""
        opened: dict = {}
        try:
            res = self._commit(receipt, req, review_token, principal, opened)
        except Exception as e:  # fail closed (invariant 1)
            res = _deny(_err(f"commit failed: {type(e).__name__}"))
        if res.outcome != "EXECUTED":  # EXECUTED was audited inside the commit tx
            p = opened.get("p")
            self._audit_deny("commit", decision="DENY", rules=_rules(res.reasons),
                             detail={"nonce": p and p["nonce"]}, **_who(req, p))
        return res

    def _commit(self, receipt, req, review_token, principal, opened: dict) -> CommitResult:
        reason, p, req = self._open(receipt, req)
        if reason:
            return _deny(reason)
        opened["p"] = p  # signature verified: the audit entry may trust these fields
        if not _bound(req, principal):
            return _deny(_UNBOUND)
        if p["decision"] not in ("ALLOW", "REVIEW"):
            return _deny(_err("receipt decision is not executable"))
        if p["decision"] == "REVIEW" and not isinstance(review_token, str):
            return _deny(_r("AP-REV-10", "G2", "REVIEW decision needs a human review token"))
        if "amount" not in req.args or not MONEY.match(req.args["amount"].value):
            return _deny(_err("request has no 2dp amount"))
        if req.tool not in TARGETS or req.tool not in self._tools:
            return _deny(_err(f"no adapter for tool {req.tool!r} (fail closed)"))

        conn = self._conn_factory()
        try:
            conn.isolation_level = psycopg.IsolationLevel.SERIALIZABLE
            for _ in range(MAX_RETRIES + 1):
                st = _Attempt()
                try:
                    return self._attempt(conn, p, req, review_token, st)
                except (errors.SerializationFailure, errors.DeadlockDetected):
                    conn.rollback()
                    if st.invoked:  # never call the tool twice for one receipt
                        return _deny(_err("serialization failure after the tool was called"), *self._burn(conn, st))
                except Exception as e:
                    conn.rollback()
                    burned = self._burn(conn, st) if st.invoked else []
                    return _deny(_err(f"commit failed: {type(e).__name__}"), *burned)
            return _deny(_err(f"serialization failure after {MAX_RETRIES} retries"))
        finally:
            conn.close()

    def _attempt(self, conn, p: dict, req: ActionRequest, review_token, st: _Attempt) -> CommitResult:
        def deny(*reasons: Reason) -> CommitResult:
            conn.rollback()
            return _deny(*reasons)

        conn.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
        # Serializes gate commits BEFORE the snapshot is taken (LOCK is not a snapshot-taking statement), so the
        # cumulative re-check sees every earlier commit and SSI never aborts a commit after the tool ran.
        # ponytail: one global commit lane; upgrade path is a per (actor, vendor) lock row taken first.
        conn.execute("LOCK TABLE commits IN SHARE ROW EXCLUSIVE MODE")
        # The audit lock too, before the snapshot, so the head this tx appends after is current (audit.py).
        audit.lock(conn)
        now = _now()
        if now >= p["exp"]:  # the receipt may have expired while waiting for the lane
            return deny(_r("AP-EXP-06", "G2", "receipt expired"))
        if conn.execute("SELECT 1 FROM quarantine WHERE record_id = %s", (p["record_id"],)).fetchone():
            return deny(_QUARANTINED)

        reviewer = None
        if p["decision"] == "REVIEW":
            row = conn.execute(
                "UPDATE review_tokens SET used_at = %s, used_nonce = %s "
                "WHERE token = %s AND request_hash = %s AND used_at IS NULL AND exp > %s RETURNING minted_by",
                (now, p["nonce"], review_token, p["request_hash"], now)).fetchone()
            if row is None:
                return deny(self._token_reason(conn, review_token, p["request_hash"], now))
            # ADR-008: re-read the directory now, so an edit after the mint, or a token minted outside the console,
            # cannot approve. A violation rolls back, so the token stays unused.
            sep, _ = _separation(conn, row[0], req.actor, req.on_behalf_of)
            if sep:
                return deny(sep)
            reviewer = row[0]

        rec = conn.execute("SELECT data, version FROM records WHERE record_id = %s FOR UPDATE",
                           (p["record_id"],)).fetchone()
        if rec is None:
            return deny(_r("AP-STALE-07", "G2", "record no longer exists"))
        data, version = rec
        t, tool = TARGETS[req.tool], self._tools[req.tool]
        amount = Decimal(req.args["amount"].value)
        # The counterparty (AP-CUM-03 key) comes from the locked record, never the request (ADR-009/015).
        st.row = (p["nonce"], p["idempotency_key"], p["request_hash"], req.actor, req.on_behalf_of,
                  str(data.get(t.counterparty)), amount, p["record_id"], now)
        try:
            conn.execute(
                "INSERT INTO commits (nonce, idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount, "
                "record_id, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", st.row)
        except errors.UniqueViolation:
            return deny(_r("AP-REP-05", "G2", "nonce or idempotency key already used"))

        total = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM commits WHERE actor = %s AND vendor_id = %s",
                             (req.actor, st.row[5])).fetchone()[0]
        if total > CAP:
            return deny(_r("AP-CUM-03", "G1", f"actor+{t.word} cumulative total exceeds 5000.00"))
        if version != p["version"]:
            return deny(_r("AP-STALE-07", "G2", "record version changed since prepare"))
        diff = tool.dry_run(req)
        if _diff_hash(diff, data) != p["diff_hash"]:
            return deny(_r("AP-STALE-07", "G2", "dry-run diff changed since prepare"))
        stale = self._recheck_policy(conn, p, req, data, str((total - amount).quantize(CENT)))
        if stale:
            return deny(*stale)

        # Audited BEFORE the tool, in this tx: if the entry cannot be written the tool is never reached (the raise
        # rolls back, DENY AP-ERR-11); if anything after it fails, the entry rolls back with the commit.
        self._audit(conn, "commit", decision="EXECUTED", **_who(None, p), detail={
            "nonce": p["nonce"], "idempotency_key": p["idempotency_key"], "amount": req.args["amount"].value,
            "version": version, "reviewer": reviewer})
        st.invoked = True
        try:
            result = tool.execute(req, version, p["idempotency_key"], conn)
        except Exception as e:
            after = conn.execute("SELECT data, version FROM records WHERE record_id = %s", (p["record_id"],)).fetchone()
            conn.rollback()
            burned = self._burn(conn, st)
            # Classification only (the outcome is DENY + rollback either way): the version moved but the approved
            # effect is absent -> someone else wrote mid-flight (STALE); otherwise the tool itself failed.
            target = str(diff.get("status", "")).partition("->")[2]
            applied = after is not None and after[1] == version + 1 and after[0].get("status") == target
            if (after is None or after[1] != version) and not applied:
                return _deny(_r("AP-STALE-07", "G2", "record changed while the tool ran"), *burned)
            return _deny(_err(f"tool error: {type(e).__name__}"), *burned)
        after = conn.execute("SELECT version FROM records WHERE record_id = %s", (p["record_id"],)).fetchone()
        if after is None or after[0] not in (version, version + 1):
            conn.rollback()
            return _deny(_r("AP-STALE-07", "G2", "record changed beyond the approved diff"), *self._burn(conn, st))
        # The receipt's version is consumed even if a tool forgot to bump it.
        conn.execute("UPDATE records SET version = %s WHERE record_id = %s", (version + 1, p["record_id"]))
        conn.commit()
        return CommitResult("EXECUTED", [], result)

    @staticmethod
    def _token_reason(conn, token: str, req_hash: str, now: int) -> Reason:
        row = conn.execute("SELECT request_hash, used_at, exp FROM review_tokens WHERE token = %s", (token,)).fetchone()
        if row is None or row[0] != req_hash:
            return _r("AP-REV-10", "G2", "review token not valid for this request")
        if row[1] is not None:
            return _r("AP-REP-05", "G2", "review token already used")
        if row[2] <= now:
            return _r("AP-EXP-06", "G2", "review token expired")
        return _r("AP-REV-10", "G2", "review token not valid for this request")

    def _recheck_policy(self, conn, p: dict, req: ActionRequest, data: dict, committed: str) -> list[Reason]:
        """ADR-014: the receipt froze a decision; the world may have moved. Re-derive the policy input from CURRENT
        state (delegation scope, PO total, committed sum) under the commit lock and decide again. Returns the deny
        reasons, or [] when the fresh decision is no stricter than the receipt's.
        Refunds (ADR-009): customer, destination and refundable balance are re-checked against the LOCKED payment
        record and every refund committed on it before this one (the commit lane serializes them)."""
        t = TARGETS[req.tool]
        if req.tool == REFUND_TOOL:
            vr = _refund_mismatches(req, data, _refunded(conn, p["record_id"], p["nonce"]))
        else:
            sor = dict(self._tools[req.tool].sor_for(req.args[t.arg].value))
            vr = _sor_mismatches(req, data, sor)
            if "variance" not in req.args:
                vr.append(_ver("variance: required argument missing (evidence gap)"))
        payload = self._policy_input(conn, req, not vr, vr, data.get(t.counterparty), committed)
        d = policy.decide(payload, self._settings.opa_url, self._settings.opa_timeout_seconds)
        if d.outcome == "ALLOW" or (d.outcome == "REVIEW" and p["decision"] == "REVIEW"):
            return []
        if d.outcome == "REVIEW":  # receipt said ALLOW; fresh state needs a human
            return [_r("AP-STALE-07", "G2", "policy outcome changed since prepare (now REVIEW)")]
        return _merge(d, not vr, vr) or [_err("fresh policy decision was not executable")]

    @staticmethod
    def _burn(conn, st: _Attempt) -> list[Reason]:
        """The tool was reached but the tx rolled back: the outcome is unknown, so the nonce and idempotency key
        are spent (a retry is AP-REP-05), the amount counts toward the cap (ADR-010), and the record is quarantined
        so no new receipt can apply it again until a human reconciles (ADR-014). Each write is attempted on its own
        so one failing does not skip the other. Returns reasons for the DENY when a write failed."""
        writes = (
            ("burn", "INSERT INTO commits (nonce, idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount, "
                     "record_id, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", st.row),
            ("quarantine", "INSERT INTO quarantine (record_id, nonce, created_at) VALUES (%s, %s, %s) "
                           "ON CONFLICT DO NOTHING", (st.row[7], st.row[0], st.row[8])),
        )
        failed = []
        for name, sql, params in writes:
            try:
                conn.execute(sql, params)
                conn.commit()
            except Exception:
                failed.append(name)
                try:
                    conn.rollback()
                except Exception:
                    pass
        # ponytail: if both fail, a retry is stopped only by the tool-side idempotency key (documented in ADR-014).
        return [_err(f"unknown outcome not recorded ({', '.join(failed)} failed)")] if failed else []
