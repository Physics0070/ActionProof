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

## ADR-012: Identity comes from the transport, not the request  — 2026-11-07 — Accepted
- **Context:** Red team (Phase 3) proved `actor` and `on_behalf_of` were free strings written by the untrusted agent: an alias (`Agent-7`, `agent-7 `, a zero-width suffix, `agent-8`) reset the AP-CUM-03 actor+vendor cap, and naming a richer principal (`cfo`) borrowed its scope.
- **Options:** (a) trust the request; (b) bind the request to a caller identity the transport authenticated; (c) look identity up from an API key inside the gate.
- **Decision:** (b). `Gate.prepare(req, docs, *, principal)` and `Gate.commit(receipt, req, review_token=None, *, principal)` take a `Principal(actor, on_behalf_of)` (frozen dataclass in `gate.py`) established by the MCP session / adapter (Phase 5). It is REQUIRED with no default (a missing principal is a TypeError, never a fail-open), and `req.actor` / `req.on_behalf_of` must equal it exactly, else DENY `AP-SCOPE-02` / G1 "identity not bound to caller" (at prepare, and at commit after the hash check). `contracts.py` restricts both ids to `^[a-z0-9][a-z0-9_.-]{0,63}$`, so case, whitespace and zero-width aliases are contract errors. The cap key stays actor+vendor (deck S6).
- **Consequences:** The gate trusts the transport for authentication; a transport that maps every caller to one Principal would merge their caps (fail closed, not open). Tests use `tests/gatekit.KitGate`, which defaults to the honest test session `Principal("agent-7", "user-123")`; the production Gate has no default.

## ADR-013: variance is pinned to sub(invoice.total, po.total)  — 2026-11-07 — Accepted
- **Context:** Red team proved `verify.derived` recomputed whatever `fn`/`inputs` the agent named: `sub(invoice.total, note)` with an ASSERTED `note`, self-subtraction, `amount - invoice.total`, `po - po`, and a DIRECT variance from a self-made `calc.json` all produced 0.00 and turned a REVIEW into ALLOW.
- **Decision:** `verify.REGISTRY["payments.approve_invoice"]["pinned"] = {"variance": ("sub", ["invoice.total", "po.total"])}`: variance must be DERIVED with exactly that fn and those inputs (a DIRECT variance is rejected, ADR-011). A DERIVED input may only be a DIRECT or DERIVED claim that verified, or a system-of-record value; an ASSERTED claim, even "ok", is never an input. The gate also requires the variance value to equal `sor invoice.total - sor po.total` (Decimal, 2dp) at prepare and again at commit.
- **Consequences:** Only one variance can reach the policy: the records' own. A tool needing other derived fields must register its own pin.

## ADR-014: commit re-derives the policy from fresh state; burned receipts quarantine the record  — 2026-11-07 — Accepted
- **Context:** Red team proved commit re-checked only the invoice record and the cap: a delegation revoked or a vendor removed from scope after prepare, or a PO total changed (true variance now 500.00), still executed. And a burned (unknown-outcome) commit left the invoice `open`, so a fresh prepare with a NEW idempotency key applied it again (double effect).
- **Decision:** (1) Inside the commit tx, after the version/diff check and under the commit lock, the gate rebuilds the policy input from CURRENT state (delegation scope, PO total/vendor via `tool.sor_for`, committed sum excluding this row; amount and variance must still equal the records) and calls `policy.decide` again. Fresh DENY = DENY with OPA's rule ids (G1). Fresh REVIEW on an ALLOW receipt = DENY `AP-STALE-07` / G2. (2) `_burn` also inserts `quarantine(record_id, nonce, created_at)`. `prepare` DENYs `AP-REP-05` / G2 "unknown outcome from a previous attempt; reconcile" while a record is quarantined, and commit re-checks it inside the tx. `Gate.release_quarantine(record_id, reviewer)` is the admin reconcile path. The burn row and the quarantine row are written in separate transactions so one failing does not skip the other; a failure is reported as an extra AP-ERR-11 reason on the DENY.
- **Consequences:** One more OPA round trip per commit, inside the commit lane (latency, not safety). A record stays blocked until a human reconciles it with the tool's real outcome. `# ponytail: if both burn writes fail, a retry is bounded only by the tool-side idempotency key; release_quarantine gets an audit hook in Phase 5.` `mint_review_token` and `release_quarantine` are Gate methods for the human/admin side only; no tool-facing path (MCP, adapter) may expose them (ADR-008 still open).

