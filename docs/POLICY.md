# ActionProof policy

Policy-time rules live in `policy/actionproof.rego` (package `actionproof`, Rego v1, OPA 1.22). The OPA
client is `src/actionproof/policy.py` (`decide(payload) -> Decision`). Commit-time rules are enforced in
`gate.commit` (design: `.superpowers/sdd/phase3/design.md`). Every DENY/REVIEW reason is
`{"rule", "guarantee", "msg"}`.

Run: `C:/Users/Soham/tools/opa/opa.exe test policy -v` and `python -m uv run pytest tests/test_policy.py -q`.

## Rules

| Rule | Where | Condition | Outcome | G | Proven by |
|---|---|---|---|---|---|
| AP-VER-01 | Rego | `verify.ok == false` | DENY | G1 | `test_ver01_verify_false_deny`; pytest `test_ver01_verification_failed` |
| AP-VER-01 | Rego | input malformed: tool is not `payments.approve_invoice`; actor/on_behalf_of/vendor_id not strings; verify.ok not boolean; any money field not `^-?\d+\.\d{2}$`; amount <= 0.00; scope.vendors not an array of strings; any field missing | DENY | G1 | `test_ver01_empty_input_deny`, `test_ver01_float_amount_deny`, `test_ver01_bad_money_strings_deny`, `test_ver01_bad_variance_deny`, `test_ver01_nonpositive_amount_deny`, `test_ver01_unknown_tool_deny`, `test_ver01_missing_scope_deny`; pytest `test_ver01_malformed_money`, `test_ver01_empty_input` |
| AP-SCOPE-02 | Rego | `amount > scope.max_amount` | DENY | G1 | `test_scope02_amount_equal_max_allow` (== max ALLOW), `test_scope02_amount_max_plus_cent_deny`; pytest `test_scope02_amount_over_max` |
| AP-SCOPE-02 | Rego | `vendor_id` not in `scope.vendors` | DENY | G1 | `test_scope02_vendor_out_of_scope_deny`; pytest `test_scope02_vendor_out_of_scope` |
| AP-SCOPE-02 | gate.prepare / gate.commit (ADR-012) | `req.actor` / `req.on_behalf_of` != the transport's `Principal` ("identity not bound to caller") | DENY | G1 | `tests/test_commit.py::test_identity_bound_to_transport_principal`, `tests/redteam/test_rt_g1_authority.py` |
| AP-VER-01 | gate.prepare / gate.commit (ADR-013) | `variance` not DERIVED `sub(invoice.total, po.total)`, an ASSERTED derivation input, or variance != SoR invoice.total − po.total | DENY | G1 | `tests/test_verify.py::test_variance_pinned_and_asserted_never_an_input`, `tests/redteam/test_rt_g1_claims.py` |
| AP-CUM-03 | Rego (advisory, at prepare) | `cumulative.committed + amount > 5000.00` | DENY | G1 | `test_cum03_0_plus_4900_allow`, `test_cum03_4900_plus_4900_deny`, `test_cum03_100_plus_4900_equal_cap_allow`, `test_cum03_cap_plus_cent_deny`; pytest `test_cum03_over_cap` |
| AP-CUM-03 | gate.commit (authoritative, ADR-006) | same sum re-read inside the SERIALIZABLE tx | DENY | G1 | Phase 3 gate tests |
| AP-INV-04 | Rego | `abs(variance) > 100.00` | REVIEW | G1 | `test_hero_review_inv04`, `test_inv04_variance_100_00_allow`, `test_inv04_variance_100_01_review`, `test_inv04_variance_negative_100_01_review`, `test_inv04_variance_negative_100_00_allow`, `test_inv04_variance_negative_500_review`; pytest `test_hero_review_inv04`, `test_allow_when_variance_within_limit` |
| AP-DEFAULT | Rego | decision undefined (evaluation error) | DENY | G1 | backstop only: every input today resolves to a defined decision (empty input is AP-VER-01, `test_ver01_empty_input_deny`) |
| AP-POL-FAIL | policy.py | OPA_URL unset, connect error, > 200 ms, non-200, missing/unknown outcome, malformed reasons, DENY/REVIEW without reasons, float or non-dict payload | DENY | G1 | pytest `test_missing_opa_url_denied`, `test_closed_port_denied`, `test_slow_server_denied`, `test_trickling_server_denied`, `test_malformed_opa_response_denied[*]`, `test_float_in_payload_denied_before_opa` |
| AP-SIG-09 | gate.commit | receipt signature invalid | DENY | G2 | Phase 3 gate tests |
| AP-HASH-08 | gate.commit | request hash != receipt.request_hash | DENY | G2 | Phase 3 gate tests |
| AP-EXP-06 | gate.commit | receipt/token expired | DENY | G2 | Phase 3 gate tests |
| AP-REP-05 | gate.commit | nonce / idempotency key / review token already used | DENY | G2 | Phase 3 gate tests |
| AP-REP-05 | gate.prepare + gate.commit (ADR-014) | target record quarantined after a burned (unknown-outcome) commit | DENY | G2 | `tests/redteam/test_rt_g2_replay.py::test_burned_receipt_*`, `test_receipt_prepared_before_burn_blocked_at_commit` |
| AP-STALE-07 | gate.commit | record version != receipt.version, or diff changed | DENY | G2 | Phase 3 gate tests |
| (fresh policy) | gate.commit (ADR-014) | policy re-decided from CURRENT state inside the commit tx: fresh DENY = DENY with OPA's rule ids (G1); fresh REVIEW on an ALLOW receipt = AP-STALE-07 (G2) | DENY | G1/G2 | `tests/redteam/test_rt_g1_authority.py`, `tests/test_commit.py::test_fresh_policy_*` |
| AP-REV-10 | gate.commit | REVIEW without a valid unused human-minted token bound to the request hash | DENY | G2 | Phase 3 gate tests |
| AP-SEP-12 | gate.mint_review_token + gate.commit (ADR-008) | reviewer login missing from `people`, lacks the `reviewer` role (`admin` cannot mint), submitter is a `team`, or reviewer `person_id` ∈ {person(Principal.actor), person(Principal.on_behalf_of)}; any submitter lookup missing; re-read inside the commit tx after the token is consumed (rollback, token stays unused) | refuse mint (`ReviewRefused`, audited) / DENY | G2 | `tests/redteam/test_rt_sep.py` |
| AP-ERR-11 | gate | any exception, serialization failure after retries, tool error | DENY | G1 | Phase 3 gate tests |

