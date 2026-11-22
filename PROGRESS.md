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

## Assurance pass (2026-11-20): failure injection, KeyRegistry, local anchor
- Built: `tests/usp/test_exec_faults.py` (crash before/after the tool call, ambiguous timeout, 8-way same-receipt race with a barrier, audit append failure; fake downstream with its own side-effect log), `tool_reached` marker (ADR-019), `signing.KeyRegistry` (ADR-020), `anchor.LocalAnchor` + `audit verify --anchor --strict` (ADR-021).
- Finding: a process crash after the tool call and before COMMIT let a retry of the same receipt call a non-idempotent downstream a second time (reproduced red, fixed green). Crash-before-call and burn paths unchanged.
- USP: G2 now holds across a process crash for any provider (the receipt cannot reach the tool twice), receipts verify by their own kid across rotation, and deleting the audit tail with its checkpoints is detectable against an anchor (G2 evidence; the same-machine file is not WORM).

## Assurance fix (2026-11-20): marker = full reservation (ADR-022)
- Found in review: the ADR-019 marker did not count toward caps and did not hold the request idempotency key (a second receipt with the same key on another record EXECUTED: reproduced red).
- Fixed: `tool_reached` carries the complete reservation, view `reservations` feeds the four cap sums, key UNIQUE, `release_quarantine(record, reviewer, executed)` reconciles. Tests: `tests/usp/test_exec_reservations.py` (cap after a crashed $4,900, same-key new receipt, refund cap, DB unique backstop, retention until release, audit accuracy, real process kill with a file-backed downstream).
- USP: G1+G2 hold across a hard crash: an unknown outcome keeps its money and its key until a human decides, and the audit chain never says it succeeded.

## Assurance hardening (2026-11-20, ADR-023)
- Fixed: duplicate public keys across kids are refused; `KeyRegistry.signature_valid` (crypto) is separate from `verify` (trust, fail closed for revoked/unknown); `LocalAnchor` publish/entries are serialized by a cross-process file lock (the two new concurrent-publisher tests were red without it). The kill test now recovers in a newly initialised Gate process.
- Already done and re-checked against the review list (ADR-022): full reservation in `tool_reached`, UNIQUE idempotency key, `reservations` view in all cap sums, audited release.
- USP: the key a receipt names is the only key that can vouch for it, and the anchor chain survives concurrent writers.

## Assurance gate: legacy markers fail closed, docs corrected (2026-11-20, ADR-024)
- Built: legacy unresolved `tool_reached` rows (NULL amount/actor/counterparty/key, left by the ADR-019 version) never count as zero: while one exists every cap-sensitive prepare and commit DENYs with AP-CUM-03 / G1; `release_quarantine(record, reviewer, executed, reservation)` is the audited reconciliation (attest not executed, or supply the missing facts). `tests/usp/test_migration_legacy_marker.py` restores the pre-ADR-022 shape, runs the real migration (`db.apply_schema`, idempotent) and covers the block, both release paths, bad input and a partially filled row.
- Docs: ARCHITECTURE sequence diagram now shows the marker connection, the reservation and the unresolved-execution branch (plus commit steps 4b/4c); DATA_MODEL separates committed from unresolved reservations and puts refund balances over `reservations`; THREAT_MODEL no longer labels built G1/G2 controls "planned" (each now names its passing tests); ADR-024; DECK_TRACE rows A1-A10 added after the deck rows, existing rows untouched.
- Check (real runs on this machine, standing local OPA for test_infra): full suite `800 passed in 664.97s`; `tests/usp` `132 passed`; `opa test policy` `PASS: 46/46`; `bash demo.sh` exit 0 `PASS: every beat produced its expected outcome`, `audit: OK (25 entries, 25 checkpoints)`.
- Not verified: Docker images/compose, CI on GitHub, any remote anchor, a real (non-mock) provider, behaviour on a shared network filesystem (anchor lock), a crash BEFORE the tool call (indistinguishable from after: holds its reservation until released).
- USP: G1 holds across a migration (an unknown spend is never assumed zero) and G2 across a crash; every way out of an unresolved execution is a human, audited step.

