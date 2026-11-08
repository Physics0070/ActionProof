"""Case executor: runs one eval case (spec/cases-format.md) against an Arm and reports what happened.

Tool executions are counted from the system of record's executed-call log, the mocks' `.calls` (spec: "tool executed
= one entry in the executed-call log"), never from what an arm says it did.

Each case starts from a truncated + reseeded database (cheaper than a database per case and just as isolated: the
only state is the tables db.reset truncates). The gate arm gets a POOLED connection factory, as a real deployment
(a pooled client) would: a fresh Postgres backend costs ~240 ms on Windows and would be measured as gate latency.
"""
from __future__ import annotations

import copy
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from psycopg.types.json import Jsonb

from actionproof import db as dbmod
from actionproof import gate as gate_mod
from actionproof.config import Settings
from actionproof.gate import Gate, Principal
from actionproof.mocks import MockERP, MockPayments, MockRefunds
from actionproof.signing import Signer
from eval import cases as ev

ROOT = Path(__file__).resolve().parents[1]
INVOICE_TOOL, REFUND_TOOL = "payments.approve_invoice", "payments.refund_payment"


class ArmError(Exception):
    """An arm cannot give an honest answer (e.g. the judge API is down). The run reports the arm as an error and
    prints no numbers for it, rather than counting an outage as a block."""


class Out(NamedTuple):
    outcome: str                 # prepare: ALLOW REVIEW DENY DEFERRED EXECUTED; commit: EXECUTED DENY; mint: MINTED REFUSED N/A
    rules: list
    data: dict | None = None     # actionproof prepare: {"receipt": ...}
    extra_ms: float = 0.0        # time not spent in this process (a cached judge answer reports its recorded latency)


class StepLog(NamedTuple):
    id: str
    op: str
    outcome: str
    rules: list
    ms: float
    receipt: bool = False        # a prepare that handed back a signed receipt


@dataclass
class CaseResult:
    case_id: str
    arm: str
    steps: list[StepLog] = field(default_factory=list)
    executions: int = 0

    @property
    def request_ms(self) -> float:
        """Wall time of the gated calls (prepare + commit + replay); minting is a human step."""
        return sum(s.ms for s in self.steps if s.op in ("prepare", "commit", "replay"))


def read_dotenv(path: Path | str) -> dict:
    """Minimal KEY=VALUE parser (comments, blanks and malformed lines skipped, optional quotes stripped)."""
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        key, sep, value = line.partition("=")
        if not line or line.startswith("#") or not sep:
            continue
        out[key.strip()] = value.strip().strip("\"'")
    return out


# ---------------------------------------------------------------- pooled connections (as a deployment would)
class _Pooled:
    def __init__(self, pool: list, conn):
        object.__setattr__(self, "_pool", pool)
        object.__setattr__(self, "_c", conn)

    def __getattr__(self, name):
        return getattr(self._c, name)

    def __setattr__(self, name, value):
        setattr(self._c, name, value)

    def __enter__(self):
        return self

    def __exit__(self, et, ev_, tb):
        if not self._c.closed:
            self._c.rollback() if et else self._c.commit()
        self.close()

    def close(self):
        c = self._c
        if c.closed:
            return
        try:
            c.rollback()
            c.isolation_level = None
        except Exception:
            c.close()
            return
        if len(self._pool) < 16:
            self._pool.append(c)
        else:
            c.close()


