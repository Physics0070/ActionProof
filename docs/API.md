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

### Proxy mode (deck slide 3 step 1, S3.2)
`python -m actionproof.server --proxy "<upstream command>"` (stdio or `--http`): the server connects as an MCP
CLIENT to a stdio upstream MCP server and re-exposes ONLY the upstream tools named in the proxy map
(`PROXY_MAP_PATH`, module `actionproof.proxy`). Example upstream + map: `examples/mock_upstream_server.py`,
`examples/proxy-map.json`:
```json
{"timeout_seconds": 10, "tools": {"approve_invoice": {"action": "payments.approve_invoice",
  "args": {"invoice_id": "invoice_id", "amount": "amount"}, "idempotency_arg": "idempotency_key",
  "read_record": "get_record", "dry_run": "preview_approval"}}}
```
- Listing = the map's write tools (here `approve_invoice`) + `extract_fields`, `review_status`. Unmapped upstream
  tools (`delete_all_invoices`, and the read helpers `get_record` / `preview_approval`) are not listed; a call is
  `refused` / `unknown_tool` (audited `refuse`) and never forwarded (default deny).
- A proxied tool's arguments are the ActionRequest JSON, exactly as for `payments_approve_invoice`. `args` maps
  upstream param -> ActionRequest arg; the upstream write gets those values + the idempotency key.
- The upstream write is the gate's `execute` step: it runs only after commit passed, inside the commit tx, at most
  once per receipt. `read_record` (`{record_id} -> {data, version}`) and `dry_run` (same args as the write -> diff)
  go to the named upstream read tools (else the local adapter); `sor_for` stays the local system of record. The
  gate mirrors the reported effect on the record row; a reported `applied > 1` moves the version past the approved
  diff -> DENY AP-STALE-07 + burn + quarantine.
- Upstream crash, error result or timeout (`timeout_seconds`, 1..300) -> DENY AP-ERR-11 / G1 (fail closed); a write
  that may have happened burns the receipt and quarantines the record (ADR-014).
