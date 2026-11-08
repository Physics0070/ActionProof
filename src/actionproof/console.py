"""Review-console backend (FastAPI; deck slide 3 step 4 "a human approves with a one-use token"; S9.2, S9.6, S7.8).

    python -m actionproof.console [--proxy "<upstream cmd>"]     # CONSOLE_BIND_HOST (default 127.0.0.1):CONSOLE_PORT; OpenAPI at /openapi.json

The human side of a REVIEW. JSON API for the Phase 7 UI (types are generated from web/openapi.json, invariant 7).
- Server-side sessions: the cookie holds a random id, the database only sha256(id) (console_sessions); httpOnly,
  SameSite=Strict, Secure on https (CONSOLE_COOKIE_SECURE=auto|true|false). Login always mints a fresh id and drops
  the presented one (no fixation). Passwords are argon2id (argon2-cffi).
- CSRF: double submit. Every state-changing request needs X-CSRF-Token equal to the ap_csrf cookie AND to the
  session's stored token.
- Login: one generic error for any bad credential (an unknown login verifies against a dummy hash too) and a
  lockout per (login, client IP) after LOGIN_MAX_FAILURES failures, for any login string (no enumeration).
- Roles come from people.roles. Deciding needs 'reviewer' (admin cannot, ADR-008); reading needs reviewer or admin.
- The reviewer identity for approve/reject is ONLY the session login (ADR-008): DecisionBody forbids extra fields,
  so a body naming a reviewer is a 422, never honoured. The response comes after the commit outcome (no optimism).
- Nothing returned carries receipt, signature, nonce, review-token or key material; every error is
  {"error": {"code", "message"}} without tracebacks; every response carries strict security headers.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Annotated, Literal

import pymupdf
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, FastAPI, Path as PathParam, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from actionproof import audit, review
from actionproof.config import ConfigError
from actionproof.contracts import IDENT
from actionproof.gate import TARGETS
from actionproof.server import RateLimiter

ROOT = Path(__file__).resolve().parents[2]
EVAL_RESULTS = ROOT / "eval" / "results.json"  # written by the Phase 6 eval runner
SESSION_COOKIE, CSRF_COOKIE, CSRF_HEADER = "ap_session", "ap_csrf", "x-csrf-token"
# ponytail: in-memory, per process; upgrade path is a shared store (Postgres/Redis) for several console replicas.
LOGIN_MAX_FAILURES, LOGIN_LOCKOUT_SECONDS = 5, 300
PAGE_ZOOM = 2  # page render scale (PDF points -> pixels)
HASH = r"^[0-9a-f]{64}$"
STATUSES = ("pending", "approved", "rejected", "executed", "denied")
AUDIT_DETAIL_KEYS = {"reviewer_login", "reviewer_person", "reviewer", "reason", "approve", "amount", "version",
                     "code", "tool"}  # never nonce / idempotency key
SECURITY_HEADERS = {
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cache-control": "no-store",
}
_PH = PasswordHasher()  # argon2id, library defaults
_DUMMY_HASH = _PH.hash(secrets.token_urlsafe(16))  # an unknown login costs one verify too


# --------------------------------------------------------------------------------------------------- settings

class ConsoleSettings(BaseModel):
    """Console-only env (invariant 7). The gate's settings are config.load_settings; DOCS_DIR is ServerSettings."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    web_origin: str
    session_ttl_seconds: int = 28800
    console_cookie_secure: Literal["auto", "true", "false"] = "auto"
    rate_limit_per_minute: int = 60
    console_port: int = 8766
    console_bind_host: str = "127.0.0.1"  # loopback unless the operator says otherwise (compose sets 0.0.0.0)

    @field_validator("web_origin")
    @classmethod
    def _origin(cls, v: str) -> str:
        if not re.match(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$", v):
            raise ValueError("must be a scheme://host[:port] origin")
        return v

    @field_validator("session_ttl_seconds", "rate_limit_per_minute")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1")
        return v

    @field_validator("console_bind_host")
    @classmethod
    def _bind(cls, v: str) -> str:
        import ipaddress

        try:
            ipaddress.ip_address(v)
        except ValueError:
            if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", v):
                raise ValueError("must be an IP address or hostname") from None
        return v

    @field_validator("console_port")
    @classmethod
    def _port(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("must be a TCP port")
        return v


def load_console_settings(env=os.environ) -> ConsoleSettings:
    names = {f: f.upper() for f in ConsoleSettings.model_fields}
    raw = {f: env[v] for f, v in names.items() if v in env}
    try:
        return ConsoleSettings.model_validate(raw, strict=False)
    except ValidationError as e:
        bad = sorted({names[str(err["loc"][0])] for err in e.errors() if err.get("loc")})
        raise ConfigError(f"invalid or missing config: {', '.join(bad)}") from None


# --------------------------------------------------------------------------------------------------- users

def set_password(conn, login: str, password: str) -> None:
    """Create or update a console user (the login must exist in people). Stores only the argon2id hash."""
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    conn.execute("INSERT INTO console_users (login, password_hash) VALUES (%s, %s) "
                 "ON CONFLICT (login) DO UPDATE SET password_hash = EXCLUDED.password_hash, disabled = false",
                 (login, _PH.hash(password)))


def _verify_password(stored: str | None, password: str) -> bool:
    try:
        return _PH.verify(stored or _DUMMY_HASH, password) and stored is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


class _Lockout:
    """Failed logins per (login, client IP). LOGIN_MAX_FAILURES failures lock the pair for LOGIN_LOCKOUT_SECONDS."""

    def __init__(self):
        self._fails: dict[tuple, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def locked(self, key) -> bool:
        with self._lock:
            n, until = self._fails.get(key, (0, 0.0))
            if n >= LOGIN_MAX_FAILURES and time.monotonic() >= until:
                self._fails.pop(key, None)
                return False
            return n >= LOGIN_MAX_FAILURES

    def fail(self, key) -> None:
        with self._lock:
            n, _ = self._fails.get(key, (0, 0.0))
            self._fails[key] = (n + 1, time.monotonic() + LOGIN_LOCKOUT_SECONDS)

    def reset(self, key) -> None:
        with self._lock:
            self._fails.pop(key, None)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# --------------------------------------------------------------------------------------------------- errors

class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


_HTTP_CODES = {401: "unauthenticated", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
               429: "rate_limited"}


# --------------------------------------------------------------------------------------------------- models

class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorOut(BaseModel):
    error: ErrorBody


class ReasonOut(BaseModel):
    rule: str
    guarantee: str
    msg: str


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class Me(BaseModel):
    login: str
    roles: list[str]


class LoginOut(Me):
    csrf_token: str


class Ok(BaseModel):
    ok: bool


class DecisionBody(BaseModel):
    """No reviewer field, by design: the reviewer is the session login (ADR-008); extras are refused."""
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=8, max_length=500)


class DecisionOut(BaseModel):
    outcome: Literal["EXECUTED", "DENY", "REJECTED"]
    status: str
    reasons: list[ReasonOut]


class QueueItem(BaseModel):
    request_hash: str
    tool: str
    actor: str
    on_behalf_of: str
    status: str
    created_at: int
    amount: str | None
    top_rule: str | None
    reasons: list[ReasonOut]
    reviewer: str | None
    decided_at: int | None


class QueuePage(BaseModel):
    items: list[QueueItem]
    next_cursor: str | None


class Verification(BaseModel):
    ok: bool
    method: str | None
    reason: ReasonOut | None


class ClaimView(BaseModel):
    name: str
    claim: Literal["DIRECT", "DERIVED", "ASSERTED"]
    value: str
    evidence: bool  # False for ASSERTED: shown, never evidence
    taint: str | None
    source: dict | None  # {doc, page, bbox} or {doc, pointer}
    derivation: dict | None  # {fn, inputs}
    doc_sha256: str | None
    verification: Verification | None


class RequestDetail(BaseModel):
    request_hash: str
    tool: str
    actor: str
    on_behalf_of: str
    label: str
    record_id: str
    status: str
    created_at: int
    reviewer: str | None
    decided_at: int | None
    card: str | None
    claims: list[ClaimView]
    taint_flags: list[str]
    policy_reasons: list[ReasonOut]  # the decision that parked it
    outcome_reasons: list[ReasonOut]  # the latest outcome (rejection, denial)
    diff: dict | None
    before: dict | None


class AuditVerify(BaseModel):
    ok: bool
    entries: int
    checkpoints: int
    error: str | None


class AuditEntry(BaseModel):
    seq: int
    ts: int
    kind: str
    request_hash: str | None
    actor: str | None
    on_behalf_of: str | None
    record_id: str | None
    decision: str | None
    rules: list[ReasonOut]
    detail: dict
    entry_hash: str


class AuditPage(BaseModel):
    items: list[AuditEntry]


class SeqRange(BaseModel):
    first_seq: int | None
    last_seq: int | None


class ReplayAttempt(BaseModel):
    """One recorded G2 bounce against a request, from the audit log (rule ids and seq only: no detail, no secrets)."""
    seq: int
    ts: int
    kind: str
    decision: str
    reasons: list[ReasonOut]


class PublicReplay(BaseModel):
    request_hash: str
    record_id: str
    tool: str
    label: str
    decision: str  # the gate's decision at prepare (REVIEW)
    status: str  # where the review ended up
    reviewer: str | None
    decided_at: int | None
    card: str | None
    claims: list[ClaimView]
    reasons: list[ReasonOut]
    outcome_reasons: list[ReasonOut]
    audit: SeqRange
    replay_attempts: list[ReplayAttempt]  # audited DENYs with a G2 reason (AP-REP-05, AP-STALE-07, ...)


class EvalOut(BaseModel):
    available: bool
    results: dict | None = None


# --------------------------------------------------------------------------------------------------- views

def _claims(request: dict, verified: dict) -> list[dict]:
    out = []
    for name, c in request["args"].items():
        src = c.get("src")
        source = {k: v for k, v in src.items() if v is not None} if src else None
        v = verified.get(name)
        out.append({
            "name": name, "claim": c["claim"], "value": c["value"], "evidence": c["claim"] != "ASSERTED",
            "taint": c.get("taint"), "source": source,
            "derivation": {"fn": c["fn"], "inputs": c["inputs"]} if c.get("fn") else None,
            "doc_sha256": c.get("doc_sha256"),
            "verification": {"ok": v["ok"], "method": v["method"], "reason": v["reason"]} if v else None,
        })
    return out


def _record_id(request: dict) -> str:
    t = TARGETS.get(request["tool"])
    target = request["args"].get(t.arg) if t else None
    return f"{t.kind}:{target['value']}" if target else ""


def _cursor(created_at: int, h: str) -> str:
    return base64.urlsafe_b64encode(f"{created_at}:{h}".encode()).decode().rstrip("=")


def _uncursor(c: str) -> tuple[int, str]:
    try:
        raw = base64.urlsafe_b64decode(c + "=" * (-len(c) % 4)).decode("ascii")
    except Exception:
        raise ApiError(422, "validation_error", "invalid cursor") from None
    m = re.match(r"^(\d{1,19}):([0-9a-f]{64})$", raw)
    if not m:
        raise ApiError(422, "validation_error", "invalid cursor")
    return int(m.group(1)), m.group(2)


_EFFECTIVE_STATUS = ("CASE WHEN p.status IN ('pending', 'approved') AND EXISTS (SELECT 1 FROM audit_log a "
                     "WHERE a.kind = 'commit' AND a.decision = 'EXECUTED' AND a.request_hash = p.request_hash) "
                     "THEN 'executed' ELSE p.status END")


# --------------------------------------------------------------------------------------------------- app

class Session(BaseModel):
    login: str
    roles: list[str]
    csrf: str
    sid_hash: str


def create_app(gate, docs, conn_factory, settings: ConsoleSettings) -> FastAPI:
    """`gate`: the human side's Gate (complete_review mints and commits through it). `docs`: server.DocStore.
    `conn_factory`: the gate's database connections. Nothing here is reachable from the MCP/agent surface."""
    lockout = _Lockout()
    limiter = RateLimiter(settings.rate_limit_per_minute)

    app = FastAPI(title="ActionProof review console", version="0.1.0", docs_url=None, redoc_url=None,
                  description="Human side of a REVIEW decision. Session cookie + X-CSRF-Token; JSON errors "
                              "{error: {code, message}}.")
    app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_credentials=True,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-CSRF-Token"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception:  # fail closed, never a traceback or an exception message
            response = _error(500, "internal", "internal error")
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    @app.exception_handler(ApiError)
    async def _api_error(request, e: ApiError):
        return _error(e.status, e.code, e.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request, e: StarletteHTTPException):
        code = _HTTP_CODES.get(e.status_code, "http_error")
        return _error(e.status_code, code, code.replace("_", " "))

    @app.exception_handler(RequestValidationError)
    async def _validation(request, e: RequestValidationError):  # never echo the input
        fields = sorted({".".join(str(x) for x in err.get("loc", ())[1:]) or "body" for err in e.errors()})
        return _error(422, "validation_error", f"invalid request: {', '.join(fields)}"[:200])

    # ---- dependencies

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def public_rate(request: Request) -> None:
        if not limiter.allow(("public", client_ip(request))):
            raise ApiError(429, "rate_limited", "rate limit exceeded; retry later")

    def session(request: Request) -> Session:
        sid = request.cookies.get(SESSION_COOKIE)
        if not sid or len(sid) > 128:
            raise ApiError(401, "unauthenticated", "a valid session is required")
        h, now = _sha(sid), int(time.time())
        with conn_factory() as conn:
            row = conn.execute(
                "SELECT s.login, s.csrf_token, p.roles FROM console_sessions s JOIN console_users u USING (login) "
                "JOIN people p USING (login) WHERE s.sid_hash = %s AND s.expires_at > %s AND NOT u.disabled",
                (h, now)).fetchone()
            if row is None:
                raise ApiError(401, "unauthenticated", "a valid session is required")
            conn.execute("UPDATE console_sessions SET last_seen = %s WHERE sid_hash = %s", (now, h))
        return Session(login=row[0], csrf=row[1], roles=list(row[2]), sid_hash=h)

    def csrf(request: Request, s: Annotated[Session, Depends(session)]) -> Session:
        header, cookie = request.headers.get(CSRF_HEADER, ""), request.cookies.get(CSRF_COOKIE, "")
        if not (header and hmac.compare_digest(header, cookie) and hmac.compare_digest(header, s.csrf)):
            raise ApiError(403, "csrf", "missing or invalid CSRF token")
        return s

    def reader(s: Annotated[Session, Depends(session)]) -> Session:
        if not {"reviewer", "admin"} & set(s.roles):
            raise ApiError(403, "forbidden", "the reviewer or admin role is required")
        return s

    def reviewer(s: Annotated[Session, Depends(csrf)]) -> Session:
        if "reviewer" not in s.roles:  # admin cannot decide (ADR-008)
            raise ApiError(403, "forbidden", "the reviewer role is required")
        return s

    def secure(request: Request) -> bool:
        mode = settings.console_cookie_secure
        return request.url.scheme == "https" if mode == "auto" else mode == "true"

    def hash_param():
        return PathParam(pattern=HASH)

    router = APIRouter(responses={"4XX": {"model": ErrorOut}, "5XX": {"model": ErrorOut}})

    # ---- auth

    @router.post("/api/auth/login", response_model=LoginOut, tags=["auth"])
    def login(body: LoginBody, request: Request, response: Response):
        key = (body.login, client_ip(request))
        if lockout.locked(key):
            raise ApiError(429, "rate_limited", "too many failed attempts; try again later")
        with conn_factory() as conn:
            row = conn.execute("SELECT u.password_hash, u.disabled, p.roles FROM console_users u "
                               "JOIN people p USING (login) WHERE u.login = %s", (body.login,)).fetchone()
            ok = _verify_password(row[0] if row else None, body.password) and not row[1]
            if not ok:
                lockout.fail(key)
                raise ApiError(401, "invalid_credentials", "invalid login or password")
            lockout.reset(key)
            presented = request.cookies.get(SESSION_COOKIE)
            if presented:  # session fixation: the presented id never survives a login
                conn.execute("DELETE FROM console_sessions WHERE sid_hash = %s", (_sha(presented),))
            sid, token, now = secrets.token_urlsafe(32), secrets.token_urlsafe(32), int(time.time())
            conn.execute("INSERT INTO console_sessions (sid_hash, login, csrf_token, created_at, expires_at, "
                         "last_seen) VALUES (%s, %s, %s, %s, %s, %s)",
                         (_sha(sid), body.login, token, now, now + settings.session_ttl_seconds, now))
        ttl, sec = settings.session_ttl_seconds, secure(request)
        response.set_cookie(SESSION_COOKIE, sid, max_age=ttl, path="/", httponly=True, samesite="strict", secure=sec)
        response.set_cookie(CSRF_COOKIE, token, max_age=ttl, path="/", httponly=False, samesite="strict", secure=sec)
        return LoginOut(login=body.login, roles=list(row[2]), csrf_token=token)

    @router.post("/api/auth/logout", response_model=Ok, tags=["auth"])
    def logout(s: Annotated[Session, Depends(csrf)], request: Request, response: Response):
        with conn_factory() as conn:
            conn.execute("DELETE FROM console_sessions WHERE sid_hash = %s", (s.sid_hash,))
        sec = secure(request)
        for name in (SESSION_COOKIE, CSRF_COOKIE):
            response.delete_cookie(name, path="/", samesite="strict", secure=sec, httponly=name == SESSION_COOKIE)
        return Ok(ok=True)

    @router.get("/api/auth/me", response_model=Me, tags=["auth"])
    def me(s: Annotated[Session, Depends(session)]):
        return Me(login=s.login, roles=s.roles)

    # ---- reviews

    @router.get("/api/queue", response_model=QueuePage, tags=["reviews"])
    def queue(s: Annotated[Session, Depends(reader)],
              status: Annotated[Literal[STATUSES] | None, Query()] = None,  # type: ignore[valid-type]
              tool: Annotated[Literal[tuple(TARGETS)] | None, Query()] = None,  # type: ignore[valid-type]
              actor: Annotated[str | None, Query(pattern=IDENT)] = None,
              limit: Annotated[int, Query(ge=1, le=100)] = 50,
              cursor: Annotated[str | None, Query(max_length=128)] = None):
        where, params = [], []
        for col, val in (("p.status", status), ("p.request->>'tool'", tool), ("p.actor", actor)):
            if val is not None:
                where.append(f"{col} = %s")
                params.append(val)
        if cursor is not None:
            at, h = _uncursor(cursor)
            where.append("(p.created_at, p.request_hash) < (%s, %s)")
            params += [at, h]
        sql = ("SELECT p.request_hash, p.request->>'tool', p.actor, p.on_behalf_of, p.status, p.created_at, "
               "p.request->'args'->'amount'->>'value', p.receipt->'payload'->'reasons'->0->>'rule', p.reasons, "
               "p.reviewer, p.decided_at FROM pending_reviews p"
               + (" WHERE " + " AND ".join(where) if where else "")
               + " ORDER BY p.created_at DESC, p.request_hash DESC LIMIT %s")
        with conn_factory() as conn:
            review.reconcile(conn)
            rows = conn.execute(sql, params + [limit + 1]).fetchall()
        keys = ("request_hash", "tool", "actor", "on_behalf_of", "status", "created_at", "amount", "top_rule",
                "reasons", "reviewer", "decided_at")
        items = [dict(zip(keys, r)) for r in rows[:limit]]
        nxt = _cursor(items[-1]["created_at"], items[-1]["request_hash"]) if len(rows) > limit else None
        return QueuePage(items=items, next_cursor=nxt)

    def _row(conn, h: str):
        review.reconcile(conn)
        row = conn.execute("SELECT request, receipt->'payload'->'reasons', actor, on_behalf_of, status, created_at, "
                           "reviewer, decided_at, card, claims, diff, before, reasons FROM pending_reviews "
                           "WHERE request_hash = %s", (h,)).fetchone()
        if row is None:
            raise ApiError(404, "not_found", "no review for this request")
        return row

    @router.get("/api/requests/{request_hash}", response_model=RequestDetail, tags=["reviews"])
    def detail(s: Annotated[Session, Depends(reader)], request_hash: Annotated[str, hash_param()]):
        with conn_factory() as conn:
            (req, policy_reasons, actor, obo, status, created_at, rev, decided_at, card, verified, diff, before,
             outcome) = _row(conn, request_hash)
        return RequestDetail(
            request_hash=request_hash, tool=req["tool"], actor=actor, on_behalf_of=obo,
            label=f"requested by {actor} for {obo}", record_id=_record_id(req), status=status, created_at=created_at,
            reviewer=rev, decided_at=decided_at, card=card, claims=_claims(req, verified),
            taint_flags=[n for n, c in req["args"].items() if c.get("taint")], policy_reasons=policy_reasons,
            outcome_reasons=outcome, diff=diff, before=before)

    @router.get("/api/requests/{request_hash}/page/{n}.png", tags=["reviews"],
                responses={200: {"content": {"image/png": {}}, "description": "the cited page, boxes drawn"}})
    def page_png(s: Annotated[Session, Depends(reader)], request_hash: Annotated[str, hash_param()],
                 n: Annotated[int, PathParam(ge=1, le=1000)], doc: Annotated[str, Query(min_length=1, max_length=256)]):
        """PyMuPDF render of page n of a document in the server's store, with a rectangle around every DIRECT
        claim of this request that cites (doc, n) and passed verification. The doc id is only a key of the store's
        manifest (never a path)."""
        with conn_factory() as conn:
            req, *_, verified, _diff, _before, _outcome = _row(conn, request_hash)
        stored = docs.get(doc)
        boxes = [c["src"]["bbox"] for name, c in req["args"].items()
                 if c["claim"] == "DIRECT" and c.get("src") and c["src"].get("doc") == doc
                 and c["src"].get("page") == n and c["src"].get("bbox") and verified.get(name, {}).get("ok") is True]
        if stored is None or stored[1] != "pdf" or not boxes:
            raise ApiError(404, "not_found", "no verified citation on that page of that document")
        with pymupdf.open(stream=stored[0], filetype="pdf") as pdf:
            if n > pdf.page_count:
                raise ApiError(404, "not_found", "no verified citation on that page of that document")
            page = pdf[n - 1]
            for x0, top, x1, bottom in boxes:
                page.draw_rect(pymupdf.Rect(float(x0), float(top), float(x1), float(bottom)), color=(0.86, 0.1, 0.1),
                               width=1.5)
            png = page.get_pixmap(matrix=pymupdf.Matrix(PAGE_ZOOM, PAGE_ZOOM)).tobytes("png")
        return Response(content=png, media_type="image/png")

    @router.post("/api/requests/{request_hash}/decision", response_model=DecisionOut, tags=["reviews"])
    def decision(s: Annotated[Session, Depends(reviewer)], request_hash: Annotated[str, hash_param()],
                 body: DecisionBody):
        # The reviewer is the session subject, nothing else (ADR-008). Synchronous: the answer is the commit outcome.
        o = review.complete_review(gate, conn_factory, request_hash, s.login, body.decision == "approve",
                                   body.reason)
        if o.status == "not_found":
            raise ApiError(404, "not_found", "no review for this request")
        replayed = any(r.rule == "AP-REP-05" for r in o.reasons)  # decided before: this call changed nothing
        outcome = "DENY" if replayed else {"executed": "EXECUTED", "rejected": "REJECTED"}.get(o.status, "DENY")
        return DecisionOut(outcome=outcome, status=o.status,
                           reasons=[ReasonOut(rule=r.rule, guarantee=r.guarantee, msg=r.msg) for r in o.reasons])

    # ---- audit

    @router.get("/api/audit/verify", response_model=AuditVerify, tags=["audit"])
    def audit_verify(s: Annotated[Session, Depends(reader)]):
        """The verifier's library function (audit.verify) on one read-only snapshot, against the gate's public key."""
        try:
            with conn_factory() as conn:
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                n, m = audit.verify(conn, gate._verify_key)
        except audit.AuditFailure as f:
            return AuditVerify(ok=False, entries=0, checkpoints=0, error=f"seq {f.seq}: {f.reason}")
        except Exception as e:
            return AuditVerify(ok=False, entries=0, checkpoints=0,
                               error=f"cannot read the audit log ({type(e).__name__})")
        return AuditVerify(ok=True, entries=n, checkpoints=m, error=None)

    @router.get("/api/audit", response_model=AuditPage, tags=["audit"])
    def audit_recent(s: Annotated[Session, Depends(reader)], limit: Annotated[int, Query(ge=1, le=200)] = 50):
        with conn_factory() as conn:
            rows = conn.execute("SELECT seq, ts, kind, request_hash, actor, on_behalf_of, record_id, decision, rules, "
                                "detail, entry_hash FROM audit_log ORDER BY seq DESC LIMIT %s", (limit,)).fetchall()
        keys = ("seq", "ts", "kind", "request_hash", "actor", "on_behalf_of", "record_id", "decision", "rules",
                "detail", "entry_hash")
        items = []
        for r in rows:
            e = dict(zip(keys, r))
            e["detail"] = {k: v for k, v in e["detail"].items() if k in AUDIT_DETAIL_KEYS}
            items.append(e)
        return AuditPage(items=items)

    # ---- public (no auth, read-only, rate-limited)

    @router.get("/api/public/replay/inv-2048", response_model=PublicReplay, tags=["public"],
                dependencies=[Depends(public_rate)])
    def public_replay():
        """The REAL stored decision for the hero invoice INV-2048 (deck slides 6-7), straight from the database."""
        with conn_factory() as conn:
            row = conn.execute(
                f"SELECT p.request_hash, p.request, p.receipt->'payload'->>'decision', {_EFFECTIVE_STATUS}, "
                "p.reviewer, p.decided_at, p.card, p.claims, p.receipt->'payload'->'reasons', p.reasons, "
                "p.actor, p.on_behalf_of FROM pending_reviews p "
                "WHERE p.request->'args'->'invoice_id'->>'value' = 'INV-2048' "
                "ORDER BY p.created_at DESC, p.request_hash DESC LIMIT 1").fetchone()
            if row is None:
                raise ApiError(404, "not_found", "no stored decision for INV-2048 yet")
            h, req, dec, status, rev, decided_at, card, verified, reasons, outcome, actor, obo = row
            lo, hi = conn.execute("SELECT min(seq), max(seq) FROM audit_log WHERE request_hash = %s",
                                  (h,)).fetchone()
            attempts = [ReplayAttempt(seq=q, ts=t, kind=k, decision=d, reasons=[x for x in rs if x["guarantee"] == "G2"])
                        for q, t, k, d, rs in conn.execute(
                            "SELECT seq, ts, kind, decision, rules FROM audit_log WHERE request_hash = %s "
                            "AND kind IN ('commit', 'refuse', 'review') AND decision = 'DENY' "
                            "AND rules @> '[{\"guarantee\": \"G2\"}]' ORDER BY seq", (h,))]
        return PublicReplay(request_hash=h, record_id=_record_id(req), tool=req["tool"],
                            label=f"requested by {actor} for {obo}", decision=dec, status=status, reviewer=rev,
                            decided_at=decided_at, card=card, claims=_claims(req, verified), reasons=reasons,
                            outcome_reasons=outcome, audit=SeqRange(first_seq=lo, last_seq=hi),
                            replay_attempts=attempts)

    @router.get("/api/public/eval", response_model=EvalOut, response_model_exclude_none=True, tags=["public"],
                dependencies=[Depends(public_rate)])
    def public_eval():
        try:
            results = json.loads(EVAL_RESULTS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return EvalOut(available=False)
        return EvalOut(available=True, results=results) if isinstance(results, dict) else EvalOut(available=False)

    @router.get("/api/health", response_model=Ok, tags=["public"])
    def health():
        try:
            with conn_factory() as conn:
                conn.execute("SELECT 1")
        except Exception:
            raise ApiError(503, "unavailable", "database unavailable") from None
        return Ok(ok=True)

    app.include_router(router)
    return app


# --------------------------------------------------------------------------------------------------- main

def main(argv=None) -> int:
    from actionproof import server
    from actionproof.config import load_settings

    ap = argparse.ArgumentParser(prog="python -m actionproof.console", description="ActionProof review console API")
    ap.add_argument("--proxy", metavar="CMD", default=None,
                    help="commit approved reviews through this upstream (same as the MCP server's --proxy)")
    args = ap.parse_args(argv)
    try:
        settings = load_settings()
        cs = load_console_settings()
        ss = server.load_server_settings(need_principal=False)
        wired = server.build_app(settings, ss, args.proxy)
    except ConfigError as e:
        print(f"ConfigError: {e}", file=sys.stderr)
        return 2
    import uvicorn

    uvicorn.run(create_app(wired.gate, wired.docs, wired._conn_factory, cs), host=cs.console_bind_host, port=cs.console_port,
                log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
