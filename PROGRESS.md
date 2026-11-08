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

## Phase 5 — Surface (W3): done
- Built: MCP server (stdio + HTTP bearer, default deny, refuse audit, rate limit), proxy mode `--proxy`, LangChain adapter + offline example agent, hash-chained audit with signed checkpoints and verifier CLI, console backend (argon2 sessions, CSRF, queue/detail/page PNG with the cited box, decisions, public replay and eval), review parking, `web/openapi.json`, refund connector (ADR-009), `scripts/demo_seed.py`, `demo.sh`.
- Check (HEAD): `pytest` 742 passed; `opa test policy` 46/46. Slide-1 card reproduced byte for byte over MCP stdio and LangChain (tests/e2e/).
- USP: G1 — the front door denies by default (unknown tool, malformed, unmapped upstream tool all refused and audited with 0 tool calls) and no secret (seed, signature, nonce, token) is reachable from any listing; G2 — a reviewer decision comes only from the server-side session and the audit chain detects edit, delete and reorder.
- Open issues: the console UI half of S9.2/S9.6/S7.8 rests on e2e specs that have not run.
- Next: Phase 6.

## Phase 6 — Proof (W4): done, with one blocked row
- Built: eval harness `eval/` (5 arms: no_gate, schema_only, llm_judge, policy_gateway, actionproof), 211 attacks over 7 classes (handwritten 93 + handwritten2 118), 120 benign cases, probe-derived capability table, report to docs/EVAL.md, extract perf work (ADR-018), per-person cumulative cap (ADR-016), 127.0.0.1 for OPA and Postgres (localhost cost about 2 s on Windows).
- Check (eval/results.json, commit 3eb62f3, clean): attacks executed no_gate 190/211, schema_only 182/211, llm_judge 114/211, policy_gateway 97/211, actionproof 0/211 (0/93 handwritten, 0/118 handwritten2). False blocks of 120 benign: no_gate 0, schema_only 0, llm_judge 43 (35.8%), policy_gateway 31 (25.8%; 30 are OPA REVIEW mapped to deny), actionproof 1 (0.83%). Added p95: actionproof 140 ms, llm_judge 2631 ms, policy_gateway 47 ms. targets_met.all = true on handwritten2.
- USP: G1/G2 measured, not asserted: across seven attack classes no attack executed through the real gate, where the no-gate arm executed 90%.
- Open issues: the independent attack generator was blocked (stopped twice by a safety classifier), so DECK_TRACE S6.9 stays blocked and the "held-out" set is handwritten2, held-out-ish and NOT independent; benign-ref-var-05 is a genuine false block under the per-person refund cap; baselines are simplified implementations, not products.
- Next: decide how to source the generated half, if at all.

## Phase 7 — Product UI: built, e2e unrun
- Built: Next.js 16 site and console (design system "Interlock", typed API client generated from OpenAPI, validated env), public site, /evaluation from /api/public/eval, review console with source-span overlays, security headers, Playwright specs (login, review, replay) and Lighthouse budgets.
- Check: Playwright specs have NOT been run; axe 0 violations (reported by the final redesign check; no committed artifact).
- USP: G1 — a reviewer decides from per-claim verification and the cited span, and ASSERTED text is flagged `evidence: false`; G2 — decisions go through the single-use token path.
- Open issues: e2e specs unrun; Lighthouse budgets unrun; mobile LCP not measured on a real device; the COOP header slows first paint in headless Chromium.
- Next: install `@playwright/test` and `@axe-core/playwright`, run `playwright test` against the full stack.

## Phase 8 — Ship: authored, not exercised
- Built: Dockerfiles, full-stack `docker-compose.yml`, `.github/workflows/ci.yml` (first job "USP: proof before permission") and `eval.yml`, RUNBOOK, DEMO, README (USP first line, five steps, honest disclosures, slide-10 limits).
- Check: slide-10 limit wording verified verbatim in README.md, docs/RUNBOOK.md and web/lib/site-copy.ts (grep). Compose and CI were never run.
- USP: G1 — the design keeps the signing key out of the agent's reach (tests/usp/test_key_isolation.py); the compose mount layout is authored, untested.
- Open issues: `docker compose up` from a fresh clone never run (no Docker engine on the build machine); no green CI run yet.
- Next: first fresh-clone compose up, first CI run.

## Redesign and video
- Built: Airlock redesign of the site (5 chapters, scroll-into-the-gate scene), simplified /evaluation and console, critic fixes (meta and og image, closing band, footer, stable gate stage, static step posters, login motif, gap cards, rail a11y); Remotion explainer (video/, output video-out/actionproof-demo.mp4).
- Check: blind critic score 7.2 before fixes (not re-scored after); axe 0 violations; video 3:25.06, 1080p, 30 fps, silent with captions, real demo log and site/console footage (docs/VIDEO.md).
- USP: the video and site show only measured numbers (fetched from the backend or eval/results.json) and the demo log is the real run.
- Open issues: video has minor flaws; the COOP header slows first paint in headless Chromium.
- Next: a final pass on the video flaws if time allows.

## Open issues (honest list)
- Independent attack generator blocked; held-out set is handwritten2 (NOT independent).
- Docker compose never run here; no green CI run exists yet.
- Playwright e2e specs written, never run; Lighthouse and real-device mobile LCP not measured.
- COOP header slows first paint in headless Chromium.
- benign-ref-var-05: genuine false block under the per-person cap (1/120).
- Video minor flaws; the blind critic 7.2 was before fixes.
