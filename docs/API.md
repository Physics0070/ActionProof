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

## MCP server
Module `actionproof.server` (deck slide 3 step 1 "an MCP proxy sits in front of every tool. Default deny", S3.2,
S7.1; ADR-004, ADR-012). SDK: the official `mcp` 2.x lowlevel `Server` (so an unknown tool name reaches our handler
and is audited, instead of being rejected inside the SDK).

| Run | Command | Principal |
|---|---|---|
| stdio (default) | `python -m actionproof.server --stdio` | `ACTIONPROOF_ACTOR` / `ACTIONPROOF_ON_BEHALF_OF`, set by the OPERATOR in the client config, read once at startup |
| HTTP | `python -m actionproof.server --http --port N` (127.0.0.1, streamable HTTP at `/mcp`, stateless JSON) | `Authorization: Bearer <token>` -> `api_clients` row (only `sha256(token)` stored, constant-time compare). Seed: `python scripts/seed_api_client.py --actor agent-7 --on-behalf-of user-123` (prints the token once) |
| Claude Desktop | `python -m actionproof.server --print-config` | prints an `mcpServers` entry (`python -m uv run --directory <project> python -m actionproof.server` + env); the DSN password is a `<PASSWORD>` placeholder, the key is a path |

Startup validates env (`config.load_settings` + `DOCS_DIR`, `RATE_LIMIT_PER_MINUTE`, `SERVER_PORT`, and for stdio
the Principal); any problem prints `ConfigError: ... <VAR names>` (never values) and exits 2 (fail closed).
HTTP: a request with an `Origin` header is 403 (CORS closed, no browser callers); a missing/invalid bearer is 401;
both before the MCP layer. The body's `actor`/`on_behalf_of` must equal the Principal, else DENY AP-SCOPE-02 / G1.

### Tools (nothing else is listed; no resources, no prompts)
| Tool | Arguments | Effect |
|---|---|---|
| `payments_approve_invoice` | ActionRequest JSON (`tool` optional; if present must be `payments.approve_invoice`) | `Gate.prepare` -> ALLOW: `Gate.commit` in the same call; REVIEW: parked; DENY |
| `payments_refund_payment` | ActionRequest JSON (`tool` optional = `payments.refund_payment`) | same |
| `extract_fields` (read-only) | `{"doc_id": "invoice.pdf"}` | the document's citable spans, labelled untrusted |
| `review_status` (read-only) | `{"request_hash": "<64 hex>"}` | status of one of the CALLER's parked requests |

Example call (hero, deck slide 1):
```json
{"actor": "agent-7", "on_behalf_of": "user-123", "idempotency_key": "idem-1", "args": {
  "invoice_id": {"value": "INV-2048", "claim": "DIRECT", "src": {"doc": "invoice.pdf", "page": 1,
                 "bbox": ["159.79", "68.49", "244.29", "95.99"]}, "doc_sha256": "8237...fe23"},
  "amount": {"value": "4800.00", "claim": "DIRECT", "src": {"doc": "invoice.pdf", "page": 1,
             "bbox": ["189.99", "406.94", "252.28", "426.20"]}, "doc_sha256": "8237...fe23"},
  "variance": {"value": "500.00", "claim": "DERIVED", "fn": "sub", "inputs": ["invoice.total", "po.total"]}, "...": "..."}}
```

### Responses
Every result has `content[0]` = the text the model should read and `content[1]` = the same object as JSON
(`structured_content`). For the action tools and every refusal, `content[0]` is exactly `PrepareResult.card()`
(slide 1 shape; the rule line shows the highest-priority reason: AP-VER-01, AP-SCOPE-02, AP-SEP-12, AP-REF-13,
AP-INV-04, AP-CUM-03, then others). `is_error` is true only for `status: refused`.

| status | decision | fields |
|---|---|---|
| `executed` | ALLOW | `request_hash`, `reasons: []`, `card`, `result` (the tool's result) |
| `denied` | DENY | `request_hash`, `reasons: [{rule, guarantee, msg}]`, `card` (prepare DENY, or the commit's DENY reasons) |
| `pending` | REVIEW | `request_hash`, `reasons`, `card`. The signed receipt is stored server-side (`pending_reviews`) and never returned |
| `refused` | DENY | `error: {code, message}`, `reasons`, `card`. Codes: `unknown_tool`, `malformed` (AP-VER-01 / G1), `unknown_doc`, `extraction_failed` (AP-VER-01), `unauthenticated` (AP-SCOPE-02), `rate_limited`, `internal` (AP-ERR-11). Every refusal except `rate_limited` is an audit entry (kind `refuse`); a refused call is never prepared |

`review_status` -> `{status: pending|approved|rejected|executed|denied|not_found, request_hash, reasons}`; another
principal's request is `not_found` (indistinguishable from none). `extract_fields` ->
`{status: ok, untrusted_document_text: true, notice, doc_id, kind, doc_sha256, truncated}` plus, for a PDF,
`words`/`lines` `[{page, bbox: [x0, top, x1, bottom] 2dp strings, text}]` (geometry from PyMuPDF padded 0.01 pt like
the fixture manifest; text = what pdfplumber reads in that box, so a span cited as-is re-extracts), and for JSON
`leaves: [{pointer, value}]` (numbers as literal text). Doc ids are keys of `DOCS_DIR/manifest.json` only (never a
path); max 5 MB per document, 2000 spans.

### Rate limit
Per Principal, in-memory token bucket: `RATE_LIMIT_PER_MINUTE` (default 60) calls of burst, refilled continuously;
over the limit -> `refused` / `rate_limited` (`# ponytail`: per process).

### Human review (not an MCP tool)
`review.complete_review(gate, conn_factory, request_hash, reviewer_login, approve, reason) -> ReviewOutcome(status,
reasons)`: for the console backend only (Task 5.7), `reviewer_login` = the authenticated session subject. Approve ->
`Gate.mint_review_token` (AP-SEP-12 refusal leaves it `pending`) then `Gate.commit` with the token -> `executed` /
`denied`; reject -> `rejected` with `AP-REV-10 "rejected by reviewer: <reason>"`; a completed review -> AP-REP-05.
`review.park(conn_factory, req, receipt, reasons)` is the shared REVIEW store (MCP server, and the LangChain adapter
with `review_db=<conn factory>`).
