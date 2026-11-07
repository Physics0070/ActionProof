# Decision log (ADRs)

Format: id | date | status. Never delete; supersede.

## ADR-001: PostgreSQL, serializable commit  — 2026-11-07 — Accepted
- **Context:** Slide 7 names PostgreSQL for versions, tokens and the audit chain. The commit must be atomic against races.
- **Options:** PostgreSQL; SQLite; Redis + app locks.
- **Decision:** PostgreSQL. Commit runs in one SERIALIZABLE transaction with row locks (`SELECT ... FOR UPDATE`).
- **Consequences:** UNIQUE constraints enforce G2 in the database, not app code. Serialization failures are retried or DENIED (fail closed).

## ADR-002: Dual extraction = pdfplumber + rasterize/OCR  — 2026-11-07 — Accepted
- **Context:** Slide 7: "pdfplumber plus a vision pass". The vision pass must stay out of the LLM trust path.
- **Options:** LLM vision model; Tesseract OCR on the rasterized box; second text library.
- **Decision:** Vision pass = PyMuPDF rasterizes the cited box, Tesseract OCRs it. Deterministic, no LLM, reads image-only values pdfplumber cannot. Both must agree or the claim fails.
- **Consequences:** Needs the Tesseract binary (`TESSERACT_CMD`). OCR error rate is a false-block risk, measured in Phase 6.

## ADR-003: Fixtures generated with PyMuPDF  — 2026-11-07 — Accepted
- **Context:** Verification tests need exact ground-truth bboxes.
- **Decision:** `fixtures/make.py` writes PDFs with PyMuPDF and records exact bboxes, JSON pointers and sha256 in `manifest.json`.
- **Consequences:** Ground truth is exact; real-world scan noise is out of scope (slide 10 "Verifier-bound").

## ADR-004: Two integration points  — 2026-11-07 — Accepted
- **Decision:** MCP proxy (any MCP client) AND the LangChain wrapper (slide 7 "Agent adapter") both route through the same `gate.prepare/commit`.
- **Consequences:** One gate implementation, two thin front doors.

## ADR-005: OPA as a sidecar container  — 2026-11-07 — Accepted
- **Decision:** OPA runs next to the gateway; the gateway calls it over HTTP with a 200 ms timeout; any error = DENY.
- **Consequences:** Policy is Rego, testable with `opa test`; adds a network hop counted in the p95 latency budget.

## ADR-006: Cumulative limits inside the commit transaction  — 2026-11-07 — Accepted
- **Context:** Two concurrent $4,900 approvals must not both pass a $5,000 cap.
- **Decision:** AP-CUM-03 is re-evaluated INSIDE the SERIALIZABLE commit transaction against locked cumulative rows, not only at prepare.
- **Consequences:** Prepare-time AP-CUM-03 is advisory; commit-time is authoritative.

## ADR-007: Signing key isolation  — 2026-11-07 — Accepted
- **Decision:** The Ed25519 key is loaded only by the gate process from a path in env; never returned, logged, or exposed to a tool/MCP response.
- **Consequences:** Invariant 6; slide 10 "The gate is a target" is stated honestly in README.
