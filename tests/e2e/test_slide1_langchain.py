"""Deck slide 1 (S1.1) and slide 7 "Agent adapter" (S7.7, ADR-004): an existing LangChain agent's tool goes through
the same Gate. The model only ever sees the tool's text output; the receipt stays on the operator side.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from gatekit import AGENT, HERO_DOCS, INVOICE_TOOL, REFUND_TOOL
from langchain_core.tools import tool as lc_tool
from pydantic import BaseModel

from actionproof.adapters.langchain import ExistingToolStep, gate_tool, wrap_existing
from actionproof.contracts import request_hash
from actionproof.gate import Gate, Principal

ROOT = Path(__file__).resolve().parents[2]
SLIDE_1 = (
    "ACTION INTERCEPTED\n"
    "action: approve_invoice\n"
    "amount: 4800.00 [DIRECT ok]\n"
    "variance: 500.00 [DERIVED ok]\n"
    "rule: AP-INV-04 (> 100)\n"
    "decision: REVIEW"
)


def _gate(kit, tools=None) -> Gate:
    """The production Gate (no default principal), documents supplied operator-side, never by the agent."""
    return Gate(kit.settings, kit.signer, kit.factory, tools or {INVOICE_TOOL: kit.tool, REFUND_TOOL: kit.refunds},
                docs_provider=lambda req: HERO_DOCS)


def _hero_json(kit, **amount) -> dict:
    d = kit.hero()[0].model_dump(mode="json")
    if amount:
        d["args"]["amount"]["value"] = amount["amount"]
    return d


def _no_receipt(out: str, receipt: dict | None = None) -> None:
    for word in ('"sig"', "sig:", "payload", "nonce", "receipt:", "kid"):
        assert word not in out
    if receipt is not None:
        assert receipt["sig"] not in out and receipt["payload"]["nonce"] not in out


def test_slide1_card_exact_through_langchain_tool(kit):
    """S1.1 via S7.7: the hero approval, called as a LangChain tool, prints the deck card exactly; nothing runs."""
    pending: dict = {}
    t = gate_tool(_gate(kit), AGENT, "approve_invoice", "Approve a vendor invoice.", pending=pending)
    out = t.invoke({"request": _hero_json(kit)})
    assert out.startswith(SLIDE_1 + "\n")
    h = request_hash(kit.hero()[0])
    assert f"request_hash: {h}" in out and "PENDING_REVIEW" in out
    assert list(pending) == [h]
    assert kit.executes == 0 and kit.tool.calls == []


def test_tool_call_message_carries_the_card(kit):
    """The model-facing ToolMessage (what an agent loop appends) is the same text."""
    t = gate_tool(_gate(kit), AGENT, "approve_invoice", "Approve a vendor invoice.")
    msg = t.invoke({"name": "approve_invoice", "args": {"request": _hero_json(kit)}, "id": "call-1",
                    "type": "tool_call"})
    assert msg.tool_call_id == "call-1" and msg.content.startswith(SLIDE_1)


class _Fields(BaseModel):
    tool: str
    actor: str
    on_behalf_of: str
    idempotency_key: str
    args: dict


def test_custom_args_schema_takes_request_fields(kit):
    """With an operator-given args_schema, the call's fields are the ActionRequest itself (same gate, same card)."""
    t = gate_tool(_gate(kit), AGENT, "approve_invoice", "Approve a vendor invoice.", args_schema=_Fields)
    assert t.invoke(_hero_json(kit)).startswith(SLIDE_1)
    assert kit.executes == 0


def test_amount_4900_denied_g1_no_tool_call(kit):
    """USP G1: a value not at the cited span (4900.00 vs the PDF's 4800.00) is DENY AP-VER-01 before any write."""
    t = gate_tool(_gate(kit), AGENT, "approve_invoice", "Approve a vendor invoice.")
    out = t.invoke({"request": _hero_json(kit, amount="4900.00")})
    assert "amount: 4900.00 [DIRECT FAILED]" in out
    assert "rule: AP-VER-01 [G1]" in out and "decision: DENY" in out
    assert "- AP-VER-01 [G1]" in out
    assert kit.executes == 0 and kit.tool.calls == []


