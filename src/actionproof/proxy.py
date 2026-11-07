"""Proxy mode (deck slide 3 step 1: "An MCP proxy sits in front of every tool. Default deny."; S3.2).

    python -m actionproof.server --proxy "<upstream command>"     # PROXY_MAP_PATH names the map

The server connects as an MCP CLIENT to an upstream MCP server (stdio) and re-exposes ONLY the upstream tools named
in the proxy map, each bound to one registry tool. Every other upstream tool is not listed, and a call to it is the
server's ordinary unknown-tool refusal (audited 'refuse', never forwarded), even though the upstream offers it.

The proxied tool's gate adapter is ProxyAdapter: the upstream write tool is the gate's `execute` step, so the
upstream sees a write only after commit passed every check, inside the commit tx, at most once per receipt.
`read_record` / `dry_run` go to the upstream read tools named in the map (else the local adapter); `sor_for` stays
the local system of record. Any upstream failure, error result or timeout raises, which the gate turns into
DENY AP-ERR-11 (fail closed), burning the receipt and quarantining the record if the write may have happened.

Map file (JSON; validated, any problem = ConfigError naming PROXY_MAP_PATH, startup aborts):
    {"timeout_seconds": 10,
     "tools": {"<upstream write tool>": {
        "action": "payments.approve_invoice",           # registry tool (gate.TARGETS)
        "args": {"<upstream param>": "<ActionRequest arg>"},
        "idempotency_arg": "idempotency_key",            # upstream param that receives the idempotency key
        "read_record": "<upstream read tool>",           # optional: {record_id} -> {data, version}
        "dry_run": "<upstream read tool>"}}}             # optional: same args as the write -> diff
"""
import json
import os
import re
import shlex
from pathlib import Path

import anyio
import anyio.from_thread
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from actionproof.config import ConfigError
from actionproof.gate import TARGETS
from actionproof.verify import REGISTRY

NAME = r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$"
RESERVED = {"extract_fields", "review_status"}  # the server's own read tools
NO_UPSTREAM_ENV = ("SIGNING_KEY_PATH", "SIGNING_KID")  # never handed to the upstream process (ADR-007)


class UpstreamError(Exception):
    """The upstream failed, returned an error result, or answered something unusable. Carries no upstream text."""


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    action: str
    args: dict[str, str]
    idempotency_arg: str = Field(default="idempotency_key", pattern=NAME)
    read_record: str | None = Field(default=None, pattern=NAME)
    dry_run: str | None = Field(default=None, pattern=NAME)

    @model_validator(mode="after")
    def _check(self):
        if self.action not in TARGETS:
            raise ValueError("action is not a registry tool")
        allowed = REGISTRY[self.action]["allowed"]
        if not all(re.match(NAME, k) for k in self.args) or not set(self.args.values()) <= allowed:
            raise ValueError("args must map upstream params to ActionRequest args of this action")
        if self.idempotency_arg in self.args:
            raise ValueError("idempotency_arg collides with a mapped param")
        return self


class ProxyMap(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    timeout_seconds: int = Field(default=10, ge=1, le=300)
    tools: dict[str, ToolSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self):
        names = set(self.tools)
        if not all(re.match(NAME, n) for n in names) or names & RESERVED:
            raise ValueError("bad or reserved exposed tool name")
        actions = [s.action for s in self.tools.values()]
        if len(actions) != len(set(actions)):
            raise ValueError("one registry tool mapped twice")
        reads = {r for s in self.tools.values() for r in (s.read_record, s.dry_run) if r}
        if reads & names:
            raise ValueError("a read tool cannot also be an exposed write tool")
        return self

    def exposed(self) -> dict[str, str]:
        """MCP name -> registry tool: exactly what the proxy lists."""
        return {name: s.action for name, s in self.tools.items()}

    def upstream_names(self) -> set[str]:
        return set(self.tools) | {r for s in self.tools.values() for r in (s.read_record, s.dry_run) if r}

    def check_offered(self, offered) -> None:
        """Startup check against the upstream's tools/list: every mapped tool must exist (extra tools are fine,
        they are simply never exposed)."""
        missing = self.upstream_names() - set(offered)
        if missing:
            raise ConfigError(f"invalid or missing config: PROXY_MAP_PATH (upstream does not offer "
                              f"{', '.join(sorted(missing))})")


def load_map(path) -> ProxyMap:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return ProxyMap.model_validate(raw)
    except (OSError, ValueError, ValidationError, TypeError) as e:
        raise ConfigError(f"invalid or missing config: PROXY_MAP_PATH ({type(e).__name__})") from None


def split_command(cmd: str) -> list[str]:
    """`--proxy "<cmd>"` -> argv. Windows paths keep their backslashes; surrounding quotes are dropped."""
    parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p
             for p in shlex.split(cmd, posix=os.name != "nt")]
    if not parts:
        raise ConfigError("invalid or missing config: --proxy needs an upstream command")
    return parts