## ADR-008: Reviewer separation of duties by directory person (AP-SEP-12)  — 2026-11-07 — Accepted
- **Context:** A REVIEW decision is executable only with a one-use human token (AP-REV-10). `mint_review_token(request_hash, submitter, reviewer)` took both identities as caller strings and only stored them. One person, or one compromised account, could submit and approve, which undoes the REVIEW control. LLM council, Phase 4 (`docs/council/verdict.md`): all five advisors chose four-eyes. Peer reviewers and the coordinator added that it must compare verified *people*, not logins: one human with two reviewer logins, and admin role escalation.
- **Options:** (A) the reviewer must differ from actor and on_behalf_of, enforced in the gate, DENY with a rule id; (B) any reviewer-role holder, audited; (C) configurable per tool/threshold.
- **Decision:** (A), as `AP-SEP-12` / **G2** ("reviewer is the same person as the submitter (separation of duties)"). New directory table `people(login PK, person_id, roles[])`, covering console logins, on_behalf_of ids and agent ids (each agent mapped to its operator). The reviewer person is `people[console_session.subject]`, from the server-side session and never from a request. The submitter persons are `people[Principal.actor]` and `people[Principal.on_behalf_of]`, using the transport Principal (ADR-012). DENY if the reviewer person is among them, or if any lookup is missing (fail closed). An on_behalf_of that names a team without a single person also DENYs. Enforced twice:
  1. At mint. The new signature is `mint_review_token(receipt, req, *, reviewer_login)`: the gate verifies the receipt signature, the hash and `decision == REVIEW`, and reads the submitter from `req`. It requires the `reviewer` role (`admin` cannot mint) and stores `minted_by` + `minted_by_person`.
  2. Inside the commit tx, right after the token is consumed, by re-reading `people` under the commit lock. A violation rolls back.

  Seeded accounts: `rev-alice`, `rev-bob` (reviewers), `sub-user123`, `admin-ops`, and test-only `rev-user123` (same person as user-123).
- **Consequences:** A solo operator uses a second seeded reviewer, so there is no weaker default. (B) was rejected because it is the status quo the product exists to fix. (C) was rejected because a threshold exemption invites split-the-invoice. An audited, time-boxed, two-person break-glass is an explicit non-goal for the prototype. Collusion between two different people and reviewer session hijack are residual risks (THREAT_MODEL). Separation is only as strong as the console's authentication and the `people` data, so admin edits to `people` are audited, and the commit-time re-check catches edits made after a mint. `# ponytail: team on_behalf_of is DENY; upgrade path is a team_members expansion.`

## ADR-009: Second connector = refund (`payments.refund_payment`)  — 2026-11-07 — Accepted
- **Context:** A second connector goes end to end through the same gate. It must show taint AND cumulative limits in a 3-minute demo without diluting the INV-2048 hero. LLM council, Phase 4 (`docs/council/verdict.md`): all five advisors chose refund, and every peer reviewer ranked the Executor's one-flow plan strongest. The coordinator's point decides it: with mock services, a bank-detail change has no system-of-record equality path (its taint check reduces to DIRECT verification alone), while a refund compares against a real original-payment record.
- **Options:** (A) vendor bank-detail change; (B) refund against an original payment with a per actor+customer cap.
- **Decision:** (B). Authority fields:
  - `payment_id`: DIRECT, and must exist in the system of record.
  - `customer_id`: equals the system-of-record payment's customer.
  - `refund_to`: equals the system-of-record payment's `method_id`. Documents can never fill it; taint is AP-VER-01 / G1.
  - `amount`: DIRECT at the cited box, and `<= payment.amount − committed refunds on that payment`, re-checked at commit (ADR-014).

  `reason` is not an authority field. AP-CUM-03 is keyed on `(Principal.actor, customer_id from the system of record)`, cap 5000.00, authoritative inside the commit tx (ADR-006/010). `commits.vendor_id` is generalized to `counterparty_id`. Demo:
  - `scripts/demo_seed.py --reset` seeds `PAY-7731` (CUST-311, 450.00, `pm_card_4242`) and prior refund commits of 4800.00 for (agent-7, CUST-311).
  - Fixture `REF-311.pdf` asks for 250.00 and carries an injected line redirecting the refund to a new account, which gives DENY AP-VER-01 (taint on `refund_to`).
  - The clean retry gives DENY AP-CUM-03 (4800 + 250 > 5000).

  The demo uses pre-generated, manifest-backed fixtures, not live extraction of unseen documents. Verification still runs.
- **Consequences:** The beat order is fixed: hero REVIEW, injected DENY, replay DENY, concurrent $4,900 (one DENY), then refund (about 40 s at most). If the taint refusal cannot land in one frame, the refund segment is cut from the video, never the hero. The refund destination redirect carries the BEC story that bank change would have told. A per-actor key lets one human running several agents spread refunds across actors. `# ponytail: per-actor cap key; upgrade path is a people.person_id key.`
