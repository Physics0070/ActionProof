"""The gate: prepare (verify + authorize + sign) and commit (re-check + execute once). Deck slides 3-4.

Protocol, rule ids and order: .superpowers/sdd/phase3/design.md and docs/ARCHITECTURE.md.
- prepare never raises; any failure is DENY AP-ERR-11 / G1 (invariant 1). DENY never carries a receipt.
- commit runs ONE SERIALIZABLE transaction and calls tool.execute at most once, only after every check passed,
  and never on a DENY. A receipt or idempotency key is single-use (UNIQUE constraints, G2).
- The signing key lives only inside the Signer (ADR-007); reasons carry exception type names, never messages.
"""

import hashlib
import re
import secrets
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal

import psycopg
import rfc8785
from psycopg import errors

from actionproof import policy, signing
from actionproof.contracts import MONEY, ActionRequest, ContractError, parse_request, request_hash
from actionproof.verify import Reason, VerifyResult, verify_request

TOOL = "payments.approve_invoice"
# Mirrors cap_cents in policy/actionproof.rego (tests/test_commit.py asserts they agree).
# ponytail: one global cap; per-tenant caps belong in data.json + the delegations table.
CAP = Decimal("5000.00")
MAX_RETRIES = 3
LOCK_TIMEOUT = "5s"
PAYLOAD_KEYS = {"request_hash", "decision", "reasons", "diff_hash", "record_id", "version", "nonce", "exp",
                "tool", "actor", "on_behalf_of", "idempotency_key"}
_HASH = re.compile(r"^[0-9a-f]{64}$")


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


_NOT_VERIFIED = VerifyResult(False, {}, [])


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
        for name in ("amount", "variance"):
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
        if not self.reasons:
            lines.append("rule: none")
        elif self.reasons[0].rule == "AP-INV-04":
            lines.append("rule: AP-INV-04 (> 100)")
        else:
            lines.append(f"rule: {self.reasons[0].rule} [{self.reasons[0].guarantee}]")
        lines.append(f"decision: {self.decision}")
        return "\n".join(lines)


@dataclass
class CommitResult:
    outcome: str  # "EXECUTED" | "DENY"
    reasons: list[Reason]
    tool_result: dict | None


def _deny(*reasons: Reason) -> CommitResult:
    return CommitResult("DENY", list(reasons), None)


class _Attempt:
    """Per-attempt state: whether the tool was reached, and the commits row to burn if it was."""

    def __init__(self):
        self.invoked = False
        self.row: tuple | None = None


