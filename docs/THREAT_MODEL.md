# ActionProof threat model

**USP: Proof before permission.** No value can authorize a write unless its derivation re-checks (**G1**), and no approval can be replayed (**G2**).

Sources: `CLAUDE.md`, `DECK_TRACE.md`, `spec/attack-classes.md`, `spec/actionrequest.md`, `docs/ARCHITECTURE.md`.

Status legend: **built** = code and test exist in the repo today. **planned (Phase N)** = not built yet; phase numbers follow `DECK_TRACE.md` S8.1-S8.4 (W1 Claims = Phase 2, W2 Gate = Phase 3, W3 Surface = Phase 5 and 7, W4 Proof = Phase 6 and 8).

## 1. Assets

| Asset | Why it matters | Protection | Status |
|---|---|---|---|
| Money-moving writes (e.g. `payments.approve_invoice`) | Executing one wrongly moves money | No ALLOW without a re-checked derivation (G1); commit re-checks state before the tool runs (G1) | planned (Phase 3) |
| Signing key (Ed25519, PyNaCl) | Whoever holds it can forge receipts and checkpoints | Key lives only in the gateway; unreachable from agent-callable code (invariant 6, ADR-007) | planned (Phase 3) |
| Audit chain (hash-chained log, signed checkpoints) | The record of what was allowed, reviewed or denied | Edits and deletes are detected by the verifier CLI | planned (Phase 5) |
| Approval tokens (signed receipts, human review tokens) | Each one is permission to write | Single use (DB UNIQUE), expire, bound to `request_hash` and record version (invariant 5, G2) | planned (Phase 3) |

## 2. Actors

| Actor | Trust | Capability we assume |
|---|---|---|
| Agent / LLM | Untrusted | Sends any ActionRequest; can be steered by document text it reads |
| Malicious document author | Untrusted | Plants hidden instructions or false values in PDFs and JSON the agent reads |
| Compromised reviewer | Trusted by role, not by proof | Mints a review token for a bad write (see residual risks) |
| Network attacker on the tool side | Untrusted | Changes upstream records or timing between `prepare` and `commit` |
| Hostile upstream tool | Untrusted (`docs/ARCHITECTURE.md`: "may be hostile") | Returns stale versions, retries, or double-executes a call |

## 3. The three gaps (deck slide 2)

### Gap 01: Evidence
- **What breaks:** a tool argument holds a value with no source field and no document citation behind it.
- **Control:** `verify.py` re-extracts each DIRECT value at its cited page and box and checks the document hash. DERIVED values are recomputed by allowlisted pure functions. ASSERTED values never fill an authority field. The contract shape part (DIRECT needs `src` and `doc_sha256`) is **built**: `tests/test_contracts.py`.
- **Proving test:** `tests/usp/test_gap_evidence.py` (must fail without the gate). Planned (Phase 2).

### Gap 02: Policy
- **What breaks:** a valid tool name still carries an amount, target or actor outside the caller's scope.
- **Control:** `policy/actionproof.rego` rule AP-SCOPE-02 checks `on_behalf_of` scope. OPA default-denies. Planned (Phase 3).
- **Proving test:** `tests/usp/test_gap_policy.py` and `opa test`. Planned (Phase 3).

### Gap 03: Execution
- **What breaks:** retries, stale records and check-then-commit races repeat or invalidate an approved write.
- **Control:** `gate.commit` runs a SERIALIZABLE transaction: signature, expiry, hash, nonce and idempotency UNIQUE constraints (G2), cumulative re-check (ADR-006), `FOR UPDATE` on the version. Planned (Phase 3).
- **Proving test:** `tests/usp/test_gap_execution.py` (retry, stale, race). Planned (Phase 3).

## 4. Attack classes

Expected result for every attack case: the tool executes **0 times** (`spec/attack-classes.md`).

| # | Class | Exact control | Test path | Guarantee | Status |
|---|---|---|---|---|---|
| 1 | Prompt injection | Taint labels; document text never fills authority fields | `tests/attacks/test_prompt_injection.py` | G1 | planned (Phase 2) |
| 2 | Argument tampering | Claims re-verified at the cited span; any change after `prepare` changes `request_hash` and invalidates the receipt | `tests/attacks/test_tampering.py` | G1 | planned (Phase 3) |
| 3 | Evidence forgery | Span re-extraction and document hash match | `tests/attacks/test_forgery.py` | G1 | planned (Phase 2) |
| 4 | Confused deputy | `on_behalf_of` scope checked in policy (AP-SCOPE-02) | `tests/attacks/test_confused_deputy.py` | G1 | planned (Phase 3) |
| 5 | Split payments | Cumulative limits per actor and vendor (AP-CUM-03, `gate.commit`, ADR-006) | `tests/attacks/test_split_payments.py` | G1 | planned (Phase 3) |
| 6 | Replay | One-use token and idempotency key enforced by DB UNIQUE constraints | `tests/attacks/test_replay.py`, `tests/usp/test_replay.py` | G2 | planned (Phase 3) |
| 7 | Race (TOCTOU) | Version precondition checked under `FOR UPDATE` at commit | `tests/attacks/test_race.py` | G1 | planned (Phase 3) |

## 5. Out of scope

Quoted from deck slide 10:

- "Verifier-bound: Only as good as its deterministic verifiers. Free-form judgments can't be proven."
- "Semantic fraud: A fake invoice that looks internally consistent is out of scope."
- "The gate is a target: The signing key must stay out of the agent's reach, and the gateway needs hardening."
- "Safety, not judgment: It stops unauthorized actions. It doesn't guarantee a good business decision."

## 6. Residual risks

| Risk | Effect | Mitigation | Status |
|---|---|---|---|
| OCR misreads cause false blocks | A correct document fails verification, so a legitimate write is denied | Two independent readers must agree (pdfplumber and raster/OCR, ADR-002); disagreement fails closed. This costs availability, not safety | planned (Phase 2) |
| Reviewer collusion | A colluding reviewer mints a review token and approves a bad write | Accepted until ADR-008. ADR-008 is not yet in `docs/DECISIONS.md`, which ends at ADR-007 | open |
