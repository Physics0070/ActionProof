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
- [ ] llm-council → ADR-008 (reviewer ≠ submitter?), ADR-009 (second connector)

## Phase 5 — Surface (W3)
- [ ] server.py MCP proxy + extract_fields; adapters/langchain.py + example agent
- [ ] second connector; audit.py + verifier CLI; console backend endpoints; docs/API.md

## Phase 6 — Proof (W4)
- [ ] attacks (handwritten + generated in isolation), 100+ benign, eval/run.py 5 arms, EVAL.md

## Phase 7 — Product UI
- [ ] web/ site + /evaluation + console; web/DESIGN.md, web/reference/

## Phase 8 — Ship
- [ ] CSP/headers, compose full stack, GitHub Actions, demo.sh, video, RUNBOOK/DEMO/README