## Precedence

Any DENY wins; else REVIEW; else ALLOW (`test_precedence_deny_beats_review`). All fired DENY reasons are
returned (`test_multiple_denies_all_returned`). `reasons` explains the outcome: a DENY lists only DENY
reasons, a REVIEW only REVIEW reasons, an ALLOW is `[]`.

## Money

Amounts are 2dp decimal strings (invariant 4). Rego converts them to integer cents by splitting on `.`
(sign handled, leading zeros allowed: `test_ver01_leading_zero_money_ok`); no floats are ever compared.
A JSON number in a money field is AP-VER-01; a Python float anywhere in the payload is rejected by
`policy.py` before OPA is called (AP-POL-FAIL).

## Constants

- `cap_cents := 500000` (5000.00), cumulative cap per actor+vendor. `# ponytail: constant, move to data.json if per-tenant caps are needed`.
- `variance_limit_cents := 10000` (100.00). 100.00 is ALLOW, 100.01 is REVIEW.

## Variance sign

`variance = invoice.total - po.total` (computed by verify's allowlisted pure function, never by the
model). It is pinned (ADR-013): only `DERIVED sub(invoice.total, po.total)` over DIRECT/DERIVED/SoR inputs is
accepted, and its value must equal the system-of-record difference at prepare and again at commit. The policy uses `abs(variance)`, so over- and under-billing by more than 100.00 both go to REVIEW.

## Timeout

`policy.py` uses one process-wide httpx client (timeout 0.2 s per phase, `trust_env=False`) and a 200 ms
deadline checked per response chunk. `# ponytail`: a trickling server is bounded at ~2x the deadline;
a hard wall clock needs a worker thread or async cancel.
