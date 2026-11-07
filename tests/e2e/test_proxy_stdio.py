"""Proxy mode over REAL stdio (deck slide 3 step 1: "An MCP proxy sits in front of every tool. Default deny.").

The SDK client spawns `python -m actionproof.server --proxy "<python> examples/mock_upstream_server.py"`; the proxy
spawns the upstream and re-exposes only the tools in examples/proxy-map.json through the gate. The upstream logs
every call it receives (MOCK_UPSTREAM_LOG), so "the upstream saw nothing" is checked on the upstream's side.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
from mcpkit import body

import hero
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = f'"{sys.executable}" "{ROOT / "examples" / "mock_upstream_server.py"}"'
SLIDE_1 = """ACTION INTERCEPTED
action: approve_invoice
amount: 4800.00 [DIRECT ok]
variance: 500.00 [DERIVED ok]
rule: AP-INV-04 (> 100)
decision: REVIEW"""
WRITES = {"approve_invoice", "delete_all_invoices"}


@pytest.fixture
def proxy_env(kit, pg, opa_url, signing_key_path, tmp_path):
    return {
        "DATABASE_URL": pg, "OPA_URL": opa_url, "TESSERACT_CMD": os.environ["TESSERACT_CMD"],
        "SIGNING_KEY_PATH": str(signing_key_path), "OPA_TIMEOUT_SECONDS": "5",
        "ACTIONPROOF_ACTOR": "agent-7", "ACTIONPROOF_ON_BEHALF_OF": "user-123",
        "DOCS_DIR": str(hero.OUT), "PYTHONPATH": str(ROOT / "src"),
        "PROXY_MAP_PATH": str(ROOT / "examples" / "proxy-map.json"),
        "MOCK_UPSTREAM_LOG": str(tmp_path / "upstream.jsonl"), "MOCK_UPSTREAM_MODE": "honest",
    }


def upstream_calls(env, *, writes_only=True) -> list[dict]:
    p = Path(env["MOCK_UPSTREAM_LOG"])
    calls = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []
    return [c for c in calls if c["tool"] in WRITES] if writes_only else calls


def _session(env, steps):
    params = StdioServerParameters(command=sys.executable, args=["-m", "actionproof.server", "--proxy", UPSTREAM],
                                   env=env, cwd=str(ROOT))

    async def go():
        async with Client(params, read_timeout_seconds=120) as c:
            return await steps(c)

    return anyio.run(go)


def test_proxy_review_unmapped_deny_allow(kit, proxy_env):
    async def steps(c):
        names = sorted(t.name for t in (await c.list_tools()).tools)
        review = await c.call_tool("approve_invoice", body(kit.hero()[0]))
        unmapped = await c.call_tool("delete_all_invoices", {})
        reads = await c.call_tool("get_record", {"record_id": "invoice:INV-2048"})
        after_refusals = upstream_calls(proxy_env, writes_only=False)
        d = body(kit.hero("idem-4900")[0])
        d["args"]["amount"]["value"] = "4900.00"
        deny = await c.call_tool("approve_invoice", d)
        writes_after_deny = upstream_calls(proxy_env)
        allow = await c.call_tool("approve_invoice", body(kit.hero_allow()[0]))
        return names, review, unmapped, reads, after_refusals, deny, writes_after_deny, allow

    names, review, unmapped, reads, after_refusals, deny, writes_after_deny, allow = _session(proxy_env, steps)
    # Default deny: only mapped upstream tools are listed; the dangerous one and the read helpers are not.
    assert names == ["approve_invoice", "extract_fields", "review_status"]

    assert review.content[0].text == SLIDE_1  # the slide-1 card, through the proxy
    assert review.structured_content["status"] == "pending"

    for r in (unmapped, reads):  # unmapped upstream tools: refused + audited, never forwarded
        assert r.is_error and r.structured_content["error"]["code"] == "unknown_tool"
    assert [c for c in after_refusals if c["tool"] in ("delete_all_invoices",)] == []
    assert kit.sql("SELECT count(*) FROM audit_log WHERE kind = 'refuse'") == [(2,)]

    assert deny.structured_content["decision"] == "DENY"
    assert {x["rule"] for x in deny.structured_content["reasons"]} == {"AP-VER-01"}
    assert writes_after_deny == []  # DENY never reaches the upstream's write tool

    a = allow.structured_content
    assert a["decision"] == "ALLOW" and a["status"] == "executed", a
    calls = upstream_calls(proxy_env)
    assert [c["tool"] for c in calls] == ["approve_invoice"]  # exactly once
    assert calls[0]["arguments"] == {"invoice_id": "INV-2048", "amount": "4800.00", "idempotency_key": "idem-allow"}
    assert kit.sql("SELECT data->>'status' FROM records WHERE record_id = 'invoice:INV-2048'") == [("approved",)]
    assert kit.executes == 0  # the in-process mock never ran: the effect came from the upstream


@pytest.mark.parametrize("mode", ["crash", "hang"])
def test_upstream_failure_fails_closed(kit, proxy_env, tmp_path, mode):
    proxy_env["MOCK_UPSTREAM_MODE"] = mode
    if mode == "hang":  # a 2 s budget instead of the example map's 10 s
        m = json.loads((ROOT / "examples" / "proxy-map.json").read_text(encoding="utf-8"))
        m["timeout_seconds"] = 2
        (tmp_path / "map.json").write_text(json.dumps(m), encoding="utf-8")
        proxy_env["PROXY_MAP_PATH"] = str(tmp_path / "map.json")

    async def steps(c):
        return (await c.call_tool("approve_invoice", body(kit.hero_allow()[0]))).structured_content

    s = _session(proxy_env, steps)
    assert s["decision"] == "DENY" and s["status"] == "denied"
    assert s["reasons"][0]["rule"] == "AP-ERR-11" and s["reasons"][0]["guarantee"] == "G1"
    assert kit.sql("SELECT data->>'status' FROM records WHERE record_id = 'invoice:INV-2048'") == [("open",)]
    assert kit.sql("SELECT count(*) FROM quarantine") == [(1,)]  # unknown outcome: reconcile before any retry


def test_hostile_upstream_double_apply_is_denied(kit, proxy_env):
    proxy_env["MOCK_UPSTREAM_MODE"] = "double"

    async def steps(c):
        return (await c.call_tool("approve_invoice", body(kit.hero_allow()[0]))).structured_content

    s = _session(proxy_env, steps)
    assert s["decision"] == "DENY" and s["reasons"][0]["rule"] == "AP-STALE-07"
    assert kit.sql("SELECT data->>'status' FROM records WHERE record_id = 'invoice:INV-2048'") == [("open",)]
    assert kit.sql("SELECT count(*) FROM quarantine") == [(1,)]


def test_proxy_map_errors_abort_startup(proxy_env, tmp_path):
    bad = tmp_path / "bad.json"
    cases = {
        "missing": None,
        "not json": "{",
        "unknown action": {"tools": {"approve_invoice": {"action": "payments.wire_money", "args": {}}}},
        "not offered": {"tools": {"pay_everything": {"action": "payments.approve_invoice",
                                                     "args": {"invoice_id": "invoice_id", "amount": "amount"}}}},
    }
    for name, content in cases.items():
        if content is None:
            path = tmp_path / "nope.json"
        else:
            bad.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
            path = bad
        env = {**os.environ, **proxy_env, "PROXY_MAP_PATH": str(path)}
        p = subprocess.run([sys.executable, "-m", "actionproof.server", "--proxy", UPSTREAM], env=env, cwd=str(ROOT),
                           input=b"", capture_output=True, timeout=90)
        assert p.returncode == 2, (name, p.stderr)
        assert b"ConfigError" in p.stderr and b"PROXY_MAP_PATH" in p.stderr, (name, p.stderr)
    assert upstream_calls(proxy_env, writes_only=False) == []
