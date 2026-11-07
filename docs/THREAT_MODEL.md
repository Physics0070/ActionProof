# ActionProof threat model

**USP: Proof before permission.** No value can authorize a write unless its derivation re-checks (**G1**), and no approval can be replayed (**G2**).

Sources: `CLAUDE.md`, `DECK_TRACE.md`, `spec/attack-classes.md`, `spec/actionrequest.md`, `docs/ARCHITECTURE.md`.

Status legend: **built** = code and test exist in the repo today. **planned (Phase N)** = not built yet; phase numbers follow `DECK_TRACE.md` S8.1-S8.4 (W1 Claims = Phase 2, W2 Gate = Phase 3, W3 Surface = Phase 5 and 7, W4 Proof = Phase 6 and 8).

## 1. Assets

| Asset | Why it matters | Protection | Status |
|---|---|---|---|
| Money-moving writes (e.g. `payments.approve_invoice`) | Executing one wrongly moves money | No ALLOW without a re-checked derivation (G1); commit re-checks state before the tool runs (G1) | planned (Phase 3) |
| Signing key (Ed25519, PyNaCl) | Whoever holds it can forge receipts and checkpoints | Key lives only in the gateway; unreachable from agent-callable code (invariant 6, ADR-007) | planned (Phase 3) |
| Audit chain (hash-chained log, signed checkpoints) | The record of what was allowed, reviewed or denied | Append-only triggers; edits, deletes, reorders, a truncated tail and forged checkpoints are detected by `python -m actionproof.audit verify` (public key only) | built (`tests/test_audit.py`) |
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
| 4 | Confused deputy | `on_behalf_of` scope checked in policy (AP-SCOPE-02); actor/on_behalf_of bound to the transport Principal (ADR-012) | `tests/attacks/test_confused_deputy.py` | G1 | planned (Phase 3) |
| 5 | Split payments | Cumulative limits per actor and vendor (AP-CUM-03, `gate.commit`, ADR-006) | `tests/attacks/test_split_payments.py` | G1 | planned (Phase 3) |
| 6 | Replay | One-use token and idempotency key enforced by DB UNIQUE constraints | `tests/attacks/test_replay.py`, `tests/usp/test_replay.py` | G2 | planned (Phase 3) |
| 7 | Race (TOCTOU) | Version precondition checked under `FOR UPDATE` at commit | `tests/attacks/test_race.py` | G1 | planned (Phase 3) |

## 4b. Red-team findings and fixes (Phase 3)

Source: `.superpowers/sdd/phase3/redteam-report.md`. The tests in `tests/redteam/` are a permanent regression suite;
every assertion encodes the safe behavior (the tool is not reached).

| Attack | Guarantee | Fixed by | Test |
|---|---|---|---|
| variance = sub(invoice.total, note) with an ASSERTED note | G1 | ASSERTED never a derivation input; variance pinned (ADR-013) | `tests/redteam/test_rt_g1_claims.py::test_variance_derived_from_asserted_note` |
| variance = sub(invoice.total, invoice.total) | G1 | variance pinned to sub(invoice.total, po.total) (ADR-013) | `test_rt_g1_claims.py::test_variance_self_subtraction` |
| variance = sub(amount, invoice.total) | G1 | variance pinned (ADR-013) | `test_rt_g1_claims.py::test_variance_sub_amount_minus_invoice_total` |
| variance = sub(po.total, po.total) | G1 | variance pinned (ADR-013) | `test_rt_g1_claims.py::test_variance_po_minus_po` |
| DIRECT variance from a self-made calc.json | G1 | variance must be DERIVED; value must equal SoR invoice − PO (ADR-011/013) | `test_rt_g1_claims.py::test_variance_direct_from_selfmade_doc` |
| cap bypass via actor alias (`Agent-7`, `agent-7 `, zero-width, `agent-8`) | G1 | canonical ids in contracts; request identity bound to the transport Principal (ADR-012) | `tests/redteam/test_rt_g1_authority.py::test_cumulative_cap_bypass_by_actor_alias` |
| borrow a richer principal (`on_behalf_of="cfo"`) | G1 | Principal binding, AP-SCOPE-02 (ADR-012) | `test_rt_g1_authority.py::test_borrow_delegated_principal` |
| delegation revoked between prepare and commit | G1 | fresh policy decision inside the commit tx (ADR-014) | `test_rt_g1_authority.py::test_scope_revoked_between_prepare_and_commit` |
| vendor removed from scope between prepare and commit | G1 | fresh policy decision (ADR-014) | `test_rt_g1_authority.py::test_vendor_removed_from_scope_between_prepare_and_commit` |
| PO total changed between prepare and commit | G1 | variance re-checked against the fresh SoR; fresh policy (ADR-013/014) | `test_rt_g1_authority.py::test_po_total_changed_between_prepare_and_commit` |
| burned (unknown-outcome) commit, re-prepared with a new idempotency key | G2 | burn quarantines the record; prepare and commit refuse it, AP-REP-05 (ADR-014) | `tests/redteam/test_rt_g2_replay.py::test_burned_receipt_then_reprepare_with_new_key`, `test_receipt_prepared_before_burn_blocked_at_commit`, `test_release_quarantine_reconciles` |
| `model_construct`-built request at commit (suspicion) | G2 | commit always re-parses the request | `tests/test_commit.py::test_model_construct_request_revalidated_at_commit` |

