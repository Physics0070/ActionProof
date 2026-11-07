"""An existing-style LangChain agent whose tool goes through the ActionProof gate (deck slides 1 and 7, ADR-004).

Offline: langchain_core only, a scripted fake chat model, no network, no API key, no LLM call. The "model" emits
one tool call (approve the hero invoice INV-2048); the gated tool returns the slide-1 card. The receipt stays in
the operator-side pending store; the model's context only ever holds the card text.

Setup (once per take):
    python scripts/dev_pg.py start                      # local Postgres on 5433
    python scripts/gen_key.py                           # keys/dev-signing.key (if absent)
    C:/Users/Soham/tools/opa/opa.exe run --server --addr 127.0.0.1:8181 policy   # OPA sidecar (or docker compose)
    python scripts/demo_seed.py --reset                 # hero records, delegation, people
Run:
    python -m uv run python examples/langchain_agent.py

Config comes from the environment (invariant 7); missing keys fall back to the dev defaults in .env.example.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "fixtures")]

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

import hero  # noqa: E402
from actionproof import db  # noqa: E402
from actionproof.adapters.langchain import gate_tool  # noqa: E402
from actionproof.config import load_settings  # noqa: E402
from actionproof.gate import TOOL, Gate, Principal  # noqa: E402
from actionproof.mocks import MockERP, MockPayments  # noqa: E402
from actionproof.signing import Signer  # noqa: E402


def _env() -> dict:
    defaults = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            defaults[key.strip()] = value.strip()
    return {**defaults, **os.environ}


def build_tool(pending: dict):
    """Operator side: the gate, its connector, the document store and the bound session identity."""
    settings = load_settings(_env())
    signer = Signer.from_path(settings.signing_key_path, settings.signing_kid)
    factory = lambda: db.connect(url=settings.database_url)  # noqa: E731
    erp = MockERP(factory)
    docs = hero.load_docs()  # the operator's document store; the agent only cites doc ids
    gate = Gate(settings, signer, factory, {TOOL: MockPayments(erp, factory)}, docs_provider=lambda req: docs)
    # The identity is the session's, bound here; nothing the model writes can change it (ADR-012).
    return gate_tool(gate, Principal("agent-7", "user-123"), "approve_invoice",
                     "Approve a vendor invoice for payment. Argument `request`: the ActionRequest JSON.",
                     pending=pending)


def main() -> int:
    pending: dict = {}
    tool = build_tool(pending)
    call = {"name": tool.name, "args": {"request": hero.hero_request("idem-lc-1").model_dump(mode="json")},
            "id": "call-1"}
    model = FakeMessagesListChatModel(responses=[
        AIMessage(content="", tool_calls=[call]),
        AIMessage(content="The approval was intercepted and is waiting for a human reviewer."),
    ])
    messages = [HumanMessage("Approve invoice INV-2048 from ACME for payment.")]
    while True:  # the classic tool-calling loop
        ai = model.invoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            break
        for tc in ai.tool_calls:
            result = {tool.name: tool}[tc["name"]].invoke(tc)  # a ToolMessage: the only thing the model sees
            messages.append(result)
            print(result.content)
            print()
    print(f"agent: {ai.content}")
    print(f"operator: {len(pending)} receipt(s) held for review, none given to the agent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
