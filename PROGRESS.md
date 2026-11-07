# PROGRESS

## Phase 1 — Foundation: gate passed (no-Docker path)
- Built: pyproject + uv env, compose (postgres, opa sidecar), policy stub, all Phase 1 docs, DECK_TRACE, subagents, Tesseract 5.5.3, local OPA 1.22.2 + Postgres 16.9 binaries.
- Check: `pytest tests/test_infra.py tests/test_smoke.py -v` -> 3 passed (Postgres reachable on :5433, OPA reachable and default-denies on :8181).
- Caveat: `docker-compose.yml` was NOT exercised (Docker Desktop engine would not start; onboarding terms need the user). Phase 8 gate requires `docker compose up` from a fresh clone, so that stays open.
- USP: the default is closed — OPA answers DENY to empty input, so nothing is permitted until a rule proves it (G1 posture).

## Phase 2 — Claims (W1): code gate passed
- Built: contracts.py (strict, RFC 8785), fixtures (53 docs, manifest, hero), extract.py (pdfplumber + raster/OCR dual check, JSON pointer), verify.py (DIRECT/DERIVED/ASSERTED, taint, fail closed, unknown args denied), THREAT_MODEL, TESTING.
- Check: `python -m uv run pytest -q -m "not infra"` -> 212 passed, 2 deselected (run by controller, not only by subagents). OCR agreed with the text layer on 27/27 fixture totals.
- USP: G1 proven for the claim layer: a value that does not re-extract at its cited span, a wrong document hash, a model-claimed derived value (501.00), an ASSERTED money field, a doc-tainted authority field and an unknown argument all fail verification with rule AP-VER-01 / G1; no verifier error can pass.
- Open issues: OCR may read `$` as `S` on other machines (fails closed); exact-compare means a dropped comma becomes a false block (measure in Phase 6); gate decision of ALLOW/REVIEW thresholds is Phase 3 (variance = invoice - po, AP-INV-04 on abs(variance) > 100).
- Next: Phase 3 (needs Docker for OPA and Postgres).

## Phase 3 — Gate (W2): gate passed after one red-team round
- Built: policy/actionproof.rego (AP-VER-01, AP-SCOPE-02, AP-CUM-03, AP-INV-04) + 24 opa tests, policy.py (200 ms, fail closed), config/signing/schema (Postgres), mocks (payments/ERP/vendor, hostile modes), gate.py prepare/commit (serializable, one commit lane, signed one-use receipts), quarantine on burned receipts, DATA_MODEL/POLICY/ARCHITECTURE, ADR-010..014.
- Red team (Opus 5.5, tests/redteam/): 14 of 35 attacks BROKE the first build (variance derivation not pinned, unauthenticated actor/on_behalf_of, no fresh re-check at commit, burned receipt left the invoice open). All fixed; tests/redteam is now a permanent regression suite (37 tests).
- Checks (controller, sequential): `opa test policy` PASS 24/24; `pytest -q -m "not infra"` -> 470 passed, 2 deselected (3:00); `pytest tests/usp tests/redteam` -> 144 passed. Two suites run concurrently also pass (per-session temp database).
- USP: G1 — a write cannot execute unless the variance is exactly sub(invoice.total, po.total) over system-of-record-equal DIRECT claims, identity comes from the transport, and the policy decision is re-derived from fresh state at commit. G2 — a receipt/nonce/idempotency key/review token is single-use (DB UNIQUE), expires, binds request hash + record version; a burned receipt quarantines the record so it cannot be re-approved under a new key.
- Open issues: PO total is read through a separate connection at commit and not row-locked (small window, ponytail); one global commit lane (throughput); burn-step failure leaves only the tool-side idempotency; `mint_review_token` caller authentication and reviewer != submitter wait for ADR-008 (Phase 4); the transport must build the Principal from the authenticated session (Phase 5); docker-compose still unexercised.
- Next: Phase 4 (llm-council: ADR-008, ADR-009), then Phase 5.

## Phase 4 — Decisions: done
- Council (5 advisors, 5 anonymized peer reviews, Opus chairman): ADR-008 reviewer must be a different PERSON than the submitters, checked against directory person ids (people table), at token mint AND inside commit (rule AP-SEP-12, G2); admin cannot mint; break-glass and per-threshold config rejected. ADR-009 second connector = refund (payments.refund_payment), demo state seeded by scripts/demo_seed.py. Transcript: docs/council/.
- USP: G2 — approvals cannot be self-granted: the human who unlocks a REVIEW is a different verified person, and the check repeats at commit so a minted token cannot be replayed into a context where the separation fails.
- Open: nothing blocking; implementation is Phase 5 tasks.
