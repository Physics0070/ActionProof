# API

## LangChain adapter
Module `actionproof.adapters.langchain` (deck slide 7 "Agent adapter", ADR-004). In-process; the operator builds
the tools and hands the agent only the gated ones. Every call goes through `Gate.prepare` / `Gate.commit`.

| Function | Signature | Use |
|---|---|---|
| `gate_tool` | `gate_tool(gate, principal, name, description, args_schema=None, *, pending=None) -> BaseTool` | new tool; the call is `{"request": <ActionRequest JSON>}` (object or JSON string). With `args_schema`, the call's fields are the ActionRequest itself. |
| `ExistingToolStep` | `ExistingToolStep(tool, connector, to_request)` | Gate adapter for an existing tool: `sor_for` / `read_record` / `dry_run` from `connector`; `execute` = the original tool. Register it in the Gate's `{tool name: adapter}` map. |
| `wrap_existing` | `wrap_existing(step, gate, principal, *, pending=None) -> BaseTool` | the existing tool, same name, description and arguments, routed through the gate; `step.to_request(kwargs) -> ActionRequest JSON`. |

- `principal`: `gate.Principal(actor, on_behalf_of)` of the authenticated session, bound at build time. Tool
  arguments never set it; a request whose `actor`/`on_behalf_of` differ is DENY AP-SCOPE-02 / G1 (ADR-012).
- `pending`: an operator-owned dict; a REVIEW stores `request_hash -> (receipt, request)` there for the review side
  (`Gate.mint_review_token`, then `Gate.commit` with the token). Omitted = a private dict.
- Documents: the Gate's `docs_provider`, never the agent.

Tool output (text, the only thing the model sees; it never contains a receipt, nonce or signature):

| Outcome | Output |
|---|---|
| DENY (prepare) | card + `reasons:` + `- <rule> [<G1/G2>] <msg>` lines |
| REVIEW | card + `request_hash: <sha256>` + `status: PENDING_REVIEW ...` |
| ALLOW, executed | card + `commit: EXECUTED` + `result: <tool result JSON>` |
| ALLOW, commit refused | card + `commit: DENY` + reasons |
| any exception / bad arguments | DENY card with `AP-ERR-11 [G1] adapter failed: <ExceptionType>` |

Example (offline, no API key): `examples/langchain_agent.py`; setup `python scripts/dev_pg.py start`,
`python scripts/gen_key.py`, OPA on `OPA_URL` (`opa run --server policy`), `python scripts/demo_seed.py --reset`;
run `python -m uv run python examples/langchain_agent.py`. It prints the slide-1 card. Proof:
`tests/e2e/test_slide1_langchain.py`.
