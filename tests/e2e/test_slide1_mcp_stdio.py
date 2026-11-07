"""Deck slide 1 over a REAL MCP stdio session (S1.1, S3.2, S7.1): the SDK client spawns
`python -m actionproof.server --stdio` as a subprocess against this session's private test database.
The human side (complete_review) runs in-process with the same key and database, as the console will."""
import json
import os
import subprocess
import sys
from pathlib import Path

import anyio
import pytest
from mcpkit import body

import hero
from actionproof import review
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[2]
SLIDE_1 = """ACTION INTERCEPTED
action: approve_invoice
amount: 4800.00 [DIRECT ok]
variance: 500.00 [DERIVED ok]
rule: AP-INV-04 (> 100)
decision: REVIEW"""


@pytest.fixture
def server_env(kit, pg, opa_url, signing_key_path):
    return {
        "DATABASE_URL": pg, "OPA_URL": opa_url, "TESSERACT_CMD": os.environ["TESSERACT_CMD"],
        "SIGNING_KEY_PATH": str(signing_key_path), "OPA_TIMEOUT_SECONDS": "5",
        "ACTIONPROOF_ACTOR": "agent-7", "ACTIONPROOF_ON_BEHALF_OF": "user-123",
        "DOCS_DIR": str(hero.OUT), "PYTHONPATH": str(ROOT / "src"),
    }


def _session(env, steps):
    params = StdioServerParameters(command=sys.executable, args=["-m", "actionproof.server", "--stdio"],
                                   env=env, cwd=str(ROOT))

    async def go():
        async with Client(params, read_timeout_seconds=120) as c:
            return await steps(c)

    return anyio.run(go)


def test_slide1_exact_then_review_then_status(kit, server_env):
    async def steps(c):
        names = sorted(t.name for t in (await c.list_tools()).tools)
        r = await c.call_tool("payments_approve_invoice", body(kit.hero()[0]))
        d = body(kit.hero("idem-4900")[0])
        d["args"]["amount"]["value"] = "4900.00"
        bad = await c.call_tool("payments_approve_invoice", d)
        unknown = await c.call_tool("shell_exec", {"cmd": "rm -rf /"})
        return names, r, bad, unknown

    names, r, bad, unknown = _session(server_env, steps)
    assert names == ["extract_fields", "payments_approve_invoice", "payments_refund_payment", "review_status"]
    assert r.content[0].text == SLIDE_1  # the deck text, byte for byte, over MCP stdio
    s = r.structured_content
    assert s["status"] == "pending" and s["reasons"][0]["rule"] == "AP-INV-04" and "receipt" not in s

    b = bad.structured_content
    assert b["decision"] == "DENY" and {x["rule"] for x in b["reasons"]} == {"AP-VER-01"}
    assert all(x["guarantee"] == "G1" for x in b["reasons"])
    assert "amount: 4900.00 [DIRECT FAILED]" in bad.content[0].text
    assert kit.executes == 0 and kit.tool.calls == [] and kit.commits() == 0  # tool calls 0

    assert unknown.is_error and unknown.structured_content["error"]["code"] == "unknown_tool"
    assert kit.sql("SELECT count(*) FROM audit_log WHERE kind = 'refuse'") == [(1,)]

    o = review.complete_review(kit.gate, kit.factory, s["request_hash"], "rev-alice", True, "PO amendment on file")
    assert o.status == "executed"
    assert kit.sql("SELECT data->>'status' FROM records WHERE record_id = 'invoice:INV-2048'") == [("approved",)]

    async def status(c):
        return (await c.call_tool("review_status", {"request_hash": s["request_hash"]})).structured_content

    assert _session(server_env, status)["status"] == "executed"


def test_startup_fails_closed_on_bad_config(server_env):
    for drop in ("DATABASE_URL", "ACTIONPROOF_ACTOR", "DOCS_DIR"):
        env = {**os.environ, **{k: v for k, v in server_env.items() if k != drop}}
        env.pop(drop, None)
        p = subprocess.run([sys.executable, "-m", "actionproof.server", "--stdio"], env=env, cwd=str(ROOT),
                           input=b"", capture_output=True, timeout=60)
        assert p.returncode == 2, (drop, p.stderr)
        assert b"ConfigError" in p.stderr and drop.encode() in p.stderr
        assert server_env["DATABASE_URL"].encode() not in p.stderr  # never echo a DSN


def test_print_config_is_json_without_secrets(server_env):
    env = {**os.environ, **server_env, "DATABASE_URL": "postgresql://actionproof:s3cr3t-pw@localhost:5433/actionproof"}
    p = subprocess.run([sys.executable, "-m", "actionproof.server", "--print-config"], env=env, cwd=str(ROOT),
                       capture_output=True, timeout=60)
    assert p.returncode == 0, p.stderr
    cfg = json.loads(p.stdout)
    (name, entry), = cfg["mcpServers"].items()
    assert entry["command"] == "python"
    assert entry["args"][:3] == ["-m", "uv", "run"] and entry["args"][-3:] == ["python", "-m", "actionproof.server"]
    assert str(ROOT) in entry["args"]
    e = entry["env"]
    assert e["ACTIONPROOF_ACTOR"] == "agent-7" and e["ACTIONPROOF_ON_BEHALF_OF"] == "user-123"
    assert Path(e["DOCS_DIR"]).is_absolute()
    out = p.stdout.decode()
    assert "s3cr3t-pw" not in out
    assert Path(server_env["SIGNING_KEY_PATH"]).read_bytes().hex() not in out