class Upstream:
    """A synchronous handle on one upstream MCP stdio session (the gate is synchronous and runs in worker threads).
    The session lives on a background event loop (an anyio blocking portal); every call has a hard timeout."""

    def __init__(self, argv: list[str], timeout_seconds: int, env=None, cwd=None):
        from mcp import Client, StdioServerParameters

        self._timeout = timeout_seconds
        env = {k: v for k, v in (os.environ if env is None else env).items() if k not in NO_UPSTREAM_ENV}
        params = StdioServerParameters(command=argv[0], args=argv[1:], env=env, cwd=cwd)
        self._portal_cm = anyio.from_thread.start_blocking_portal()
        self._portal = self._portal_cm.__enter__()
        try:
            self._client_cm = self._portal.wrap_async_context_manager(
                Client(params, read_timeout_seconds=timeout_seconds))
            self._client = self._client_cm.__enter__()
            self.tool_names = {t.name for t in self._run(self._client.list_tools).tools}
        except Exception as e:
            self._portal_cm.__exit__(None, None, None)
            raise ConfigError(f"invalid or missing config: --proxy (upstream unusable: {type(e).__name__})") from None

    def _run(self, fn, *args):
        async def go():
            with anyio.fail_after(self._timeout):
                return await fn(*args)

        return self._portal.call(go)

    def call(self, name: str, arguments: dict) -> dict:
        """One upstream tools/call. Raises UpstreamError on anything but a successful object result."""
        try:
            r = self._run(self._client.call_tool, name, arguments)
        except Exception as e:  # crash, closed pipe, timeout: fail closed, the type name only
            raise UpstreamError(f"upstream call failed: {type(e).__name__}") from None
        if r.is_error or not isinstance(r.structured_content, dict):
            raise UpstreamError("upstream returned an error or no structured result")
        return r.structured_content

    def close(self) -> None:
        for cm in (getattr(self, "_client_cm", None), self._portal_cm):
            try:
                if cm is not None:
                    cm.__exit__(None, None, None)
            except Exception:
                pass


class ProxyAdapter:
    """Gate adapter (4-method contract) for one proxied registry tool. `local` is the in-process adapter of the
    same tool: the system-of-record reads (sor_for) and the record write that mirrors the upstream's effect."""

    def __init__(self, name: str, spec: ToolSpec, upstream: Upstream, local):
        self._name, self._spec, self._up, self._local = name, spec, upstream, local

    def _args(self, req) -> dict:
        return {param: req.args[arg].value for param, arg in self._spec.args.items()}

    def sor_for(self, key: str) -> dict:
        return self._local.sor_for(key)

    def read_record(self, record_id: str) -> tuple[dict, int]:
        if self._spec.read_record is None:
            return self._local.read_record(record_id)
        r = self._up.call(self._spec.read_record, {"record_id": record_id})
        if not isinstance(r.get("data"), dict) or type(r.get("version")) is not int:
            raise UpstreamError("upstream read_record answered an unusable record")
        return r["data"], r["version"]

    def dry_run(self, req) -> dict:
        if self._spec.dry_run is None:
            return self._local.dry_run(req)
        return self._up.call(self._spec.dry_run, self._args(req))

    def execute(self, req, expected_version: int, idempotency_key: str, conn) -> dict:
        """The upstream write, then the same effect on the system-of-record row inside the gate's commit tx, once
        per write the upstream reports applying. A hostile upstream that applies twice therefore moves the version
        past the approved diff, and the gate DENYs (AP-STALE-07), burns and quarantines."""
        r = self._up.call(self._name, {**self._args(req), self._spec.idempotency_arg: idempotency_key})
        applied = r.get("applied", 1)
        if type(applied) is not int or applied < 1:
            raise UpstreamError("upstream did not report the write")
        result = self._local.execute(req, expected_version, idempotency_key, conn)
        if applied > 1:
            conn.execute("UPDATE records SET version = version + %s WHERE record_id = %s",
                         (applied - 1, result["record_id"]))
        return {**result, "upstream": self._name}