| self-approval: the submitter's own second reviewer login (`rev-user123` = `p-user123`) mints | G2 | AP-SEP-12 compares `people.person_id`, at mint and inside the commit tx (ADR-008) | `tests/redteam/test_rt_sep.py::test_second_login_of_submitter_cannot_mint`, `test_second_login_token_denied_at_commit` |
| unmapped reviewer or submitter login | G2 | missing directory row fails closed, AP-SEP-12 | `test_rt_sep.py::test_unmapped_reviewer_login_refused`, `test_unmapped_submitter_refused` |
| admin mints a review token | G2 | only the `reviewer` role mints, AP-SEP-12 | `test_rt_sep.py::test_admin_cannot_mint` |
| directory edited after a legitimate mint (reviewer now = submitter person, or role revoked) | G2 | `people` re-read `FOR SHARE` inside the commit tx after the token is consumed; rollback | `test_rt_sep.py::test_directory_edit_after_mint_denied_at_commit`, `test_reviewer_role_revoked_after_mint_denied_at_commit` |
| `on_behalf_of` is a team with no single person | G2 | `team` role fails closed, AP-SEP-12 | `test_rt_sep.py::test_team_on_behalf_of_denied` |

Still open: the global commit lock can DENY legitimate commits under load (availability, not safety).
`mint_review_token` stays human/admin-side only and must not be exposed through MCP/adapters.

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
| Reviewer collusion | Two DIFFERENT people (e.g. the user-123 operator and rev-bob) agree to approve each other's bad write | ADR-008 stops one person approving their own request (AP-SEP-12), not two people colluding. Every token records `minted_by` + `minted_by_person` for the audit trail | accepted (prototype) |
| Reviewer session hijack | An attacker who holds a reviewer's console session mints as that reviewer | The reviewer identity is only the server-side session subject, never a request field (ADR-008); session security is the console's (Phase 5/7). Separation is only as strong as console authentication and the `people` data | accepted (prototype) |
| `people` directory tampering | An admin maps a reviewer login to a different person to pass AP-SEP-12 | Commit re-reads `people` inside the tx, so edits after a mint are caught; every mint entry records `reviewer_login` + `reviewer_person`, so a remap is visible in the chain. The edit itself is not an audit entry until the console backend has an admin edit path | open (console backend) |
| Audit: superuser / owner tampering | The DB owner (the gate's role in dev) can disable the append-only trigger and edit rows | Detection, not prevention: hash chain + gate-signed checkpoints; the verifier needs only the public key (`tests/test_audit.py` edit, rehashed-chain, delete, reorder, forged-signature cases) | accepted (detected) |
| Audit: tail truncation with its checkpoints | Deleting the last k entries AND their checkpoints leaves a shorter, valid chain; emptying both tables verifies as `OK (0 entries, 0 checkpoints)` | Checkpoint every entry by default (`AUDIT_CHECKPOINT_EVERY=1`) so no entry is ever unpinned; the residual needs an external anchor (publish checkpoint heads off-box / to a WORM store) | open (Phase 8 ops) |
| Audit: entries after the last checkpoint | With `AUDIT_CHECKPOINT_EVERY=N>1`, up to N-1 newest entries can be truncated undetected | Default 1; documented in `.env.example` and `config.py` (ponytail) | accepted (default 1) |
| Audit: gate key compromise | Whoever holds the Ed25519 key can re-sign a rewritten chain | Same key as receipts (ADR-007, invariant 6); key rotation + external anchoring is the upgrade path | accepted (prototype) |
| Audit: write availability | A broken audit table DENYs every prepare ALLOW/REVIEW and every commit (fail closed, AP-ERR-11); one audit lock serializes appends and is held for the whole commit tx | Availability, not safety: an audit failure never turns a DENY into an execution (`test_audit_failure_*`) | accepted (prototype) |
