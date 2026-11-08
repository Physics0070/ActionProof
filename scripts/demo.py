"""ActionProof demo driver (docs/DEMO.md): plays every beat in order against the REAL gate and prints its output.

    bash demo.sh                      # or: python scripts/demo.py
    DEMO_PAUSE=1 bash demo.sh         # wait for Enter between beats (recording)
    DEMO_ASCII=1 / NO_COLOR=1         # plain output

Beat 1 runs the honest INV-2048 over the real MCP stdio client (python -m actionproof.server --stdio), then the
reviewer rev-alice completes the review (review.complete_review, the console's call). Beats 2-5 are driven the same
way (agent calls over MCP; the commit lane, the human side and the audit verifier in-process, as the tests do).
Exit 0 only if every beat produced its expected outcome, else FAIL lines and exit 1.

Isolation: everything runs in a DEDICATED database (DEMO_DB, default actionproof_demo) on the server named by
DATABASE_URL, reset on every run with scripts/demo_seed.py semantics. Shared/dev data is never touched.
Env (invariant 7, no hardcoded config): DATABASE_URL, OPA_URL, OPA_BIN, TESSERACT_CMD, SIGNING_KEY_PATH (optional;
a throwaway key is generated if unset), DEMO_DB, DEMO_DROP=1 (drop the demo DB afterwards), DEMO_PAUSE, DEMO_ASCII.
"""
import contextlib
import importlib.util
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "fixtures")]

import anyio  # noqa: E402
import anyio.from_thread  # noqa: E402
import httpx  # noqa: E402
import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

import hero  # noqa: E402
from actionproof import audit, db, review, server, signing  # noqa: E402
from actionproof.config import load_settings  # noqa: E402
from actionproof.contracts import ActionRequest  # noqa: E402
from actionproof.gate import Principal  # noqa: E402
from mcp import Client, StdioServerParameters  # noqa: E402

AGENT7, AGENT8 = Principal("agent-7", "user-123"), Principal("agent-8", "user-123")
SLIDE_1 = """ACTION INTERCEPTED
action: approve_invoice
amount: 4800.00 [DIRECT ok]
variance: 500.00 [DERIVED ok]
rule: AP-INV-04 (> 100)
decision: REVIEW"""
USP = "Proof before permission."

for _s in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _s.reconfigure(encoding="utf-8", errors="replace")
UNICODE = (sys.stdout.encoding or "").lower().replace("-", "") == "utf8" and not os.environ.get("DEMO_ASCII")
COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR") and not os.environ.get("DEMO_ASCII")
DOT = "·" if UNICODE else "|"


def c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if COLOR else s


class Ctx:
    results: list[tuple[str, str, bool]] = []  # (beat, outcome, ok)
    failures = 0
    beat = ""


def say(s: str = "") -> None:
    print(s, flush=True)


def banner(text: str) -> None:
    bar = "=" * 74
    say(c("1;36", bar))
    say(c("1;36", f"  {text}"))
    say(c("1;36", bar))


def section(n: str, title: str, sub: str) -> None:
    pause()
    Ctx.beat = n
    say()
    say(c("1;33", f"--- BEAT {n}: {title} " + "-" * max(2, 62 - len(title) - len(n))))
    say(c("2", f"    {sub}"))


def pause() -> None:
    if os.environ.get("DEMO_PAUSE", "") not in ("", "0"):
        if sys.stdin and sys.stdin.isatty():
            input(c("2", "    [enter] "))
        else:
            time.sleep(2)


def card(text: str) -> None:
    lines = text.splitlines()
    w = max(len(x) for x in lines) + 2
    say("    +" + "-" * w + "+")
    for ln in lines:
        say("    | " + c("1", ln.ljust(w - 1)) + "|")
    say("    +" + "-" * w + "+")


def rule_of(r) -> tuple[str, str]:
    return (r["rule"], r["guarantee"]) if isinstance(r, dict) else (r.rule, r.guarantee)


def msg_of(r) -> str:
    return r["msg"] if isinstance(r, dict) else r.msg


def show_reasons(reasons) -> None:
    for r in reasons:
        rule, g = rule_of(r)
        say(f"    reason: {c('1;31', rule)} ({c('1;35', g)})  {msg_of(r)}")


