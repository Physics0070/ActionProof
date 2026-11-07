# ActionProof policy

Policy-time rules live in `policy/actionproof.rego` (package `actionproof`, Rego v1, OPA 1.22). The OPA
client is `src/actionproof/policy.py` (`decide(payload) -> Decision`). Commit-time rules are enforced in
`gate.commit` (design: `.superpowers/sdd/phase3/design.md`). Every DENY/REVIEW reason is
`{"rule", "guarantee", "msg"}`.

Run: `C:/Users/Soham/tools/opa/opa.exe test policy -v` and `python -m uv run pytest tests/test_policy.py -q`.

## Input shape (two tools, ADR-009)

Both tools share every rule; only the counterparty differs. The gate fills it from the system-of-record record,
never from the request.

| tool | args | scope | counterparty (cap key with `actor`) | REVIEW rule |
|---|---|---|---|---|
| `payments.approve_invoice` | `amount`, `variance`, `vendor_id` | `max_amount`, `vendors` | invoice record `vendor_id` | AP-INV-04 |
| `payments.refund_payment` | `amount`, `customer_id` | `max_amount`, `customers` | payment record `customer_id` | AP-REF-13 |

Common: `tool`, `actor`, `on_behalf_of`, `verify {ok, reasons}`, `cumulative {committed, person_committed}` (both
required 2dp strings; a missing `person_committed` is malformed, DENY AP-VER-01, ADR-016). Rego reads the
counterparty through `counterparty` / `scope_ids` / `counterparty_kind` (per tool); an input with the other tool's
scope list is malformed (`test_refund_does_not_read_vendor_scope`, `test_invoice_does_not_read_customer_scope`).
Invoice inputs and reason texts are unchanged.

## Rules