## Assurance final cleanup: validation step, start-up warning, reconcile CLI (2026-11-20, ADR-024 addendum)
- Built: `db.legacy_markers(conn)` is the single definition of an incomplete unresolved marker (the gate barrier uses it too); `python -m actionproof.reconcile check` is the explicit validation step (exit 1 if any); `scripts/apply_schema.py` and `server.build_app` log a WARNING at start-up (boot is not refused: reconciliation needs the API); `python -m actionproof.reconcile release [--executed --reservation JSON]` is the audited reconciliation. The barrier itself (every cap-sensitive prepare/commit DENY AP-CUM-03 / G1 while a legacy marker exists) was already in 9b9a792 and is unchanged.
- Tests: `tests/usp/test_migration_legacy_marker.py` now migrates a REAL pre-ADR-022 `tool_reached` table (exact ADR-019 DDL, no reservation columns) through `db.apply_schema`; 13 tests cover the migration, the block, both release paths, bad input, the validation function, the CLI, the apply_schema warning and the start-up log.
- Docs: stale "NULL amount counts as zero" removed (schema.sql comment, ADR-022 superseded by ADR-024); RUNBOOK describes the CLI instead of "no CLI wrapper yet"; DATA_MODEL, ARCHITECTURE (operator view), THREAT_MODEL (legacy-marker row) updated; DECK_TRACE row A11 added, existing rows untouched.
- Check (real runs, standing local OPA for test_infra): full suite `806 passed in 716.53s`; `tests/usp` `138 passed`; `opa test policy` `PASS: 46/46`; `bash demo.sh` exit 0 `PASS: every beat produced its expected outcome`.
- Not verified: Docker images/compose, GitHub CI, a remote anchor, a real provider, a legacy marker on a production-sized database, anchor lock on a network filesystem.
- USP: an unknown spend is detected, reported and blocked, never assumed zero, and only an audited human step releases it.

## Open issues (honest list)
- Independent attack generator blocked; held-out set is handwritten2 (NOT independent).
- Docker compose never run here; no green CI run exists yet.
- Playwright e2e specs written, never run; Lighthouse and real-device mobile LCP not measured.
- COOP header slows first paint in headless Chromium.
- benign-ref-var-05: genuine false block under the per-person cap (1/120).
- Video minor flaws; the blind critic 7.2 was before fixes.

## Hardening v2, Phase 1: review-token hashing, credential lifecycle, directory administration (2026-11-22, branch feat/security-hardening-v2, ADR-025/026/027)
- Built: `review_tokens` stores sha256 only (migration keeps outstanding and used tokens, drops the plaintext column); `api_clients` gains id/label/issuer/scopes/expiry/revocation/last-use with `actionproof.credentials` (issue, list, revoke, rotate, audited) and tool-scope enforcement (AP-SCOPE-02 / G1) before the Gate; legacy credentials expire 30 days after migration; `actionproof.directory` + `PUT /api/admin/people/{login}` (admin + CSRF) audit every directory change with before/after, `people.disabled`, lock order audit -> people in commit, mint and directory edits. OpenAPI and web API types regenerated (no UI change).
- Check (real runs): see the Phase 1 gate entry below once the full suite finishes.
- Not verified: Docker, CI, the admin endpoints from the web UI, deadlock behaviour under heavy concurrent edit/commit load (lock order reasoned, not stress-tested).
- USP: a stolen database no longer yields a usable approval token, an agent credential can only do what it was scoped and is still valid for, and a role change cannot be outrun by an old approval (G2/G1).

## Hardening v2, Phase 2: policy provenance (2026-11-22, ADR-028)
- Built: policy revision (sha256 of the `package actionproof` modules as OPA reports them) in `Decision`, in the signed receipt (`policy_revision`), checked again at commit (AP-STALE-07 on change, pending reviews do not survive), recorded with OPA version and input in the prepare audit entry; immutable `policy_archive/<revision>/` plus `policy.reconstruct`; authz.rego allows the two read-only GETs.
- Check (real runs): tests/usp/test_policy_provenance.py `8 passed`. Core suites after the receipt-shape change: see the final regression run (full suite deferred to the end by instruction).
- Not verified: signed policy bundles (not implemented), a hot reload racing the pre-decision read, the OPA GETs under the Render authz.rego, Docker.
- USP: a decision can now be traced to, and re-run against, the exact policy that made it, and an approval cannot outlive that policy (G1/G2).

## Hardening v2, Phase 4: live MCP agent integration (2026-11-23, ADR-031, H10)
- Built: `examples/live_agent/agent.py` (Anthropic Messages API over httpx, HTTP MCP with a scoped bearer credential, INV-2048 + injected.pdf scenario, printed real requests/responses, JSONL traces with optional operator-side audit seq), `examples/live_agent/traces/` (git-ignored), `docs/LIVE_AGENT.md`, pointer in docs/DEMO.md.
- Check (real runs): tests/e2e/test_live_agent_offline.py — see report-p4.md for the exact output.
- Not verified: any live provider run (no credentials; UNTESTED LIVE), provider acceptance of the server's JSON schema ($defs) as a tool input_schema, Docker, CI.
- USP: a model free to choose its own tool calls, holding only a scoped credential and the ActionProof tool surface, still cannot turn a document's instruction or a conflicting amount into an executed write, and never sees a receipt, token or key (G1/G2).

