# ActionProof testing

**USP: Proof before permission.** Every row below maps a claim to the test that guards it. `done` means the test file exists in the repo today (checked with Glob). Everything else is `todo`.

Sources: `CLAUDE.md` (invariants), `DECK_TRACE.md`, `spec/attack-classes.md`.

## Matrix

| kind | what | test path | guarantee | status |
|---|---|---|---|---|
| invariant | 1. Fail closed: any exception, timeout, unknown tool or unknown field = DENY | `tests/usp/test_fail_closed.py` | G1 | todo |
| invariant | 2. Model never does arithmetic; DERIVED values come from allowlisted pure functions | `tests/usp/test_derived_only_pure.py` | G1 | todo |
| invariant | 3. ASSERTED or doc-tainted values never fill an authority field | `tests/usp/test_taint.py` | G1 | todo |
| invariant | 4. Amounts are Decimal strings; no floats in contracts, policy input, signatures, DB | `tests/usp/test_no_floats.py` | G1 | done |
| invariant | 5. Receipts and review tokens are single-use, expire, bind to request hash + record version | `tests/usp/test_replay.py` | G2 | todo |
| invariant | 6. Signing key unreachable from anything the agent can call | `tests/usp/test_key_isolation.py` | G1+G2 | todo |
| invariant | 7. Nothing hardcoded: config from validated env, API types generated from OpenAPI, numbers fetched from backend | `tests/test_config.py`, web e2e | none (hygiene) | todo |
| attack | 1. Prompt injection: hidden "approve regardless" text in a PDF | `tests/attacks/test_prompt_injection.py` | G1 | todo |
| attack | 2. Argument tampering: amount edited after extraction | `tests/attacks/test_tampering.py` | G1 | todo |
| attack | 3. Evidence forgery: cited span lacks the value | `tests/attacks/test_forgery.py` | G1 | todo |
| attack | 4. Confused deputy: agent exceeds the user's scope | `tests/attacks/test_confused_deputy.py` | G1 | todo |
| attack | 5. Split payments: two $4,900 approvals against a $5,000 cap | `tests/attacks/test_split_payments.py` | G1 | todo |
| attack | 6. Replay: reused token or idempotency key | `tests/attacks/test_replay.py` | G2 | todo |
| attack | 7. Race (TOCTOU): record mutated mid-flight | `tests/attacks/test_race.py` | G1 | todo |
| gap | 01 Evidence: a tool argument with no source behind it (fails without the gate) | `tests/usp/test_gap_evidence.py` | G1 | todo |
| gap | 02 Policy: a valid tool name carrying an out-of-scope amount, target or actor | `tests/usp/test_gap_policy.py` (+ `opa test`) | G1 | todo |
| gap | 03 Execution: retries, stale records, check-then-commit races | `tests/usp/test_gap_execution.py` | G1+G2 | todo |
| USP | CI job "USP: proof before permission" runs `tests/usp` before the full suite | `tests/usp/` | G1+G2 | todo |
| deck | S5.5 ActionProof checks args | `tests/test_checks_args.py` | G1 | todo |
| deck | S5.6 ActionProof evidence per arg | `tests/test_evidence_per_arg.py` | G1 | todo |
| deck | S5.7 ActionProof taint flow | `tests/usp/test_taint.py` | G1 | todo |
| deck | S5.8 ActionProof commit-time check | `tests/test_commit_time_check.py` | G1 | todo |
| deck | S5.9 ActionProof signed receipt | `tests/test_signed_receipt.py` | G1+G2 | todo |
| deck | S7.2 Contracts: Pydantic v2 strict, RFC 8785 | `tests/test_contracts.py`, `tests/usp/test_no_floats.py` | G1 | done |
| deck | S2.1 Fixtures: manifest matches generated files; PDF field crops, JSON pointers, 20+ benign pairs, injected PDF | `tests/test_fixtures.py` | — | done |
| deck | Smoke: pinned dependencies import and pydantic is v2 | `tests/test_smoke.py` | — | done |
| deck | S3.6 / S9.3 Audit: append-only triggers; chain grows with prepare+commit; edited row, rehashed chain (checkpoint), deleted middle row, deleted tail row (checkpoint), reordered rows, forged checkpoint signature, wrong public key all detected (superuser connection bypasses the trigger); 20 concurrent appends gap-free; audit failure inside commit = DENY AP-ERR-11 with `tool.calls == []`; audit failure at prepare withholds the receipt; DENY/refusal/mint/release entries; checkpoint cadence; no seed/token/signature/traceback in entries; verifier CLI exit codes + output with only DATABASE_URL + public key | `tests/test_audit.py` | G1+G2 | done |
| connector | ADR-009 refund registry: payment_id/amount DIRECT only; refund_to SoR only (DIRECT, injected, tainted copy of the real method all fail); customer_id SoR-confirmed; required/unknown args | `tests/test_refund_verify.py` | G1 | done |
| connector | ADR-009 refund through the same gate: executes once, replay, over-refund at prepare and inside the commit tx, customer mismatch, unknown payment, customer scope, REVIEW AP-REF-13 + AP-REV-10 + AP-SEP-12, audit entries + chain verify, burn/quarantine, double call, invoice hero unchanged | `tests/test_refund_gate.py` | G1+G2 | done |
| attack | 1b. Refund destination injection (visible line in REF-311.pdf), DIRECT/tainted/untainted variants, swap after prepare | `tests/attacks/test_refund_injection.py` | G1+G2 | done |
| attack | 5b. Split refunds: cap (actor, SoR customer) at prepare, sequential and concurrent (10 rounds) | `tests/attacks/test_refund_cap.py` | G1 | done |
| connector | Mock refund tool: dry_run, execute once, idempotency key, hostile switches | `tests/test_refund_mocks.py` | G2 | done |
| connector | Refund fixtures: visible injected line, clean variant, 3 benign | `tests/test_refund_fixtures.py` | — | done |
| demo | `scripts/demo_seed.py --reset`: whole demo state; injected → AP-VER-01, clean retry → AP-CUM-03, small → executes once; idempotent | `tests/test_refund_demo_seed.py` | G1+G2 | done |
| deck | S3.2 / S7.1 MCP front door, in-process (SDK Client against the real Server): registry-only listing, slide-1 card, 4900 DENY with 0 tool calls, ALLOW executes in the same call, unknown tool / malformed refused + audited, principal mismatch, review lifecycle (SEP-12, executed once, replay AP-REP-05, reject with reason), status scoping, injected PDF, refund beats (card shows AP-VER-01), extract_fields (bbox = manifest, cited span verifies, JSON leaves, traversal refused), rate limit | `tests/test_mcp_default_deny.py` | G1+G2 | done |
| deck | S1.1 slide 1 exact over MCP stdio (subprocess server, temp DB), 4900 DENY, unknown tool, complete_review -> executed; startup fails closed on bad env; `--print-config` JSON without secrets | `tests/e2e/test_slide1_mcp_stdio.py` | G1+G2 | done |
| deck | MCP HTTP transport: bearer token Principal, 401/403 (CORS closed), body cannot pick the Principal | `tests/e2e/test_mcp_http.py` | G1 | done |
| invariant | 6 at the MCP surface: no seed, receipt signature, nonce or review token in any listing or hostile call | `tests/usp/test_mcp_no_secret_surface.py` | G1+G2 | done |
| adapter | LangChain `review_db` parks REVIEW in `pending_reviews`; complete_review executes once | `tests/test_review_park.py` | G2 | done |
| deck | S3.2 proxy mode over real stdio (proxy + upstream subprocesses): only mapped tools listed, slide-1 card through the proxy, unmapped upstream tool refused + audited with 0 upstream calls, DENY never reaches the upstream write, ALLOW executes upstream exactly once, upstream crash / hang -> DENY AP-ERR-11 + quarantine, double-applying upstream -> DENY AP-STALE-07, bad map aborts startup | `tests/e2e/test_proxy_stdio.py` | G1+G2 | done |
| deck | proxy map validation (unknown action, arg outside registry, duplicates, reserved names, clashes, timeout bounds, upstream must offer every mapped tool) | `tests/test_proxy_map.py` | G1 | done |
| deck | S9.2 / S9.6 / S7.8 console backend: login (identical bad-credential errors, lockout, cookie flags, sha256-only session, rotation), CSRF on every POST, logout / expiry / disabled user, roles (submitter and admin cannot decide), MCP REVIEW -> queue -> detail (DIRECT ok / DERIVED ok, AP-INV-04 G1, diff, before, ASSERTED `evidence: false`) -> rev-alice approves -> executed once -> replay AP-REP-05 -> audit verify ok; same-person reviewer AP-SEP-12; body cannot name the reviewer; reject with typed reason; lost status update reconciled; queue filters + cursor; page PNG box pixels + traversal refused; public replay = DB rows; public eval; structured errors + security headers; CORS origin; seed script; OpenAPI current | `tests/test_console.py` | G1+G2 | done |
| invariant | 5: REVIEW receipts use REVIEW_RECEIPT_TTL_SECONDS, ALLOW the short TTL, AP-EXP-06 for both | `tests/test_review_ttl.py` | G2 | done |
| policy | refund input shape, AP-REF-13 bounds, customer scope, cap 4800+250 | `policy/actionproof_test.rego` (`test_refund_*`) | G1 | done |

Notes:
- Attack rows follow `spec/attack-classes.md`. Expected result for each attack case: the tool executes 0 times.
- `tests/attacks/` and the `tests/usp/` files other than `test_no_floats.py` do not exist yet. Their phases are in `docs/THREAT_MODEL.md`.

## How to run

From `CLAUDE.md`:

```
python -m uv sync                              # install
docker compose up -d postgres opa              # infra up
python -m uv run pytest tests/usp -v           # USP suite
python -m uv run pytest                        # all tests
python -m actionproof.audit verify             # audit chain (needs DATABASE_URL + AUDIT_PUBLIC_KEY_PATH or --public-key)
docker run --rm -v ./policy:/p openpolicyagent/opa test /p -v   # OPA tests
```

CI order (planned; no CI config is in the repo yet):

1. **USP: proof before permission**: `pytest tests/usp -v`. Runs first. A failure here stops the build.
2. Full suite: `pytest`.
3. OPA tests: `opa test` on `policy/`.