- Startup aborts (`ConfigError: ... PROXY_MAP_PATH`, exit 2) on a missing/invalid map (unknown action, arg outside
  the tool's registry, one action twice, reserved or clashing names, extra keys) or a mapped tool the upstream does
  not offer. The upstream process inherits the env minus `SIGNING_KEY_PATH` / `SIGNING_KID`.

### Human review (not an MCP tool)
`review.complete_review(gate, conn_factory, request_hash, reviewer_login, approve, reason) -> ReviewOutcome(status,
reasons)`: for the console backend only, `reviewer_login` = the authenticated session subject. Approve ->
`Gate.mint_review_token` (AP-SEP-12 refusal leaves it `pending`) then `Gate.commit` with the token -> `executed` /
`denied`; reject -> `rejected` with `AP-REV-10 "rejected by reviewer: <reason>"`; a completed review -> AP-REP-05.
`review.park(conn_factory, req, receipt, reasons, res=None)` is the shared REVIEW store (MCP server, and the
LangChain adapter with `review_db=<conn factory>`); `res` (the PrepareResult) adds the reviewer view (card, per-claim
verification, dry-run diff, record before-state). `review.reconcile(conn)` repairs a lost status update: a row still
`pending` whose commit has an EXECUTED audit entry reads as `executed` (every reader calls it first).

REVIEW receipts expire after `REVIEW_RECEIPT_TTL_SECONDS` (default 3600), ALLOW receipts after
`RECEIPT_TTL_SECONDS` (300); AP-EXP-06 / G2 applies to both.

## Review console (HTTP)
Module `actionproof.console` (FastAPI): `python -m actionproof.console [--proxy "<cmd>"]` on
`127.0.0.1:CONSOLE_PORT`. OpenAPI: `/openapi.json`, committed as `web/openapi.json` by `python scripts/gen_openapi.py`
(`--check` fails if stale; UI types are generated from it). Seed users: `python scripts/seed_console.py` (passwords
from `CONSOLE_PASSWORD_<LOGIN>` env, else generated and printed ONCE; only argon2id hashes are stored; never
commit a password).

### Auth
- `POST /api/auth/login {login, password}` -> `{login, roles, csrf_token}` + cookies `ap_session` (random id;
  httpOnly, SameSite=Strict, Secure on https / `CONSOLE_COOKIE_SECURE`) and `ap_csrf` (readable by the page).
  The database stores only sha256(session id); a login always mints a new id and deletes the presented one.
  Bad login or password -> 401 `invalid_credentials` (identical for unknown logins). 5 failures per (login, client
  IP) -> 429 `rate_limited` for 300 s (`# ponytail`: in-memory, per process).
- `POST /api/auth/logout`, `GET /api/auth/me` -> `{login, roles}`. Sessions expire after `SESSION_TTL_SECONDS`;
  a disabled user's sessions stop working at once.
- Every POST except login needs header `X-CSRF-Token` = the `ap_csrf` cookie = the session's token, else 403 `csrf`.
- Roles from `people.roles`: reads need `reviewer` or `admin`; a decision needs `reviewer` (admin cannot, ADR-008).
  No session -> 401 `unauthenticated`; wrong role -> 403 `forbidden`.

### Endpoints
| Method, path | Role | Returns |
|---|---|---|
| `GET /api/queue?status=&tool=&actor=&limit=&cursor=` | reviewer/admin | `{items: [{request_hash, tool, actor, on_behalf_of, status, created_at, amount, top_rule, reasons, reviewer, decided_at}], next_cursor}`; newest first; `limit` 1..100 (50); opaque cursor |
| `GET /api/requests/{request_hash}` | reviewer/admin | `{label: "requested by <actor> for <on_behalf_of>", card, claims: [{name, claim, value, evidence, taint, source {doc, page, bbox} or {doc, pointer}, derivation {fn, inputs}, doc_sha256, verification {ok, method, reason}}], taint_flags, policy_reasons, outcome_reasons, diff, before {data, version}, status, ...}`. ASSERTED claims have `evidence: false` (shown, never evidence). No receipt/signature material |
| `GET /api/requests/{request_hash}/page/{n}.png?doc=` | reviewer/admin | PNG of page n (zoom 2) with a rectangle on every DIRECT claim of this request citing (doc, n) that passed verification. `doc` must be a document-store id (manifest key, never a path) of a PDF; anything else 404 |
| `POST /api/requests/{request_hash}/decision {decision: approve\|reject, reason: 8..500 chars}` | reviewer + CSRF | `{outcome: EXECUTED\|DENY\|REJECTED, status, reasons}` after the commit outcome. Reviewer = session login only; extra body fields (e.g. `reviewer_login`) -> 422. Same person -> DENY AP-SEP-12 (stays pending); decided before -> DENY AP-REP-05; unknown hash -> 404 |
| `GET /api/audit/verify` | reviewer/admin | `{ok, entries, checkpoints, error}` from `audit.verify` (library, one read-only snapshot, gate public key) |
| `GET /api/audit?limit=` | reviewer/admin | `{items: [{seq, ts, kind, request_hash, actor, on_behalf_of, record_id, decision, rules, detail, entry_hash}]}`, newest first; `detail` allowlisted (no nonce, no idempotency key) |
| `GET /api/public/replay/inv-2048` | none, rate-limited | the stored INV-2048 decision: `{card, claims, reasons, decision, status, reviewer, decided_at, audit {first_seq, last_seq}, ...}`, no receipt; 404 before one exists |
| `GET /api/public/eval` | none, rate-limited | `{available: true, results}` from `eval/results.json`, else `{available: false}` |
| `GET /api/health` | none | `{ok: true}`, 503 if the database is down |

### Errors, headers, CORS, rate limits
Every error is `{"error": {"code", "message"}}` (no input echo, no traceback): 401 `unauthenticated` /
`invalid_credentials`, 403 `forbidden` / `csrf`, 404 `not_found`, 422 `validation_error`, 429 `rate_limited`,
500 `internal`, 503 `unavailable`. Every response: `Content-Security-Policy: default-src 'none'; frame-ancestors
'none'; ...`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`,
`Cache-Control: no-store`. CORS: only `WEB_ORIGIN`, with credentials, methods GET/POST, headers Content-Type and
X-CSRF-Token. Public endpoints: `RATE_LIMIT_PER_MINUTE` per client IP.
