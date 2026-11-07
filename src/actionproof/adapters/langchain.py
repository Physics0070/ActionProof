"""LangChain front door to the same Gate (deck slide 7 "Agent adapter", ADR-004). In-process, operator-built.

The model only ever sees the tool's text output: PrepareResult.card() plus a short status. It never receives a
receipt, a nonce or a signature (G2). The Principal is bound when the operator builds the tool, never read from
the call (ADR-012). Any exception is a DENY string; nothing executes outside Gate.commit (invariant 1).

- gate_tool: the call argument is the ActionRequest JSON; the effect is the adapter the Gate already serves.
- wrap_existing + ExistingToolStep: an existing LangChain tool keeps its name and arguments; `to_request` maps
  them to an ActionRequest, and the original tool runs ONLY as the gate's `execute` step, after every check.
  Limitation: the original tool must be idempotent-keyed (take the request's idempotency key as an argument and
  dedupe on it): the gate calls execute at most once per receipt, but after an unknown outcome (burn, ADR-014) only
  the tool can tell whether its effect happened. Give the agent only the wrapped tool, never the original, and do not
  set handle_tool_error on the original (its failure must raise so the gate rolls back and quarantines).
"""

import json
from typing import Any, Callable

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from actionproof.contracts import ActionRequest, request_hash
from actionproof.gate import TARGETS, PrepareResult
from actionproof.verify import Reason, VerifyResult


class _RequestArg(BaseModel):
    request: Any = Field(default=None, description="The ActionRequest JSON (tool, actor, on_behalf_of, "
                                                   "idempotency_key, args with DIRECT/DERIVED/ASSERTED claims).")


def _reasons(reasons) -> list[str]:
    return [f"- {r.rule} [{r.guarantee}] {r.msg}" for r in reasons]


def _deny_text(exc: BaseException) -> str:
    """The gate was not reached or failed in the adapter: DENY AP-ERR-11 / G1, exception type name only."""
    reason = Reason("AP-ERR-11", "G1", f"adapter failed: {type(exc).__name__}")
    card = PrepareResult("DENY", [reason], VerifyResult(False, {}, []), None, None).card()
    return "\n".join([card, "reasons:", *_reasons([reason])])


def _run(gate, principal, raw, pending: dict, on_receipt: Callable[[str], None] | None) -> str:
    try:
        if isinstance(raw, str):
            raw = json.loads(raw)
        res = gate.prepare(raw, principal=principal)
        lines = [res.card()]
        if res.decision == "DENY" or res.receipt is None:
            return "\n".join([*lines, "reasons:", *_reasons(res.reasons)])
        req: ActionRequest = res.request
        h = request_hash(req)
        if on_receipt is not None:
            on_receipt(h)
        if res.decision == "REVIEW":
            # ponytail: in-process dict (lost on restart, unbounded); upgrade path is the gate-side pending_reviews
            # table through review.py once that lands (Task 5.4). The receipt stays operator-side: the agent must
            # never hold it (G2).
            pending[h] = (res.receipt, req)
            return "\n".join([*lines, f"request_hash: {h}",
                              "status: PENDING_REVIEW (a different person must approve it in the review console)"])
        com = gate.commit(res.receipt, req, principal=principal)
        if com.outcome != "EXECUTED":
            return "\n".join([*lines, "commit: DENY", "reasons:", *_reasons(com.reasons)])
        return "\n".join([*lines, "commit: EXECUTED", f"result: {json.dumps(com.tool_result, sort_keys=True)}"])
    except Exception as e:  # fail closed (invariant 1): the model gets a DENY, never a traceback
        return _deny_text(e)


def gate_tool(gate, principal, name: str, description: str, args_schema=None, *,
              pending: dict | None = None) -> BaseTool:
    """A LangChain tool whose call is `{"request": <ActionRequest JSON>}` (or, with a custom `args_schema`, the
    ActionRequest fields themselves). prepare -> ALLOW: commit; REVIEW: receipt into `pending` (keyed by
    request_hash; pass your own dict to reach it from the review side); DENY: reasons."""
    store = {} if pending is None else pending

    def call(**kw) -> str:
        return _run(gate, principal, kw if args_schema is not None else kw.get("request"), store, None)

    return StructuredTool.from_function(func=call, name=name, description=description,
                                        args_schema=args_schema or _RequestArg,
                                        handle_validation_error=_deny_text)


class ExistingToolStep:
    """Gate adapter for a wrapped existing tool: system-of-record reads and the dry run come from `connector`; the
    effect is the original LangChain tool, invoked only by Gate.commit (register it in the Gate's tool map)."""

    def __init__(self, tool: BaseTool, connector, to_request: Callable[[dict], dict]):
        self.tool, self.to_request = tool, to_request
        self._connector = connector
        self._calls: dict[str, dict] = {}  # request_hash -> the original tool's arguments (prepared calls only)

    def sor_for(self, key):
        return self._connector.sor_for(key)

    def read_record(self, record_id):
        return self._connector.read_record(record_id)

    def dry_run(self, req):
        return self._connector.dry_run(req)

    def execute(self, req, expected_version, idempotency_key, conn) -> dict:
        # Only a call that came through wrap_existing has arguments here; anything else raises (gate DENY + burn).
        kwargs = self._calls.pop(request_hash(req))
        output = self.tool.invoke(kwargs)
        # Record the approved effect in the gate's view of the record, in the commit tx (rolls back with it), so a
        # fresh prepare sees the record already actioned (AP-STALE-07). Target status from the dry-run diff.
        target = str(self.dry_run(req).get("status", "")).partition("->")[2]
        if target:
            conn.execute("UPDATE records SET data = jsonb_set(data, '{status}', to_jsonb(%s::text)) "
                         "WHERE record_id = %s", (target, _record_id(req)))
        return {"output": output if isinstance(output, (str, int, dict, list)) else str(output)}


def _record_id(req) -> str:
    t = TARGETS[req.tool]
    return f"{t.kind}:{req.args[t.arg].value}"


def wrap_existing(step: ExistingToolStep, gate, principal, *, pending: dict | None = None) -> BaseTool:
    """The existing tool, same name/description/arguments, routed through the gate: its arguments become an
    ActionRequest via step.to_request, and its function runs only as step.execute inside Gate.commit."""
    store = {} if pending is None else pending
    original = step.tool

    def call(**kw) -> str:
        seen: list[str] = []

        def remember(h: str) -> None:  # kept for the commit now (ALLOW) or the human's later one (REVIEW)
            seen.append(h)
            step._calls[h] = dict(kw)

        try:
            raw = step.to_request(dict(kw))
        except Exception as e:
            return _deny_text(e)
        out = _run(gate, principal, raw, store, remember)
        if seen and seen[0] not in store:  # not pending review: an ALLOW commit consumed it or was denied
            step._calls.pop(seen[0], None)
        return out

    return StructuredTool.from_function(func=call, name=original.name, description=original.description,
                                        args_schema=original.args_schema,
                                        handle_validation_error=_deny_text)
