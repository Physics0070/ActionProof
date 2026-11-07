"""A tiny stdio MCP server standing in for a real payments system, for proxy-mode tests and the demo.

    python -m actionproof.server --proxy "python examples/mock_upstream_server.py"   (map: examples/proxy-map.json)

Tools: approve_invoice (the write), get_record and preview_approval (reads), and delete_all_invoices, a dangerous
tool deliberately left OUT of the proxy map: the proxy must never list or forward it (default deny).
It never writes the database itself (the gate mirrors the reported effect inside its commit tx); get_record reads
`records` read-only via DATABASE_URL.

Env: MOCK_UPSTREAM_LOG  file that gets one JSON line per tools/call received (what tests call "upstream calls")
     MOCK_UPSTREAM_MODE honest (default) | double (hostile: reports applying the write twice) |
                        crash (the process dies on a write) | hang (a write never answers)
"""
import json
import os

import anyio
import mcp_types as types
import psycopg

from mcp.server import Server

MODE = os.environ.get("MOCK_UPSTREAM_MODE", "honest")
_done: dict[str, dict] = {}  # idempotency key -> first result (an honest upstream never applies a key twice)


def _schema(*props: str) -> dict:
    return {"type": "object", "properties": {p: {"type": "string"} for p in props}, "required": list(props),
            "additionalProperties": False}


TOOLS = [
    types.Tool(name="approve_invoice", input_schema=_schema("invoice_id", "amount", "idempotency_key"),
               description="Approve an invoice for payment."),
    types.Tool(name="get_record", input_schema=_schema("record_id"), description="Read one record."),
    types.Tool(name="preview_approval", input_schema=_schema("invoice_id", "amount"),
               description="Dry run of approve_invoice."),
    types.Tool(name="delete_all_invoices", input_schema={"type": "object", "properties": {}},
               description="Delete every invoice. Dangerous; never mapped."),
]


def _log(name: str, arguments: dict) -> None:
    path = os.environ.get("MOCK_UPSTREAM_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"tool": name, "arguments": arguments}, sort_keys=True) + "\n")


def _ok(data: dict) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(data))],
                                structured_content=data)


async def _call(name: str, a: dict) -> types.CallToolResult:
    _log(name, a)
    if name == "get_record":
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as conn:
            row = conn.execute("SELECT data, version FROM records WHERE record_id = %s", (a["record_id"],)).fetchone()
        if row is None:
            return types.CallToolResult(content=[types.TextContent(type="text", text="not found")], is_error=True)
        return _ok({"data": row[0], "version": row[1]})
    if name == "preview_approval":
        return _ok({"record_id": f"invoice:{a['invoice_id']}", "status": "open->approved", "amount": a["amount"]})
    if name == "approve_invoice":
        if MODE == "crash":
            os._exit(3)
        if MODE == "hang":
            await anyio.sleep(3600)
        key = a["idempotency_key"]
        if key not in _done:
            _done[key] = {"invoice_id": a["invoice_id"], "status": "approved", "amount": a["amount"],
                          "applied": 2 if MODE == "double" else 1}
        return _ok(_done[key])
    if name == "delete_all_invoices":
        return _ok({"deleted": "all"})
    return types.CallToolResult(content=[types.TextContent(type="text", text="unknown tool")], is_error=True)


def main() -> None:
    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=TOOLS)

    async def call_tool(ctx, params):
        return await _call(params.name, params.arguments or {})

    server = Server("mock-payments-upstream", version="0.1.0", on_list_tools=list_tools, on_call_tool=call_tool)

    async def serve():
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(serve)


if __name__ == "__main__":
    main()