def test_principal_bound_at_build_not_from_arguments(kit):
    """ADR-012: the agent cannot name itself or its principal. Extra `principal`/`actor` arguments are ignored, the
    request's own identity must equal the bound Principal, and the binding decides."""
    g = _gate(kit)
    t = gate_tool(g, AGENT, "approve_invoice", "Approve a vendor invoice.")
    assert set(t.args) == {"request"}
    forged = _hero_json(kit)
    forged["on_behalf_of"] = "cfo"
    out = t.invoke({"request": forged, "principal": {"actor": "agent-7", "on_behalf_of": "cfo"},
                    "on_behalf_of": "cfo"})
    assert "decision: DENY" in out and "AP-SCOPE-02 [G1]" in out
    other = gate_tool(g, Principal("agent-8", "user-123"), "approve_invoice", "Approve a vendor invoice.")
    out = other.invoke({"request": _hero_json(kit), "principal": {"actor": "agent-7", "on_behalf_of": "user-123"}})
    assert "decision: DENY" in out and "AP-SCOPE-02 [G1]" in out
    assert kit.executes == 0


@pytest.mark.parametrize("bad", [None, 42, "not json", "[]", {"tool": "nope"}, {"request": "x"}, [1, 2]])
def test_garbage_input_is_deny_card(kit, bad):
    """Invariant 1 at the adapter: any input shape is a DENY string carrying a card, never an exception."""
    t = gate_tool(_gate(kit), AGENT, "approve_invoice", "Approve a vendor invoice.")
    out = t.invoke({"request": bad})
    assert out.startswith("ACTION INTERCEPTED\n") and "decision: DENY" in out
    assert kit.executes == 0


class _Boom:
    """A gate whose calls raise with hostile text (the message must never reach the model)."""

    def __init__(self, on: str, inner=None):
        self.on, self.inner = on, inner

    def prepare(self, *a, **kw):
        if self.on == "prepare":
            raise RuntimeError("secret-xyz")
        return self.inner.prepare(*a, **kw)

    def commit(self, *a, **kw):
        raise RuntimeError("secret-xyz")


@pytest.mark.parametrize("on", ["prepare", "commit"])
def test_adapter_exceptions_are_deny(kit, on):
    """Invariant 1: an exception anywhere in the adapter is DENY AP-ERR-11 / G1 (type name only); no tool runs."""
    req = kit.hero_allow()[0].model_dump(mode="json")
    t = gate_tool(_Boom(on, _gate(kit)), AGENT, "approve_invoice", "Approve a vendor invoice.")
    out = t.invoke({"request": req})
    assert "decision: DENY" in out and "AP-ERR-11 [G1]" in out and "RuntimeError" in out
    assert "secret-xyz" not in out
    assert kit.executes == 0


def test_allow_executes_once_and_agent_gets_no_receipt(kit):
    """ALLOW: the adapter commits on the operator side; the tool runs once; a second call cannot run it again."""
    t = gate_tool(_gate(kit), AGENT, "approve_invoice", "Approve a vendor invoice.")
    req = kit.hero_allow()[0].model_dump(mode="json")
    out = t.invoke({"request": req})
    assert "decision: ALLOW" in out and "commit: EXECUTED" in out
    _no_receipt(out)
    again = t.invoke({"request": req})
    assert "decision: DENY" in again
    assert kit.executes == 1 and len(kit.tool.calls) == 1


def test_review_receipt_stays_operator_side_and_human_can_commit(kit):
    """USP G2: the REVIEW receipt never enters the model's context; the operator's pending store holds it and a
    different person's review token commits it exactly once."""
    pending: dict = {}
    g = _gate(kit)
    t = gate_tool(g, AGENT, "approve_invoice", "Approve a vendor invoice.", pending=pending)
    out = t.invoke({"request": _hero_json(kit)})
    (h, (receipt, req)), = pending.items()
    _no_receipt(out, receipt)
    assert json.dumps(receipt) not in out
    token = g.mint_review_token(receipt, req, reviewer_login="rev-alice")
    assert g.commit(receipt, req, token, principal=AGENT).outcome == "EXECUTED"
    assert kit.executes == 1


