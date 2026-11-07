"""Helpers for MCP server tests: an App wired to the test kit's gate, and an in-process MCP client round trip.

The in-process path uses the SDK's real Client against the real lowlevel Server (no JSON-RPC framing); the
stdio and HTTP e2e tests (tests/e2e) spawn the server as a subprocess instead.
"""
import anyio
from gatekit import AGENT

import hero
from actionproof import server as srv
from mcp import Client


def app_for(kit, rate: int = 10_000) -> "srv.App":
    return srv.App(kit.gate, srv.DocStore(hero.OUT), kit.factory, rate_limit_per_minute=rate)


def call(app, name: str, arguments, principal=AGENT):
    """One MCP tools/call through the SDK client. Returns (texts, structured, is_error)."""

    async def go():
        async with Client(srv.build_server(app, lambda ctx: principal)) as c:
            r = await c.call_tool(name, arguments)
            return [b.text for b in r.content], r.structured_content, r.is_error

    return anyio.run(go)


def listing(app, principal=AGENT):
    """(tool names, tools, resources, prompts) as an MCP client sees them."""

    async def go():
        async with Client(srv.build_server(app, lambda ctx: principal)) as c:
            tools = (await c.list_tools()).tools
            resources = (await c.list_resources()).resources
            prompts = (await c.list_prompts()).prompts
            return [t.name for t in tools], tools, resources, prompts

    return anyio.run(go)


def body(req) -> dict:
    """The tool arguments an agent sends: the ActionRequest JSON."""
    return req if isinstance(req, dict) else req.model_dump(mode="json")