class Env:
    """Everything an arm needs: pooled DB, the mock downstream systems, a gate, the OPA URL and a movable clock."""

    def __init__(self, database_url: str, opa_url: str, key_path, tesseract_cmd: str | None = None):
        self.pool: list = []

        def factory():
            try:
                conn = self.pool.pop()
            except IndexError:
                conn = dbmod.connect(url=database_url)
            return _Pooled(self.pool, conn)

        self.factory = factory
        self.db = dbmod.connect(url=database_url)
        self.erp = MockERP(factory)
        self.payments = MockPayments(self.erp, factory)
        self.refunds = MockRefunds(self.erp, factory)
        self.tools = {INVOICE_TOOL: self.payments, REFUND_TOOL: self.refunds}
        tess = tesseract_cmd or os.environ.get("TESSERACT_CMD") or read_dotenv(ROOT / ".env.example").get(
            "TESSERACT_CMD", "tesseract")
        os.environ.setdefault("OCR_POOL_SIZE", read_dotenv(ROOT / ".env.example").get("OCR_POOL_SIZE", "0"))  # as deployed
        os.environ.setdefault("TESSERACT_CMD", tess)  # extract.py reads the binary path from the environment
        self.settings = Settings(database_url=database_url, opa_url=opa_url, tesseract_cmd=tess,
                                 signing_key_path=str(key_path))
        self.gate = Gate(self.settings, Signer.from_path(self.settings.signing_key_path, self.settings.signing_kid),
                         factory, self.tools)
        self.clock = 0

    def sql(self, q: str, params=()):
        cur = self.db.execute(q, params)
        rows = cur.fetchall() if cur.description else None
        self.db.commit()
        return rows

    def close(self):
        for c in [*self.pool, self.db]:
            try:
                c.close()
            except Exception:
                pass
        self.pool.clear()

    def seed(self, case: ev.Case) -> None:
        dbmod.reset(self.db)
        for login, person, roles in dbmod.PEOPLE:
            self.sql("INSERT INTO people (login, person_id, roles) VALUES (%s, %s, %s)", (login, person, list(roles)))
        for p in case.setup.people:
            self.sql("INSERT INTO people (login, person_id, roles) VALUES (%s, %s, %s)",
                     (p.login, p.person_id, p.roles))
        for r in case.setup.records:
            self.sql("INSERT INTO records (record_id, kind, data, version) VALUES (%s, %s, %s, %s)",
                     (r.record_id, r.kind, Jsonb(r.data()), r.version))
        deleg = case.setup.delegations
        if deleg is None:
            ids = lambda k: sorted({getattr(r, k) for r in case.setup.records if getattr(r, k)})  # noqa: E731
            deleg = [ev.Delegation(on_behalf_of="user-123", max_amount="5000.00", vendors=ids("vendor_id"),
                                   customers=ids("customer_id"))]
        for d in deleg:
            self.sql("INSERT INTO delegations (on_behalf_of, max_amount, vendors, customers) "
                     "VALUES (%s, %s::numeric, %s, %s)", (d.on_behalf_of, d.max_amount, d.vendors, d.customers))
        for i, pc in enumerate(case.setup.prior_commits):
            self.sql("INSERT INTO commits (nonce, idempotency_key, request_hash, actor, on_behalf_of, vendor_id, "
                     "amount, record_id, created_at) VALUES (%s, %s, 'prior', %s, %s, %s, %s, %s, 1)",
                     (f"prior-{i}", f"prior-{i}", pc.actor, pc.on_behalf_of, pc.counterparty, pc.amount,
                      pc.record_id or f"prior:{i}"))
            if pc.record_id:
                self.sql("UPDATE records SET data = data || jsonb_build_object('refunded', "
                         "(COALESCE(data->>'refunded', '0.00')::numeric + %s::numeric)::text) WHERE record_id = %s",
                         (pc.amount, pc.record_id))
        for t in self.tools.values():
            t.calls.clear()
            t._results.clear()  # the mock tool's own idempotency memory is per case
        self.clock = 0

    @property
    def executions(self) -> int:
        return len(self.payments.calls) + len(self.refunds.calls)


def _race(calls):
    barrier = threading.Barrier(len(calls))

    def run(fn):
        barrier.wait()
        fn()

    threads = [threading.Thread(target=run, args=(fn,)) for fn in calls]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)