class Gate:
    def __init__(self, settings, signer, conn_factory, tool, docs_provider=None):
        self._settings = settings
        self._signer = signer
        self._verify_key = signer.public_key_b64()
        self._conn_factory = conn_factory
        self._tool = tool
        self._docs_provider = docs_provider

    def __repr__(self) -> str:
        return f"Gate(kid={self._signer.kid!r}, tool={TOOL!r})"

    __str__ = __repr__

    # ------------------------------------------------------------------ prepare

    def prepare(self, req, docs=None) -> PrepareResult:
        try:
            return self._prepare(req, docs)
        except Exception as e:  # fail closed (invariant 1)
            return PrepareResult("DENY", [_err(f"prepare failed: {type(e).__name__}")], _NOT_VERIFIED, None, None,
                                 req if isinstance(req, ActionRequest) else None)

    def _prepare(self, req, docs) -> PrepareResult:
        if not isinstance(req, ActionRequest):
            try:
                req = parse_request(req)
            except ContractError:
                return PrepareResult("DENY", [_ver("request failed the strict contract")], _NOT_VERIFIED, None, None)

        def deny(*reasons: Reason, v: VerifyResult = _NOT_VERIFIED) -> PrepareResult:
            return PrepareResult("DENY", list(reasons), v, None, None, req)

        if req.tool != TOOL:
            return deny(_ver(f"unknown tool {req.tool!r} (fail closed)"))
        inv = req.args.get("invoice_id")
        if inv is None:
            return deny(_ver("invoice_id: required to target a record (evidence gap)"))
        record_id = f"invoice:{inv.value}"
        try:
            sor = dict(self._tool.sor_for(inv.value))
        except KeyError:
            return deny(_ver("invoice_id: target record not in the system of record"))
        if docs is None:
            docs = self._docs_provider(req) if self._docs_provider is not None else {}
        v = verify_request(req, docs, sor)

        data, version = self._tool.read_record(record_id)
        # The system of record, not the documents, decides what is owed: a document the agent supplied can
        # only prove it says a value, so money claims must also agree with the records (G1).
        extra = []
        for name, want in (("amount", data.get("total")), ("invoice.total", data.get("total")),
                           ("po.total", sor.get("po.total"))):
            c = req.args.get(name)
            if c is not None and not _same_money(c.value, want):
                extra.append(_ver(f"{name}: disagrees with the system of record"))
        if extra:
            v = VerifyResult(False, v.claims, v.reasons + extra)
        if data.get("status") != "open":
            return deny(_r("AP-STALE-07", "G2", "target record is not open (already actioned)"), v=v)

        with self._conn_factory() as conn:
            scope = conn.execute("SELECT max_amount::text, vendors FROM delegations WHERE on_behalf_of = %s",
                                 (req.on_behalf_of,)).fetchone()
            vendor_id = data.get("vendor_id")
            committed = conn.execute(
                "SELECT COALESCE(SUM(amount), 0)::numeric(18,2)::text FROM commits WHERE actor = %s AND vendor_id = %s",
                (req.actor, vendor_id)).fetchone()[0]
        args = {name: req.args[name].value for name in ("amount", "variance") if name in req.args}
        args["vendor_id"] = vendor_id
        payload = {
            "tool": req.tool,
            "actor": req.actor,
            "on_behalf_of": req.on_behalf_of,
            "verify": {"ok": v.ok, "reasons": [asdict(r) for r in v.reasons]},
            "args": args,
            # No delegation = empty scope, so the policy denies AP-SCOPE-02 (never a default grant).
            "scope": {"max_amount": scope[0], "vendors": list(scope[1])} if scope else {"max_amount": "0.00", "vendors": []},
            "cumulative": {"committed": committed},
        }
        d = policy.decide(payload, self._settings.opa_url, self._settings.opa_timeout_seconds)
        reasons = list(d.reasons) + ([r for r in v.reasons if r not in d.reasons] if not v.ok else [])
        if d.outcome not in ("ALLOW", "REVIEW"):
            return deny(*reasons, v=v)

        diff = self._tool.dry_run(req)
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

    # ------------------------------------------------------------------ review tokens

    def mint_review_token(self, request_hash: str, submitter: str, reviewer: str) -> str:
        """A one-use human approval bound to one request hash (AP-REV-10). Raises on bad input."""
        if not isinstance(request_hash, str) or not _HASH.match(request_hash):
            raise ValueError("request_hash must be a sha256 hex digest")
        if not all(isinstance(x, str) and x.strip() for x in (submitter, reviewer)):
            raise ValueError("submitter and reviewer are required")
        # ponytail: token stored as-is; store sha256(token) and compare digests once tokens leave the demo.
        # ADR-008 (Phase 4) decides whether reviewer must differ from submitter; both are kept.
        token = secrets.token_urlsafe(32)
        now = _now()
        with self._conn_factory() as conn:
            conn.execute(
                "INSERT INTO review_tokens (token, request_hash, submitter, minted_by, minted_at, exp) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (token, request_hash, submitter, reviewer, now, now + self._settings.review_token_ttl_seconds))
        return token

    # ------------------------------------------------------------------ commit

    def commit(self, receipt, req, review_token=None) -> CommitResult:
        try:
            return self._commit(receipt, req, review_token)
        except Exception as e:  # fail closed (invariant 1)
            return _deny(_err(f"commit failed: {type(e).__name__}"))

    def _commit(self, receipt, req, review_token) -> CommitResult:
        if not signing.verify(receipt, self._verify_key):
            return _deny(_r("AP-SIG-09", "G2", "receipt signature invalid"))
        p = receipt["payload"]
        if set(p) != PAYLOAD_KEYS:
            return _deny(_r("AP-SIG-09", "G2", "receipt payload malformed"))
        if not isinstance(p["exp"], int) or _now() >= p["exp"]:
            return _deny(_r("AP-EXP-06", "G2", "receipt expired"))
        if not isinstance(req, ActionRequest):
            try:
                req = parse_request(req)
            except ContractError:
                return _deny(_r("AP-HASH-08", "G2", "request does not match the receipt"))
        if request_hash(req) != p["request_hash"]:
            return _deny(_r("AP-HASH-08", "G2", "request changed after prepare"))
        if p["decision"] not in ("ALLOW", "REVIEW"):
            return _deny(_err("receipt decision is not executable"))
        if p["decision"] == "REVIEW" and not isinstance(review_token, str):
            return _deny(_r("AP-REV-10", "G2", "REVIEW decision needs a human review token"))
        if "amount" not in req.args or not MONEY.match(req.args["amount"].value):
            return _deny(_err("request has no 2dp amount"))

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
                        self._burn(conn, st)
                        return _deny(_err("serialization failure after the tool was called"))
                except Exception as e:
                    conn.rollback()
                    if st.invoked:
                        self._burn(conn, st)
                    return _deny(_err(f"commit failed: {type(e).__name__}"))
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
        now = _now()
        if now >= p["exp"]:  # the receipt may have expired while waiting for the lane
            return deny(_r("AP-EXP-06", "G2", "receipt expired"))

        if p["decision"] == "REVIEW":
            row = conn.execute(
                "UPDATE review_tokens SET used_at = %s, used_nonce = %s "
                "WHERE token = %s AND request_hash = %s AND used_at IS NULL AND exp > %s RETURNING token",
                (now, p["nonce"], review_token, p["request_hash"], now)).fetchone()
            if row is None:
                return deny(self._token_reason(conn, review_token, p["request_hash"], now))

        rec = conn.execute("SELECT data, version FROM records WHERE record_id = %s FOR UPDATE",
                           (p["record_id"],)).fetchone()
        if rec is None:
            return deny(_r("AP-STALE-07", "G2", "record no longer exists"))
        data, version = rec
        amount = Decimal(req.args["amount"].value)
        st.row = (p["nonce"], p["idempotency_key"], p["request_hash"], req.actor, req.on_behalf_of,
                  str(data.get("vendor_id")), amount, p["record_id"], now)
        try:
            conn.execute(
                "INSERT INTO commits (nonce, idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount, "
                "record_id, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", st.row)
        except errors.UniqueViolation:
            return deny(_r("AP-REP-05", "G2", "nonce or idempotency key already used"))

        total = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM commits WHERE actor = %s AND vendor_id = %s",
                             (req.actor, st.row[5])).fetchone()[0]
        if total > CAP:
            return deny(_r("AP-CUM-03", "G1", "actor+vendor cumulative total exceeds 5000.00"))
        if version != p["version"]:
            return deny(_r("AP-STALE-07", "G2", "record version changed since prepare"))
        diff = self._tool.dry_run(req)
        if _diff_hash(diff, data) != p["diff_hash"]:
            return deny(_r("AP-STALE-07", "G2", "dry-run diff changed since prepare"))

        st.invoked = True
        try:
            result = self._tool.execute(req, version, p["idempotency_key"], conn)
        except Exception as e:
            after = conn.execute("SELECT data, version FROM records WHERE record_id = %s", (p["record_id"],)).fetchone()
            conn.rollback()
            self._burn(conn, st)
            # Classification only (the outcome is DENY + rollback either way): the version moved but the approved
            # effect is absent -> someone else wrote mid-flight (STALE); otherwise the tool itself failed.
            target = str(diff.get("status", "")).partition("->")[2]
            applied = after is not None and after[1] == version + 1 and after[0].get("status") == target
            if (after is None or after[1] != version) and not applied:
                return _deny(_r("AP-STALE-07", "G2", "record changed while the tool ran"))
            return _deny(_err(f"tool error: {type(e).__name__}"))
        after = conn.execute("SELECT version FROM records WHERE record_id = %s", (p["record_id"],)).fetchone()
        if after is None or after[0] not in (version, version + 1):
            conn.rollback()
            self._burn(conn, st)
            return _deny(_r("AP-STALE-07", "G2", "record changed beyond the approved diff"))
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

    @staticmethod
    def _burn(conn, st: _Attempt) -> None:
        """The tool was reached but the tx rolled back: the outcome is unknown, so the nonce and idempotency key
        are spent (a retry is AP-REP-05) and the amount counts toward the cap (fail closed, ADR-010)."""
        try:
            conn.execute(
                "INSERT INTO commits (nonce, idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount, "
                "record_id, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", st.row)
            conn.commit()
        except Exception:
            # ponytail: if the burn itself fails, a retry is stopped only by the tool-side idempotency key.
            conn.rollback()