def expect(outcome: str, ok: bool, detail: str = "") -> bool:
    Ctx.results.append((Ctx.beat, outcome, bool(ok)))
    if ok:
        say(f"    {c('1;32', '[ OK ]')} {outcome}")
    else:
        Ctx.failures += 1
        say(f"    {c('1;31', '[FAIL]')} expected: {outcome}" + (f"   ({detail})" if detail else ""))
    return bool(ok)


def pairs(reasons) -> list[tuple[str, str]]:
    return [rule_of(r) for r in reasons]


# ---------------------------------------------------------------------------------------------------- services

def _env_default(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        k, sep, v = line.partition("=")
        if sep and k.strip() == name:
            return v.strip() or None
    return None


def ensure_database() -> tuple[str, str, str]:
    """Create (if missing) the dedicated demo database; return (its DSN, the admin DSN, its name). Starts the local dev Postgres if
    the server in DATABASE_URL is not reachable."""
    base = urlsplit(_env_default("DATABASE_URL") or "")
    if not base.scheme:
        raise SystemExit("DATABASE_URL is not set (and not in .env.example)")
    admin = urlunsplit(base._replace(path="/postgres"))
    try:
        psycopg.connect(admin, connect_timeout=3).close()
    except psycopg.OperationalError:
        say(c("2", "    postgres not reachable: starting the local dev cluster (scripts/dev_pg.py start)"))
        subprocess.run([sys.executable, str(ROOT / "scripts" / "dev_pg.py"), "start"], check=True,
                       stdout=subprocess.DEVNULL)
    name = os.environ.get("DEMO_DB") or "actionproof_demo"
    with psycopg.connect(admin, autocommit=True, connect_timeout=5) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return urlunsplit(base._replace(path=f"/{name}")), admin, name


def ensure_opa(tmp: Path) -> tuple[str, subprocess.Popen | None]:
    """Return (OPA_URL, process we started or None)."""
    url = _env_default("OPA_URL") or "http://localhost:8181"

    def healthy() -> bool:
        try:
            return httpx.get(f"{url}/health", timeout=1).status_code == 200
        except httpx.HTTPError:
            return False

    if healthy():
        return url, None
    parts = urlsplit(url)
    if parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise SystemExit(f"OPA at {url} is not reachable and is not local: cannot start it")
    opa_bin = os.environ.get("OPA_BIN") or _env_default("OPA_BIN") or shutil.which("opa") or "opa"
    port = parts.port or 8181
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:  # port taken by something that is not a healthy OPA
            s2 = socket.socket()
            s2.bind(("127.0.0.1", 0))
            port = s2.getsockname()[1]
            s2.close()
    url = f"http://127.0.0.1:{port}"
    say(c("2", f"    OPA not reachable: starting {Path(opa_bin).name} on {url} (policy/)"))
    log = (tmp / "opa.log").open("wb")
    proc = subprocess.Popen([opa_bin, "run", "--server", "--log-level", "error", "--disable-telemetry",
                             "--addr", f"127.0.0.1:{port}", str(ROOT / "policy")], stdout=log, stderr=subprocess.STDOUT)
    for _ in range(100):
        if proc.poll() is not None:
            raise SystemExit(f"OPA exited: {(tmp / 'opa.log').read_text(errors='replace')[:300]}")
        if healthy():
            return url, proc
        time.sleep(0.1)
    proc.kill()
    raise SystemExit("OPA did not become healthy")


def load_demo_seed():
    spec = importlib.util.spec_from_file_location("demo_seed", ROOT / "scripts" / "demo_seed.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------------------------------- MCP client

class McpAgent:
    """One agent session over the REAL MCP stdio client; the operator-assigned Principal comes from the env."""

    def __init__(self, env: dict, principal: Principal):
        e = {**env, "ACTIONPROOF_ACTOR": principal.actor, "ACTIONPROOF_ON_BEHALF_OF": principal.on_behalf_of}
        self._params = StdioServerParameters(command=sys.executable, args=["-m", "actionproof.server", "--stdio"],
                                             env=e, cwd=str(ROOT))

    def __enter__(self):
        self._cm = anyio.from_thread.start_blocking_portal()
        self._portal = self._cm.__enter__()
        self._client_cm = self._portal.wrap_async_context_manager(Client(self._params, read_timeout_seconds=120))
        self._client = self._client_cm.__enter__()
        return self

    def __exit__(self, *exc):
        try:
            self._client_cm.__exit__(*exc)
        finally:
            self._cm.__exit__(*exc)

    def call(self, name: str, args: dict) -> dict:
        r = self._portal.call(self._client.call_tool, name, args)
        return {"text": r.content[0].text if r.content else "", "s": r.structured_content or {},
                "is_error": r.is_error}


def body(req) -> dict:
    return req if isinstance(req, dict) else req.model_dump(mode="json")


# ---------------------------------------------------------------------------------------------------- data helpers

def sql_one(factory, q: str, params=()):
    with factory() as conn:
        row = conn.execute(q, params).fetchone()
        return row[0] if row else None


def seed_invoice(factory, invoice_id: str, total: str, po_total: str, vendor: str) -> None:
    po_id = f"PO-{invoice_id}"
    with factory() as conn:
        conn.execute("INSERT INTO records (record_id, kind, data, version) VALUES (%s, 'invoice', %s, 1) "
                     "ON CONFLICT (record_id) DO UPDATE SET data = EXCLUDED.data, version = 1",
                     (f"invoice:{invoice_id}", Jsonb({"vendor_id": vendor, "total": total, "status": "open",
                                                      "po_id": po_id})))
        conn.execute("INSERT INTO records (record_id, kind, data, version) VALUES (%s, 'po', %s, 1) "
                     "ON CONFLICT (record_id) DO UPDATE SET data = EXCLUDED.data, version = 1",
                     (f"po:{po_id}", Jsonb({"vendor_id": vendor, "total": po_total})))
        conn.commit()


def json_invoice(factory, invoice_id: str, total: str, po_total: str, vendor: str, idem: str,
                 principal: Principal = AGENT7) -> tuple[ActionRequest, dict]:
    """A JSON-export invoice request (cheap: no OCR) against a freshly seeded invoice + PO."""
    import hashlib
    from decimal import Decimal
    seed_invoice(factory, invoice_id, total, po_total, vendor)
    doc_id = f"export-{invoice_id}.json"
    blob = json.dumps({"invoice_id": invoice_id, "total": total}, sort_keys=True).encode()
    sha = hashlib.sha256(blob).hexdigest()

    def claim(key, value):
        return {"value": value, "claim": "DIRECT", "src": {"doc": doc_id, "pointer": f"/{key}"}, "doc_sha256": sha}

    var = str((Decimal(total) - Decimal(po_total)).quantize(Decimal("0.01")))
    req = ActionRequest.model_validate({
        "tool": "payments.approve_invoice", "on_behalf_of": principal.on_behalf_of, "actor": principal.actor,
        "idempotency_key": idem,
        "args": {"invoice_id": claim("invoice_id", invoice_id), "amount": claim("total", total),
                 "invoice.total": claim("total", total),
                 "variance": {"value": var, "claim": "DERIVED", "fn": "sub", "inputs": ["invoice.total", "po.total"]}}})
    return req, {doc_id: blob}


def race(*calls):
    barrier = threading.Barrier(len(calls))
    out = [None] * len(calls)

    def run(i, fn):
        barrier.wait()
        try:
            out[i] = fn()
        except BaseException as e:  # noqa: BLE001 - surfaced as a failed beat, never swallowed
            out[i] = e

    ts = [threading.Thread(target=run, args=(i, f)) for i, f in enumerate(calls)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    return out


def committed(factory, counterparty: str) -> str:
    return sql_one(factory, "SELECT COALESCE(SUM(amount), 0)::text FROM commits WHERE vendor_id = %s", (counterparty,))


def n_commits(factory) -> int:
    return sql_one(factory, "SELECT count(*) FROM commits")


# ---------------------------------------------------------------------------------------------------- the beats

def beat1(agent, gate, factory) -> str:
    section("1", "Honest INV-2048 -> REVIEW -> a different person approves -> executed once",
            "real MCP stdio client; the card is the deck's slide 1, byte for byte")
    inv = hero.MANIFEST["hero"]["invoice"]
    fields = agent.call("extract_fields", {"doc_id": inv})["s"]
    line = next((ln for ln in fields.get("lines", []) if "4,800.00" in ln["text"]), None)
    f = hero.MANIFEST["docs"][inv]["fields"]["total"]
    say(f"    agent reads {inv}: line {line['text']!r} at page {line['page']}" if line else "    (no total line)")
    say(f"    source span the console highlights for amount: doc={inv} page={f['page']} bbox={f['bbox']}")
    expect("extract_fields returns the cited span (page 1, bbox)", line is not None and line["page"] == f["page"])

    base = n_commits(factory)
    req = hero.hero_request("demo-hero")
    r = agent.call("payments_approve_invoice", body(req))
    s = r["s"]
    say("    agent -> payments_approve_invoice(INV-2048)   gate says:")
    card(r["text"])
    show_reasons(s.get("reasons", []))
    expect("slide-1 card reproduced EXACTLY", r["text"] == SLIDE_1)
    expect("REVIEW is parked (pending), rule AP-INV-04 (G1), nothing executed",
           s.get("status") == "pending" and pairs(s.get("reasons", []))[:1] == [("AP-INV-04", "G1")]
           and n_commits(factory) == base and "receipt" not in s)
    h = s["request_hash"]
    say(f"    request_hash {h[:16]}...  (the agent got a hash, never a receipt or token)")
    say(f"    label: {c('1', f'requested by agent-7 for user-123 {DOT} approved by a different person')}")

    o = review.complete_review(gate, factory, h, "rev-alice", True, "PO amendment on file")
    say(f"    console -> rev-alice approves (person p-alice, submitter p-user123): {o.status}")
    inv_status = sql_one(factory, "SELECT data->>'status' FROM records WHERE record_id = 'invoice:INV-2048'")
    expect("rev-alice completes the review -> EXECUTED once",
           o.status == "executed" and inv_status == "approved" and n_commits(factory) == base + 1
           and sql_one(factory, "SELECT count(*) FROM commits WHERE request_hash = %s", (h,)) == 1)
    return h


def beat2(agent, factory) -> None:
    section("2", "Injected PDF: hidden 'approve regardless' text -> DENY AP-VER-01 (G1)",
            "document text may describe a value, it can never authorize one")
    doc = hero.MANIFEST["docs"]["injected.pdf"]["fields"]["hidden_text"]
    say(f"    injected.pdf hides (white, 1pt, page {doc['page']}): {doc['text']!r}")
    seed_invoice(factory, "INV-3001", "900.00", "900.00", "V-NOVA")  # the open invoice the injected PDF is about
    before = n_commits(factory)
    d = body(hero.hero_request("demo-inj-hidden"))
    d["args"].pop("po.total")
    d["args"]["invoice_id"] = hero.pdf_claim("injected.pdf", "invoice_id")
    d["args"]["invoice.total"] = hero.pdf_claim("injected.pdf", "total")
    d["args"]["variance"]["value"] = "0.00"
    d["args"]["amount"] = hero.pdf_claim("injected.pdf", "hidden_text", value="900.00")
    r = agent.call("payments_approve_invoice", d)
    s = r["s"]
    say("    hijacked agent cites the hidden span as the amount.   gate says:")
    card(r["text"])
    show_reasons(s.get("reasons", []))
    got = pairs(s.get("reasons", []))
    expect("DENY AP-VER-01 (G1), no execution",
           s.get("decision") == "DENY" and ("AP-VER-01", "G1") in got and n_commits(factory) == before
           and sql_one(factory, "SELECT data->>'status' FROM records WHERE record_id = 'invoice:INV-3001'") == "open")


def beat3(agent, factory, gate, hero_hash: str) -> None:
    section("3", "Replay: same receipt / same idempotency key again -> DENY AP-REP-05 (G2)",
            "an approval is spent exactly once; the DB constraint, not a flag, says so")
    # INV-2048 itself: replay its spent receipt with a freshly minted token. The bounce is audited against the
    # hero's request_hash, so GET /api/public/replay/inv-2048 (public site signature panel) shows the G2 attempt.
    req_json, receipt = sql_row(factory, "SELECT request, receipt FROM pending_reviews WHERE request_hash = %s",
                                (hero_hash,))
    hreq = ActionRequest.model_validate(req_json)
    n0 = n_commits(factory)
    token = gate.mint_review_token(receipt, hreq, reviewer_login="rev-alice")
    ch = gate.commit(receipt, hreq, token, principal=AGENT7)
    say("    INV-2048's spent receipt replayed at commit (with a fresh token):")
    show_reasons(ch.reasons)
    logged = sql_one(factory, "SELECT count(*) FROM audit_log WHERE request_hash = %s AND kind = 'commit' "
                              "AND decision = 'DENY' AND rules @> '[{\"rule\": \"AP-REP-05\", \"guarantee\": \"G2\"}]'",
                     (hero_hash,))
    say(f"    recorded in the audit chain against INV-2048's request_hash: {logged} replay attempt(s)")
    expect("INV-2048 replay -> DENY AP-REP-05 (G2), audited, executed once only",
           ch.outcome == "DENY" and pairs(ch.reasons) == [("AP-REP-05", "G2")] and logged >= 1
           and n_commits(factory) == n0)
    say()
    req, docs = json_invoice(factory, "INV-3101", "1000.00", "1000.00", "V-ZETA", "demo-replay")
    p = gate.prepare(req, docs, principal=AGENT7)
    c1 = gate.commit(p.receipt, req, principal=AGENT7)
    after = n_commits(factory)
    say(f"    invoice INV-3101 (1000.00, in policy): prepare {p.decision}, commit {c1.outcome}")
    c2 = gate.commit(p.receipt, req, principal=AGENT7)
    say("    the SAME signed receipt replayed at commit:")
    show_reasons(c2.reasons)
    expect("replayed receipt -> DENY AP-REP-05 (G2), tool not reached again",
           c1.outcome == "EXECUTED" and c2.outcome == "DENY" and pairs(c2.reasons) == [("AP-REP-05", "G2")]
           and n_commits(factory) == after)
    p2 = gate.prepare(req, docs, principal=AGENT7)  # same idempotency key
    say("    the SAME idempotency key re-prepared:")
    show_reasons(p2.reasons)
    expect("replayed idempotency key -> DENY (G2: the record is already actioned), no new receipt",
           p2.decision == "DENY" and p2.receipt is None and all(g == "G2" for _, g in pairs(p2.reasons)))
    r = agent.call("payments_approve_invoice", body(hero.hero_request("demo-hero")))
    say("    and the executed INV-2048 re-sent by the agent over MCP (record no longer open):")
    show_reasons(r["s"].get("reasons", []))
    expect("re-sent executed INV-2048 -> DENY (G2), nothing executes",
           r["s"].get("decision") == "DENY" and all(g == "G2" for _, g in pairs(r["s"].get("reasons", [])))
           and n_commits(factory) == after)


def sql_row(factory, q: str, params=()):
    with factory() as conn:
        return conn.execute(q, params).fetchone()


def beat4(gate, factory) -> None:
    section("4", "Two concurrent $4,900 approvals -> exactly one executes, the other DENY AP-CUM-03",
            "cap 5000.00 per person+vendor; authoritative inside the SERIALIZABLE commit transaction")
    a, da = json_invoice(factory, "INV-4001", "4900.00", "4900.00", "V-BETA", "demo-cc-a")
    b, db_ = json_invoice(factory, "INV-4002", "4900.00", "4900.00", "V-BETA", "demo-cc-b")
    pa, pb = gate.prepare(a, da, principal=AGENT7), gate.prepare(b, db_, principal=AGENT7)
    say(f"    both prepared while nothing is committed: {pa.decision} / {pb.decision}  (each alone is under the cap)")
    out = race(lambda: gate.commit(pa.receipt, a, principal=AGENT7), lambda: gate.commit(pb.receipt, b, principal=AGENT7))
    if any(isinstance(o, BaseException) for o in out):
        expect("two racing commits complete", False, repr(out))
        return
    loser = next((i for i, o in enumerate(out) if o.outcome == "DENY"), None)
    if loser is not None and pairs(out[loser].reasons) == [("AP-ERR-11", "G1")]:  # serialization failure: retry once
        say("    serialization failure on the loser (fail closed); retrying it once sequentially")
        pr, rq = (pa, a) if loser == 0 else (pb, b)
        out[loser] = gate.commit(pr.receipt, rq, principal=AGENT7)
    for name, o in zip(("approval A", "approval B"), out):
        say(f"    {name}: {c('1;32', o.outcome) if o.outcome == 'EXECUTED' else c('1;31', o.outcome)}")
        show_reasons(o.reasons)
    denied = [o for o in out if o.outcome == "DENY"]
    tot = committed(factory, "V-BETA")
    say(f"    committed for V-BETA: {tot}   (cap 5000.00)")
    expect("exactly one EXECUTED, the other DENY AP-CUM-03 (G1)",
           sorted(o.outcome for o in out) == ["DENY", "EXECUTED"] and len(denied) == 1
           and pairs(denied[0].reasons) == [("AP-CUM-03", "G1")] and tot == "4900.00")

    say()
    say(c("1", "    actor rotation: agent-8 is the same person (p-user123) as agent-7"))
    x, dx = json_invoice(factory, "INV-4003", "4900.00", "4900.00", "V-GAMMA", "demo-rot-a")
    y, dy = json_invoice(factory, "INV-4004", "4900.00", "4900.00", "V-GAMMA", "demo-rot-b", AGENT8)
    px = gate.prepare(x, dx, principal=AGENT7)
    cx = gate.commit(px.receipt, x, principal=AGENT7)
    py = gate.prepare(y, dy, principal=AGENT8)
    say(f"    agent-7 spends 4900.00 on V-GAMMA: {cx.outcome};  agent-8 tries 4900.00 on V-GAMMA: {py.decision}")
    show_reasons(py.reasons)
    expect("rotated agent (same person) -> DENY AP-CUM-03 (G1), person cap (ADR-016)",
           cx.outcome == "EXECUTED" and py.decision == "DENY" and pairs(py.reasons) == [("AP-CUM-03", "G1")]
           and py.receipt is None and committed(factory, "V-GAMMA") == "4900.00")


def beat5(agent, gate, factory) -> None:
    section("5", "Second connector: payments.refund_payment through the SAME gate",
            "refund destination is an authority field: only the system of record may fill it")
    inj = hero.MANIFEST["docs"][hero.REFUND_INJECTED]["fields"]["injected_text"]
    say(f"    REF-311.pdf shows (visible, page {inj['page']}, bbox {inj['bbox']}):")
    say(f"      {c('1;31', repr(inj['text']))}")
    before = n_commits(factory)
    r = agent.call("payments_refund_payment",
                   body(hero.refund_request(hero.REFUND_INJECTED, "demo-ref-inj", refund_to=hero.injected_refund_to())))
    s = r["s"]
    say("    hijacked agent fills refund_to from that line.   gate says:")
    card(r["text"])
    show_reasons(s.get("reasons", []))
    taint = [x for x in s.get("reasons", []) if rule_of(x) == ("AP-VER-01", "G1") and msg_of(x).startswith("refund_to:")]
    expect("injected REF-311 -> DENY AP-VER-01 (G1) on refund_to (taint), no execution",
           s.get("decision") == "DENY" and bool(taint) and n_commits(factory) == before)

    say()
    r = agent.call("payments_refund_payment", body(hero.refund_request(hero.REFUND_CLEAN, "demo-ref-clean")))
    s = r["s"]
    say(f"    clean retry (destination from the system of record, 250.00): committed so far 4800.00 -> 5050.00")
    card(r["text"])
    show_reasons(s.get("reasons", []))
    expect("clean 250.00 retry -> DENY AP-CUM-03 (G1): 4800 + 250 > 5000",
           s.get("decision") == "DENY" and pairs(s.get("reasons", [])) == [("AP-CUM-03", "G1")]
           and n_commits(factory) == before)

    say()
    r = agent.call("payments_refund_payment", body(hero.refund_request(hero.REFUND_SMALL, "demo-ref-small")))
    s = r["s"]
    say("    small clean refund (150.00, back to the original method):")
    card(r["text"])
    refunded = committed(factory, "CUST-311")
    expect("small clean refund executes once (4800.00 + 150.00 = 4950.00 committed)",
           s.get("status") == "executed" and refunded == "4950.00" and n_commits(factory) == before + 1,
           f"status={s.get('status')} committed={refunded}")

    say()
    say(c("1", "    reviewer self-approval: rev-user123 is a SECOND LOGIN of the person who submitted"))
    with factory() as conn:
        conn.execute("INSERT INTO people (login, person_id, roles) VALUES ('rev-user123', 'p-user123', "
                     "ARRAY['reviewer']) ON CONFLICT (login) DO NOTHING")
        conn.commit()
    req, docs = json_invoice(factory, "INV-5001", "1500.00", "1200.00", "V-DELTA", "demo-self")
    p = gate.prepare(req, docs, principal=AGENT7)
    if p.decision != "REVIEW":
        expect("a REVIEW request exists for the self-approval attempt", False, p.decision)
        return
    review.park(factory, req, p.receipt, p.reasons, p)
    h = p.receipt["payload"]["request_hash"]
    o = review.complete_review(gate, factory, h, "rev-user123", True, "approving my own request")
    say("    rev-user123 tries to approve it:")
    show_reasons(o.reasons)
    expect("self-approval -> DENY AP-SEP-12 (G2), review stays pending, nothing executed",
           o.status == "pending" and pairs(o.reasons) == [("AP-SEP-12", "G2")]
           and sql_one(factory, "SELECT count(*) FROM commits WHERE request_hash = %s", (h,)) == 0)


def beat_audit(url: str, pub: str) -> None:
    section("6", "The audit chain verifies", "hash chain + Ed25519 checkpoints over every decision above")
    code, line = audit.run_verify(url, pub)
    say(f"    {c('1', line)}")
    expect("audit verifier prints 'audit: OK (n entries, m checkpoints)'", code == 0 and line.startswith("audit: OK ("))


def summary() -> None:
    say()
    banner("RESULT")
    for beat, outcome, ok in Ctx.results:
        say(f"  {c('1;32', 'ok  ') if ok else c('1;31', 'FAIL')}  beat {beat}  {outcome}")


# ---------------------------------------------------------------------------------------------------- main

def main() -> int:
    banner(f"ActionProof  -  {USP}")
    say("  No value can authorize a write unless its derivation re-checks (G1);")
    say("  no approval can be replayed (G2).")
    tmp = Path(tempfile.mkdtemp(prefix="actionproof-demo-"))
    opa_proc = None
    admin = name = None
    try:
        url, admin, name = ensure_database()
        opa_url, opa_proc = ensure_opa(tmp)
        key = os.environ.get("SIGNING_KEY_PATH")
        if not key or not Path(key).is_file():
            key = str(tmp / "demo.key")
            signing.generate_key(key)
        tess = _env_default("TESSERACT_CMD")
        env = {**os.environ, "DATABASE_URL": url, "OPA_URL": opa_url, "SIGNING_KEY_PATH": key,
               "TESSERACT_CMD": tess or "tesseract", "DOCS_DIR": str(hero.OUT),
               "OPA_TIMEOUT_SECONDS": os.environ.get("OPA_TIMEOUT_SECONDS", "5"), "PYTHONPATH": str(ROOT / "src")}
        os.environ.update({k: env[k] for k in ("DATABASE_URL", "OPA_URL", "SIGNING_KEY_PATH", "TESSERACT_CMD",
                                                "DOCS_DIR", "OPA_TIMEOUT_SECONDS")})
        pub = signing.Signer.from_path(key, env.get("SIGNING_KID", "k1")).public_key_b64()

        with db.connect(url=url) as conn:  # scripts/demo_seed.py --reset semantics, on the demo database only
            load_demo_seed().seed(conn, reset=True)
            conn.execute("UPDATE delegations SET vendors = %s WHERE on_behalf_of = 'user-123'",
                         (["V-ACME", "V-BETA", "V-GAMMA", "V-DELTA", "V-NOVA", "V-ZETA"],))
            conn.execute("INSERT INTO people (login, person_id, roles) VALUES ('agent-8', 'p-user123', "
                         "ARRAY['agent']) ON CONFLICT (login) DO NOTHING")
            conn.commit()
        say(c("2", f"  demo database: {name} (reset)   OPA: {opa_url}   signing key: throwaway/{Path(key).name}"))

        settings = load_settings(env)
        app = server.build_app(settings, server.load_server_settings(env, need_principal=False))
        gate, factory = app.gate, app._conn_factory

        with McpAgent(env, AGENT7) as agent:
            hero_hash = beat1(agent, gate, factory)
            beat2(agent, factory)
            beat3(agent, factory, gate, hero_hash)
            beat4(gate, factory)
            beat5(agent, gate, factory)
        beat_audit(url, pub)
        summary()
        say()
        if Ctx.failures:
            say(c("1;31", f"FAIL: {Ctx.failures} expected outcome(s) not produced"))
        else:
            say(c("1;32", "PASS: every beat produced its expected outcome"))
        banner(USP)
        return 1 if Ctx.failures else 0
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        say(c("1;31", f"FAIL: demo aborted ({type(e).__name__}: {e})"))
        return 1
    finally:
        if opa_proc is not None:
            opa_proc.kill()
            opa_proc.wait()
        if os.environ.get("DEMO_DROP") == "1" and name:
            with contextlib.suppress(Exception), psycopg.connect(admin, autocommit=True, connect_timeout=5) as conn:
                conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
