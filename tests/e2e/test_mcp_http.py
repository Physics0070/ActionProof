"""HTTP transport (ADR-012): `python -m actionproof.server --http --port N`. The Principal comes from the bearer
token (api_clients, sha256 stored), never from the request body; no token, a wrong token, or a browser Origin
(CORS closed) is refused before any tool runs."""
import importlib.util
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import anyio
import httpx
import httpx2
import pytest
from mcpkit import body

import hero
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("seed_api_client", ROOT / "scripts" / "seed_api_client.py")
seed_api_client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_api_client)


@pytest.fixture
def http_server(kit, pg, opa_url, signing_key_path, tmp_path):
    token = seed_api_client.seed(kit.db, "agent-7", "user-123")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "DATABASE_URL": pg, "OPA_URL": opa_url, "SIGNING_KEY_PATH": str(signing_key_path),
           "OPA_TIMEOUT_SECONDS": "5", "DOCS_DIR": str(hero.OUT), "PYTHONPATH": str(ROOT / "src")}
    env.pop("ACTIONPROOF_ACTOR", None)
    env.pop("ACTIONPROOF_ON_BEHALF_OF", None)
    log = (tmp_path / "server.log").open("wb")
    proc = subprocess.Popen([sys.executable, "-m", "actionproof.server", "--http", "--port", str(port)], env=env,
                            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        for _ in range(200):
            if proc.poll() is not None:
                raise RuntimeError((tmp_path / "server.log").read_text(errors="replace"))
            try:
                httpx.get(url, timeout=0.5)
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        yield url, token
    finally:
        proc.kill()
        proc.wait()
        log.close()


def _with_token(url, token, steps):
    async def go():
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=120) as h:
            async with Client(streamable_http_client(url, http_client=h)) as c:
                return await steps(c)

    return anyio.run(go)


def test_bearer_token_principal_and_slide1(kit, http_server):
    url, token = http_server

    async def steps(c):
        names = sorted(t.name for t in (await c.list_tools()).tools)
        r = await c.call_tool("payments_approve_invoice", body(kit.hero()[0]))
        return names, r

    names, r = _with_token(url, token, steps)
    assert "payments_approve_invoice" in names
    assert r.structured_content["status"] == "pending" and "decision: REVIEW" in r.content[0].text
    assert kit.sql("SELECT actor, on_behalf_of FROM pending_reviews") == [("agent-7", "user-123")]
    # The table holds only the digest of the token.
    assert kit.sql("SELECT count(*) FROM api_clients WHERE token_hash = %s", (token,)) == [(0,)]


def test_missing_or_wrong_token_refused(kit, http_server):
    url, token = http_server
    init = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    hdr = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    assert httpx.post(url, json=init, headers=hdr, timeout=10).status_code == 401
    assert httpx.post(url, json=init, headers={**hdr, "Authorization": "Bearer nope"}, timeout=10).status_code == 401
    assert httpx.post(url, json=init, headers={**hdr, "Authorization": token}, timeout=10).status_code == 401
    r = httpx.post(url, json=init, headers={**hdr, "Authorization": f"Bearer {token}",
                                            "Origin": "https://evil.example"}, timeout=10)
    assert r.status_code == 403
    assert token not in r.text
    assert kit.executes == 0


def test_body_cannot_pick_another_principal(kit, http_server):
    url, token = http_server
    d = body(kit.hero()[0])
    d["actor"], d["on_behalf_of"] = "agent-9", "user-9"

    async def steps(c):
        return await c.call_tool("payments_approve_invoice", d)

    r = _with_token(url, token, steps)
    assert r.structured_content["decision"] == "DENY"
    assert [x["rule"] for x in r.structured_content["reasons"]] == ["AP-SCOPE-02"]
