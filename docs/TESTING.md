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
docker run --rm -v ./policy:/p openpolicyagent/opa test /p -v   # OPA tests
```

CI order (planned; no CI config is in the repo yet):

1. **USP: proof before permission**: `pytest tests/usp -v`. Runs first. A failure here stops the build.
2. Full suite: `pytest`.
3. OPA tests: `opa test` on `policy/`.
