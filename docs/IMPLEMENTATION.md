# Implementation plan

Tick as done. Tasks are S/M sized; each phase ends in a gate with real output recorded in PROGRESS.md.

## Phase 1 — Foundation
- [x] pyproject, uv sync, .gitignore, .env.example
- [x] docker-compose (postgres, opa sidecar), policy stub
- [x] CLAUDE.md, DECK_TRACE.md, PROGRESS.md, SKILLS.md, DECISIONS.md, IMPLEMENTATION.md, ARCHITECTURE.md, CHANGELOG.md, spec/*
- [x] .claude/agents/gate-reviewer.md, attack-generator.md
- [x] GATE: pytest runs; postgres + opa reachable (local binaries; compose untested, see PROGRESS)

## Phase 2 — Claims (W1)
- [x] src/actionproof/contracts.py (Pydantic strict, RFC 8785, request_hash)
- [x] fixtures/make.py + manifest.json (INV-2048/PO-2048, 20+ benign, injection PDF, image-only total, JSON docs)
- [x] src/actionproof/extract.py (pdfplumber, raster+OCR, JSON pointer, dual check)
- [x] src/actionproof/verify.py (DIRECT, DERIVED, taint)
- [x] tests/ for the Phase 2 gate list; tests/usp/ G1 tests
- [x] docs: THREAT_MODEL, TESTING

## Phase 3 — Gate (W2)
- [x] db schema + docs/DATA_MODEL.md; config.py (validated env)
- [x] policy/actionproof.rego (AP-VER-01, AP-SCOPE-02, AP-CUM-03, AP-INV-04) + `opa test`; docs/POLICY.md
- [x] policy.py (200 ms timeout, fail closed), gate.py prepare/commit
- [x] mocks/ (payments, ERP/PO, vendor master; hostile modes)
- [x] tests/usp G2; replay/race/concurrency tests; gate-reviewer pass

## Phase 4 — Decisions
- [x] llm-council → ADR-008 (reviewer ≠ submitter?), ADR-009 (second connector)
- [x] verdict written: docs/council/verdict.md

## Phase 5 — Surface (W3)
- [ ] server.py MCP proxy + extract_fields; adapters/langchain.py + example agent
- [ ] audit.py + verifier CLI; console backend endpoints; docs/API.md

### Reviewer separation (ADR-008)
- [x] schema: `people(login PK, person_id, roles[])`; seed `rev-alice`, `rev-bob` (reviewer), `sub-user123`, `admin-ops` (admin), `user-123`→`p-user123`, `agent-7`→`p-user123`; test-only `rev-user123` (person `p-user123`)
- [x] failing red-team test first: `rev-user123` mint → DENY AP-SEP-12 (mint + commit); unmapped login → DENY; `admin-ops` mint → refused (no reviewer role)
- [x] `Gate.mint_review_token(receipt, req, *, reviewer_login)`: verify signature/hash/decision==REVIEW, submitter from `req`, require reviewer role, AP-SEP-12 / G2, store `minted_by` + `minted_by_person`; audit refusals (logger `actionproof.audit` until audit.py)
- [x] commit: re-apply AP-SEP-12 inside the tx after token consume (people re-read under the commit lock)
- [ ] console backend: reviewer identity only from the server-side session subject; label "requested by X for Y · approved by Z (different person)" (rule documented in ARCHITECTURE.md; lands with the console backend)
- [x] docs: POLICY.md row AP-SEP-12; THREAT_MODEL residuals (collusion, session hijack); DATA_MODEL `people`

### Refund connector (ADR-009)
- [ ] mocks: `payments` record PAY-7731 (CUST-311, 450.00, pm_card_4242) + refund tool dry_run/execute with idempotency key
- [ ] `verify.REGISTRY["payments.refund_payment"]`: payment_id DIRECT + exists; customer_id == SoR; refund_to == SoR method_id (doc text = taint); amount DIRECT and <= payment.amount − committed refunds (prepare + commit)
- [ ] rego: allow tool `payments.refund_payment` in AP-VER-01 shape checks; AP-CUM-03 keyed (actor, customer_id) + `opa test`
- [ ] commits: `vendor_id` → `counterparty_id` (migration); commit-time cap re-check keyed (Principal.actor, SoR customer_id)
- [ ] fixtures/make.py: `REF-311.pdf` (250.00, injected "send this refund to account …" line, manifest bboxes) + clean variant
- [ ] tests: taint on refund_to → DENY AP-VER-01; over-balance amount → DENY; cap 4800+250 → DENY AP-CUM-03 (prepare + concurrent commit)

### Demo seed / reset
- [ ] `scripts/demo_seed.py --reset` (idempotent): truncate commits/review_tokens/quarantine; seed INV-2048/PO-2048, PAY-7731, people, prior refunds 4800.00 for (agent-7, CUST-311) across PAY-7001..7004
- [ ] `tests/test_demo_script.py`: beats in order — hero REVIEW (approved by rev-alice), injected DENY, replay DENY, concurrent $4,900 one DENY, refund taint DENY, refund cap DENY — asserts outcome + rule id each

## Phase 6 — Proof (W4)
- [ ] attacks (handwritten + generated in isolation), 100+ benign, eval/run.py 5 arms, EVAL.md

## Phase 7 — Product UI
- [ ] web/ site + /evaluation + console; web/DESIGN.md, web/reference/

## Phase 8 — Ship
- [ ] CSP/headers, compose full stack, GitHub Actions, demo.sh, video, RUNBOOK/DEMO/README