## Hardening v2, Phase 5: TLA+ model (2026-11-23, ADR-032). Built formal/ActionProof.tla/.cfg/README/MAPPING. Check: NOT run (Java and TLC absent); the spec was reviewed by reading only. USP: the protocol behind G2 and the spending caps is now stated precisely enough to model-check; no guarantee is claimed until TLC passes.

### Phase 6 (hardening v2): remote audit trust (ADR-030, H8-H9)
- Added `anchor_remote.HttpAnchor` (generic append-only HTTP adapter) and `anchor_publisher` (async publisher/monitor: once, check, run); `anchor.CheckpointAnchor` protocol, KeyRegistry accepted by `_check_signed`.
- Docs: ARCHITECTURE (remote anchor), RUNBOOK (operating the publisher), THREAT_MODEL (host owner row), DATA_MODEL (remote anchor + state file), DEPLOY_ORACLE_VERCEL (note).
- Tests: tests/usp/test_anchor_remote.py 16 passed; tests/test_anchor.py and related suites see report-p6.md.
- Not verified: any real append-only/WORM provider (stub only).
- USP: checkpoints that left the host through the publisher cannot be silently rewritten, rolled back, gapped or forked without `check` failing (G1/G2 evidence of the audit trail), and the remote anchor can never block or alter an authorization decision because it is never on the decision path and never does I/O inside a database transaction.

### Phase 3 (hardening v2): execution journal and truthful audit semantics (ADR-029, H5-H7)
- New `src/actionproof/journal.py` and table `execution_journal` (append-only, own hash chain and verifier, journal-only advisory lock). The commit path journals RESERVATION_CREATED + DISPATCH_STARTED atomically with the `tool_reached` reservation before the call, CONFIRMED after the tool returned, FAILED (explicit DefiniteFailure) or UNKNOWN otherwise. The EXECUTED audit entry is written after confirmation and references it; it is rehearsed in a rolled-back savepoint before dispatch.
- `release_quarantine` journals STARTED/COMPLETED, accepts downstream evidence that must match the execution, and refuses to free a CONFIRMED execution. CLI `reconcile journal verify|list|resolve`.
- Tests: tests/usp/test_exec_journal.py (see report-p3.md for exact output).
- USP: what this phase proved about G1/G2: a dispatched execution can no longer vanish: whatever happens after dispatch (success, definite failure, ambiguous error, a really killed process) leaves a tamper-evident journal entry naming the receipt, key, principal, counterparty and exact amount; the audit chain claims EXECUTED only after the downstream confirmed; an UNKNOWN keeps its money and key (G1 caps, G2 AP-REP-05) until trustworthy matching evidence or an audited human decision resolves it, and no amount of elapsed time does.

## Hardening v2 gate: full regression, stress and real-browser run (2026-11-23)
- Real runs on this machine: full suite `882 passed, 2 failed in 1442s` (the 2 were a Decision-equality regression from ADR-028, fixed, and an OPA-not-running environment test, re-run green); `opa test policy` `PASS: 46/46`; stress `tests/stress` N=10000 seed=8 (800 vendors): 10000 prepared, 6124 executed, concurrent phase executed exactly 5 of 5000.00-cap-limited 900.00 approvals; every invariant held (executes == commits, no nonce/key twice, caps never exceeded, audit verifies). A first 10000-op run (seed 7, 40 vendors) also passed but executed only 506 (cap-saturated).
- Real browser (built-in browser, local app): landing page shows the live recorded decision; reviewer login; review page with cited evidence; approve ran the mock write once (ALLOW executed, rev-alice different person); audit page lists the chain and "Verify chain" = 6 entries and 6 checkpoints verified; sign-out redirects and APIs return 401; admin can list the directory, cannot approve (403), cannot self-grant reviewer (403), PUT without CSRF 403; phone layout 375px no overflow.
- Found by the browser run: a review parked before ADR-028 failed with a misleading AP-SIG-09; it is now AP-STALE-07 "receipt predates policy provenance; re-prepare the request" (tests/usp/test_policy_provenance.py).
- Not verified: the repo's Playwright specs (package not installed), TLC on the TLA+ model (no Java), a live provider run, Docker, GitHub CI, a real remote anchor provider, the full suite re-run after the last gate.py message change (targeted tests only).
