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

## ADR-010: The tool executes inside the commit transaction; idempotency key at the tool  — 2026-11-07 — Accepted
- **Context:** Deck S2.4 "execution gap": retries, stale records and check-then-commit races. The gate must call the tool at most once per receipt and never on a DENY, and the system of record must not drift from what was approved.
- **Options:** (a) call `tool.execute` inside the SERIALIZABLE commit tx after every check; (b) commit a reservation, then call the tool outside the tx; (c) transactional outbox / two-phase with the tool.
- **Decision:** (a). `gate.commit` takes `LOCK TABLE commits IN SHARE ROW EXCLUSIVE MODE` as its first statement (before the snapshot is taken), so gate commits form one lane, the cumulative re-check sees every earlier commit, and SSI never aborts a commit after the tool ran. Inside the tx: consume review token, insert `commits` (UNIQUE nonce + idempotency key), cumulative re-check, `FOR UPDATE` version + diff hash (diff hash binds the dry-run diff AND the record's before-state), then `execute(req, version, idempotency_key, conn)` exactly once, a post-check that the tool moved the version by at most one, and the gate sets `version = receipt.version + 1`. Serialization failures (40001/40P01) are retried up to 3 times only while the tool has NOT been reached. Once the tool was reached, any failure rolls back and **burns** the receipt: a separate tx inserts the `commits` row (`ON CONFLICT DO NOTHING`), so a client retry is AP-REP-05 and the amount counts toward the cap (unknown outcome = spent, fail closed).
- **Consequences:** A crash after `execute` but before COMMIT can leave a tool-side effect with no `commits` row; the tool-side idempotency key bounds that. A hostile tool can still double-apply on its own side (mock `double_call`); the gate detects the extra version bump, rolls back and burns, but cannot undo a real external payment. One commit lane caps throughput. `# ponytail: global lock; upgrade path is a per (actor, vendor) lock row, then an outbox/two-phase tool protocol.`

## ADR-011: variance = invoice − PO; the policy uses abs  — 2026-11-07 — Accepted
- **Context:** Slide 2: invoice $4,800, PO $4,300, "unexplained $500". The sign of the difference must not let an over- or under-billing slip past AP-INV-04.
- **Decision:** `variance` is a DERIVED claim `sub(invoice.total, po.total)` (positive = invoice above PO). Rego compares `abs(variance)` in integer cents against 100.00. The gate also requires `amount`, `invoice.total` and `po.total` claims to equal the system-of-record values (invoice record total, PO total) — a document the agent supplies proves only what the document says.
- **Consequences:** Under-billing by more than 100.00 is also REVIEW. A self-made document cannot lower the variance or the amount below what the records say (AP-VER-01, G1).