def run_case(env: Env, arm, case: ev.Case) -> CaseResult:
    """Execute every step of `case` against `arm`. A step that blows up is logged as ERROR (an arm outage is raised
    as ArmError and aborts the arm instead)."""
    blobs, entries = ev.materialize_docs(case.setup)
    env.seed(case)
    res = CaseResult(case.id, arm.name)
    state: dict[str, dict] = {}
    lock = threading.Lock()
    committed_from = {s.receipt_from for st in case.steps for s in (st.steps if st.op == "concurrent" else [st])
                      if s.op == "commit"}

    def who(p):
        p = p or case.principal
        return Principal(p.actor, p.on_behalf_of)

    def logged(s, fn):
        t0 = time.perf_counter()
        try:
            out = fn()
        except ArmError:
            raise
        except Exception as e:
            out = Out("ERROR", [type(e).__name__])
        ms = (time.perf_counter() - t0) * 1000 + out.extra_ms
        with lock:
            res.steps.append(StepLog(s.id, s.op, out.outcome, list(out.rules), ms,
                                     bool(out.data and out.data.get("receipt") is not None)))
        return out

    def do_prepare(s):
        wire = ev.resolve_request(s.request, case.principal, entries)
        out = logged(s, lambda: arm.prepare(env, wire, blobs, who(s.principal), defer=s.id in committed_from))
        state[s.id] = {"wire": wire, "out": out}

    def do_commit(s):
        prep = state[s.receipt_from]
        wire = ev.merge_patch(state[s.request_from or s.receipt_from]["wire"], s.request_override or {})
        token = state[s.review_token_from].get("token") if s.review_token_from else None
        redo = lambda: arm.commit(env, prep["out"], wire, token, who(s.principal), s.receipt_override)  # noqa: E731
        state[s.id] = {"redo": redo}
        logged(s, redo)

    def do_mint(s):
        prep = state[s.receipt_from]
        wire = state[s.request_from or s.receipt_from]["wire"]
        box = {}

        def mint():
            box["token"], out = arm.mint(env, prep["out"], wire, s.reviewer_login)
            return out

        logged(s, mint)
        state[s.id] = {"token": box.get("token")}

    run = {"prepare": do_prepare, "commit": do_commit, "mint_token": do_mint}
    real_now = gate_mod._now
    gate_mod._now = lambda: real_now() + env.clock
    try:
        for s in case.steps:
            if s.op in run:
                run[s.op](s)
            elif s.op == "concurrent":
                _race([(lambda st=st: run[st.op](st)) for st in s.steps])
            elif s.op == "replay":
                logged(s, state[s.step]["redo"])
            elif s.op == "mutate_record":
                env.sql("UPDATE records SET data = data || %s, version = COALESCE(%s, version + 1) "
                        "WHERE record_id = %s", (Jsonb(s.set), s.version, s.record_id))
            elif s.op == "set_delegation":
                if s.revoke:
                    env.sql("DELETE FROM delegations WHERE on_behalf_of = %s", (s.on_behalf_of,))
                for col, v in (("max_amount", s.max_amount), ("vendors", s.vendors), ("customers", s.customers)):
                    if v is not None:
                        cast = "::numeric" if col == "max_amount" else ""
                        env.sql(f"UPDATE delegations SET {col} = %s{cast} WHERE on_behalf_of = %s",
                                (v, s.on_behalf_of))
            elif s.op == "advance_clock":
                env.clock += s.seconds
    finally:
        gate_mod._now = real_now
    res.executions = env.executions
    return res


# ---------------------------------------------------------------- standing up a private environment (CLI)
def _dev_database_url() -> str:
    return os.environ.get("DATABASE_URL") or read_dotenv(ROOT / ".env.example")["DATABASE_URL"]


@contextmanager
def provision(opa_bin: str | None = None):
    """A private Postgres database, an OPA server on a free port and a throwaway signing key; yields an Env."""
    import tempfile
    from urllib.parse import urlsplit, urlunsplit

    import httpx
    import psycopg
    from psycopg import sql

    from actionproof import policy, signing

    base = urlsplit(_dev_database_url())
    with_db = lambda n: urlunsplit(base._replace(path=f"/{n}"))  # noqa: E731
    admin = with_db("postgres")
    try:
        psycopg.connect(admin, connect_timeout=3).close()
    except psycopg.OperationalError:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "dev_pg.py"), "start"], check=True)
    name = f"actionproof_eval_{os.getpid()}_{secrets.token_hex(4)}"
    with psycopg.connect(admin, autocommit=True, connect_timeout=5) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = with_db(name)
    tmp = Path(tempfile.mkdtemp(prefix="ap-eval-"))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    opa_log = (tmp / "opa.log").open("wb")
    opa = subprocess.Popen([opa_bin or os.environ.get("OPA_BIN") or read_dotenv(ROOT / ".env.example")["OPA_BIN"],
                            "run", "--server", "--log-level", "error", "--disable-telemetry",
                            "--addr", f"127.0.0.1:{port}", str(ROOT / "policy")], stdout=opa_log,
                           stderr=subprocess.STDOUT)
    env = None
    try:
        opa_url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(f"{opa_url}/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise RuntimeError("OPA did not become healthy")
        with dbmod.connect(url=url) as conn:
            dbmod.apply_schema(conn)
        signing.generate_key(tmp / "eval.key")
        env = Env(url, opa_url, tmp / "eval.key")
        warm = {"tool": INVOICE_TOOL, "actor": "agent-7", "on_behalf_of": "user-123",
                "verify": {"ok": True, "reasons": []},
                "args": {"amount": "4800.00", "variance": "500.00", "vendor_id": "V-ACME"},
                "scope": {"max_amount": "5000.00", "vendors": ["V-ACME"]}, "cumulative": {"committed": "0.00"}}
        refund = {**warm, "tool": REFUND_TOOL, "args": {"amount": "250.00", "customer_id": "CUST-311"},
                  "scope": {"max_amount": "5000.00", "customers": ["CUST-311"]}}
        for inp in (warm, refund):  # compile every rule before the first measured request
            for _ in range(3):
                policy.decide(inp, opa_url, 5)
        yield env
    finally:
        if env is not None:
            env.close()
        opa.kill()
        opa.wait()
        opa_log.close()
        with psycopg.connect(admin, autocommit=True, connect_timeout=5) as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