def _existing(calls: list):
    @lc_tool
    def approve_invoice(invoice_id: str, amount: str, idempotency_key: str) -> str:
        """Approve a vendor invoice for payment (an existing agent's tool)."""
        calls.append((invoice_id, amount, idempotency_key))
        return f"approved {invoice_id} for {amount}"

    return approve_invoice


def _to_request(kit):
    base = kit.hero_allow()[0].model_dump(mode="json")

    def to_request(kw: dict) -> dict:
        d = json.loads(json.dumps(base))
        d["idempotency_key"] = kw["idempotency_key"]
        d["args"]["amount"]["value"] = kw["amount"]
        return d

    return to_request


def test_wrap_existing_runs_original_only_as_execute_step(kit):
    """S7.7 "works with existing agents": an existing tool, unchanged, runs only as the gate's execute step:
    DENY (4900.00, G1) never calls it, ALLOW calls it exactly once, a retry cannot call it again."""
    calls: list = []
    original = _existing(calls)
    step = ExistingToolStep(original, kit.tool, _to_request(kit))
    g = _gate(kit, {INVOICE_TOOL: step})
    wrapped = wrap_existing(step, g, AGENT)
    assert wrapped.name == original.name and set(wrapped.args) == set(original.args)
    out = wrapped.invoke({"invoice_id": "INV-2048", "amount": "4900.00", "idempotency_key": "w-1"})
    assert "decision: DENY" in out and "AP-VER-01 [G1]" in out and calls == []
    out = wrapped.invoke({"invoice_id": "INV-2048", "amount": "4800.00", "idempotency_key": "w-2"})
    assert "commit: EXECUTED" in out and "approved INV-2048 for 4800.00" in out
    assert calls == [("INV-2048", "4800.00", "w-2")]
    _no_receipt(out)
    again = wrapped.invoke({"invoice_id": "INV-2048", "amount": "4800.00", "idempotency_key": "w-3"})
    assert "decision: DENY" in again and len(calls) == 1
    assert kit.sql("SELECT data->>'status' FROM records WHERE record_id = 'invoice:INV-2048'") == [("approved",)]


def test_wrap_existing_review_does_not_run(kit):
    """A REVIEW from a wrapped tool runs nothing until a human approves (hero variance 500.00)."""
    calls: list = []
    original = _existing(calls)
    hero = kit.hero()[0].model_dump(mode="json")
    step = ExistingToolStep(original, kit.tool, lambda kw: hero)
    wrapped = wrap_existing(step, _gate(kit, {INVOICE_TOOL: step}), AGENT)
    out = wrapped.invoke({"invoice_id": "INV-2048", "amount": "4800.00", "idempotency_key": "idem-1"})
    assert out.startswith(SLIDE_1) and "PENDING_REVIEW" in out and calls == []


def test_example_agent_prints_slide1(kit, pg, opa_url, signing_key_path):
    """The offline example agent (scripted fake chat model, no network, no key) prints the slide-1 card."""
    env = {**os.environ, "DATABASE_URL": pg, "OPA_URL": opa_url, "SIGNING_KEY_PATH": str(signing_key_path)}
    env["OPA_TIMEOUT_SECONDS"] = "5"  # a cold subprocess; the decision is the same
    p = subprocess.run([sys.executable, str(ROOT / "examples" / "langchain_agent.py")], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=240)
    assert p.returncode == 0, p.stderr
    assert SLIDE_1 in p.stdout
    assert "PENDING_REVIEW" in p.stdout and '"sig"' not in p.stdout
    assert kit.executes == 0 and kit.sql("SELECT count(*) FROM commits") == [(0,)]