| Rule | Where | Condition | Outcome | G | Proven by |
|---|---|---|---|---|---|
| AP-VER-01 | Rego | `verify.ok == false` | DENY | G1 | `test_ver01_verify_false_deny`, `test_refund_verify_false_deny`; pytest `test_ver01_verification_failed` |
| AP-VER-01 | Rego | input malformed: tool is neither `payments.approve_invoice` nor `payments.refund_payment`; actor/on_behalf_of/counterparty not strings; verify.ok not boolean; any money field not `^-?\d+\.\d{2}$`; amount <= 0.00; the tool's scope list (`vendors` / `customers`) not an array of strings; invoice without `variance`; any field missing | DENY | G1 | `test_ver01_empty_input_deny`, `test_ver01_float_amount_deny`, `test_ver01_bad_money_strings_deny`, `test_ver01_bad_variance_deny`, `test_ver01_nonpositive_amount_deny`, `test_ver01_unknown_tool_deny`, `test_ver01_missing_scope_deny`, `test_refund_malformed_shapes_deny`; pytest `test_ver01_malformed_money`, `test_ver01_empty_input` |
| AP-SCOPE-02 | Rego | `amount > scope.max_amount` | DENY | G1 | `test_scope02_amount_equal_max_allow` (== max ALLOW), `test_scope02_amount_max_plus_cent_deny`, `test_refund_amount_over_scope_max_deny`; pytest `test_scope02_amount_over_max` |
| AP-SCOPE-02 | Rego | counterparty not in the tool's scope list: "vendor not in on_behalf_of scope" / "customer not in on_behalf_of scope" | DENY | G1 | `test_scope02_vendor_out_of_scope_deny`, `test_refund_customer_out_of_scope_deny`; pytest `test_scope02_vendor_out_of_scope`, `tests/test_refund_gate.py::test_refund_customer_out_of_scope_denied` |
| AP-VER-01 | verify.py (ADR-009) | refund: `payment_id` / `amount` not DIRECT; `refund_to` DIRECT, doc-tainted (even when equal to the record) or != payment `method_id`; `customer_id` ASSERTED and != payment customer | DENY | G1 | `tests/test_refund_verify.py`, `tests/attacks/test_refund_injection.py` |
| AP-VER-01 | gate.prepare + gate.commit (ADR-009) | refund: payment not in the SoR; `customer_id` / `refund_to` != the payment record; `amount > payment.amount − committed refunds on that payment` (re-read inside the commit tx under the commit lock) | DENY | G1 | `tests/test_refund_gate.py::test_amount_over_remaining_denied_at_prepare`, `test_amount_over_remaining_denied_inside_the_commit_tx`, `test_customer_id_mismatch_denied`, `test_unknown_payment_denied` |
| AP-SCOPE-02 | gate.prepare / gate.commit (ADR-012) | `req.actor` / `req.on_behalf_of` != the transport's `Principal` ("identity not bound to caller") | DENY | G1 | `tests/test_commit.py::test_identity_bound_to_transport_principal`, `tests/redteam/test_rt_g1_authority.py` |
| AP-VER-01 | gate.prepare / gate.commit (ADR-013) | `variance` not DERIVED `sub(invoice.total, po.total)`, an ASSERTED derivation input, or variance != SoR invoice.total − po.total | DENY | G1 | `tests/test_verify.py::test_variance_pinned_and_asserted_never_an_input`, `tests/redteam/test_rt_g1_claims.py` |
| AP-CUM-03 | Rego (advisory, at prepare) | `cumulative.committed + amount > 5000.00`, committed = SUM for (transport actor, SoR counterparty); msg "actor+vendor ..." / "actor+customer cumulative total exceeds 5000.00" | DENY | G1 | `test_cum03_0_plus_4900_allow`, `test_cum03_4900_plus_4900_deny`, `test_cum03_100_plus_4900_equal_cap_allow`, `test_cum03_cap_plus_cent_deny`, `test_refund_cum03_demo_4800_plus_250_deny`, `test_refund_cum03_equal_cap_allow`, `test_refund_cum03_cap_plus_cent_deny`; pytest `test_cum03_over_cap`, `tests/attacks/test_refund_cap.py::test_cap_denies_at_prepare` |
| AP-CUM-03 | Rego (advisory, at prepare, ADR-016) | actor cap holds AND `cumulative.person_committed + amount > 5000.00`, person_committed = SUM for (person behind `on_behalf_of`, SoR counterparty); person = `people.person_id` of the on_behalf_of login, else the on_behalf_of string; msg "person+vendor ..." / "person+customer cumulative total exceeds 5000.00". When both caps trip, only the actor reason is returned (one AP-CUM-03 reason) | DENY | G1 | `test_cum03_person_equal_cap_allow`, `test_cum03_person_cap_plus_cent_deny`, `test_cum03_person_only_trips`, `test_cum03_actor_only_trips`, `test_cum03_both_trip_one_reason`, `test_cum03_person_committed_required`, `test_refund_cum03_person_cap_plus_cent_deny`; pytest `test_cum03_person_cap_actor_rotation`, `test_missing_person_committed_denied` |
| AP-CUM-03 | gate.commit (authoritative, ADR-006/016) | both sums re-read inside the SERIALIZABLE tx under the commit lock, actor first then person (refunds too: same lane, key from the locked payment record) | DENY | G1 | Phase 3 gate tests; `tests/attacks/test_refund_cap.py::test_concurrent_refunds_one_executes`, `test_sequential_refunds_capped_at_commit`, `test_other_agent_for_the_same_person_counts`; `tests/redteam/test_rt_g1_rotation.py` |
| AP-INV-04 | Rego | invoice: `abs(variance) > 100.00` | REVIEW | G1 | `test_hero_review_inv04`, `test_inv04_variance_100_00_allow`, `test_inv04_variance_100_01_review`, `test_inv04_variance_negative_100_01_review`, `test_inv04_variance_negative_100_00_allow`, `test_inv04_variance_negative_500_review`, `test_refund_ignores_variance_rule`; pytest `test_hero_review_inv04`, `test_allow_when_variance_within_limit` |
| AP-REF-13 | Rego (ADR-009) | refund: `amount > 1000.00` ("refund amount exceeds 1000.00"); needs a human review token (AP-REV-10), minted by a different person (AP-SEP-12, unchanged) | REVIEW | G1 | `test_refund_ref13_1000_00_allow`, `test_refund_ref13_1000_01_review`, `test_refund_deny_beats_ref13_review`, `test_invoice_large_amount_no_ref13`; `tests/test_refund_gate.py::test_review_above_1000_needs_a_token_from_a_different_person`, `test_refund_at_1000_is_allow` |
| AP-DEFAULT | Rego | decision undefined (evaluation error) | DENY | G1 | backstop only: every input today resolves to a defined decision (empty input is AP-VER-01, `test_ver01_empty_input_deny`) |
| AP-POL-FAIL | policy.py | OPA_URL unset, connect error, > 200 ms, non-200, missing/unknown outcome, malformed reasons, DENY/REVIEW without reasons, float or non-dict payload | DENY | G1 | pytest `test_missing_opa_url_denied`, `test_closed_port_denied`, `test_slow_server_denied`, `test_trickling_server_denied`, `test_malformed_opa_response_denied[*]`, `test_float_in_payload_denied_before_opa` |
| AP-SIG-09 | gate.commit | receipt signature invalid | DENY | G2 | Phase 3 gate tests |
| AP-HASH-08 | gate.commit | request hash != receipt.request_hash | DENY | G2 | Phase 3 gate tests |
| AP-EXP-06 | gate.commit | receipt/token expired. Receipt `exp` = prepare time + `REVIEW_RECEIPT_TTL_SECONDS` (default 3600) for a REVIEW receipt, + `RECEIPT_TTL_SECONDS` (default 300) for ALLOW | DENY | G2 | Phase 3 gate tests, `tests/test_review_ttl.py` |
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

- `cap_cents := 500000` (5000.00), cumulative cap per actor+counterparty AND per person+counterparty (vendor or customer, ADR-015/016). `# ponytail: constant, move to data.json if per-tenant caps are needed`.
- `variance_limit_cents := 10000` (100.00). 100.00 is ALLOW, 100.01 is REVIEW.
- `refund_review_cents := 100000` (1000.00, AP-REF-13). 1000.00 is ALLOW, 1000.01 is REVIEW.

## Variance sign

`variance = invoice.total - po.total` (computed by verify's allowlisted pure function, never by the
model). It is pinned (ADR-013): only `DERIVED sub(invoice.total, po.total)` over DIRECT/DERIVED/SoR inputs is
accepted, and its value must equal the system-of-record difference at prepare and again at commit. The policy uses `abs(variance)`, so over- and under-billing by more than 100.00 both go to REVIEW.

## Timeout

`policy.py` uses one process-wide httpx client (timeout 0.2 s per phase, `trust_env=False`) and a 200 ms
deadline checked per response chunk. `# ponytail`: a trickling server is bounded at ~2x the deadline;
a hard wall clock needs a worker thread or async cancel.
