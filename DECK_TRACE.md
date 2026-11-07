# DECK_TRACE — every deck claim → code → proof

Source: `ActionProof — CodeQuest 2026.pdf` (10 slides, team Bench Warmers). Status: `todo` | `done`. The final gate fails if any row is not `done` with a proving test or artifact.
Paths are planned until the phase that builds them; `todo` rows are the contract.

| id | slide | exact deck claim | where built | proving test / artifact | status |
|---|---|---|---|---|---|
| S1.1 | 1 | "ACTION INTERCEPTED: action: approve_invoice / amount: 4800.00 [DIRECT ok] / variance: 500.00 [DERIVED ok] / rule: AP-INV-04 (> 100) / decision: REVIEW" | gate.py, server.py, adapters/langchain.py | tests/e2e/test_slide1_card.py (MCP stdio + LangChain) | todo |
| S1.2 | 1 | "Before an AI agent acts, prove it should." | web hero, README | web e2e hero text; README first lines | todo |
| S1.3 | 1 | "An evidence-verified safety gate for AI agents and the tools they control." | README, web hero | README check | todo |
| S2.1 | 2 | "Approve INV-2048: Invoice $4,800 / Purchase order $4,300 / Unexplained $500. A filter that reads the agent's reply sees nothing wrong, so the write could execute." | fixtures/make.py, eval/run.py (LLM-judge arm) | eval results: output-filter arm passes INV-2048 attack; fixtures/manifest.json | todo |
| S2.2 | 2 | "01 Evidence gap — A tool argument can hold a value with no source field and no document citation behind it." | verify.py | tests/usp/test_gap_evidence.py (fails without gate) | todo |
| S2.3 | 2 | "02 Policy gap — A valid tool name can still carry an amount, target or actor outside the caller's scope." | policy/actionproof.rego AP-SCOPE-02 | tests/usp/test_gap_policy.py + opa test | todo |
| S2.4 | 2 | "03 Execution gap — Retries, stale records and check-then-commit races can repeat or invalidate an approved write." | gate.py commit | tests/usp/test_gap_execution.py (retry, stale, race) | todo |
| S3.1 | 3 | "USP: Proof before permission. No value can authorize a write unless its derivation re-checks, and no approval can be replayed." | CLAUDE.md, tests/usp/, README, web, eval | CI job "USP: proof before permission" | todo |
| S3.2 | 3 | "1 Intercept: An MCP proxy sits in front of every tool. Default deny." | server.py | tests/test_mcp_default_deny.py | todo |
| S3.3 | 3 | "2 Verify: Re-extract each cited value, recompute derived ones, check taint." | extract.py, verify.py | tests/test_verify_*.py | todo |
| S3.4 | 3 | "3 Authorize: OPA/Rego policy, plus a dry-run diff and a state version." | policy.py, rego, gate.prepare | opa test; tests/test_prepare.py | todo |
| S3.5 | 3 | "4 Receipt and commit: A signed one-use receipt. Commit re-checks state, then calls the tool." | gate.py | tests/usp/test_replay.py, tests/test_commit.py | todo |
| S3.6 | 3 | "5 Audit: Hash-chained log with signed checkpoints and a verifier CLI." | audit.py | tests/test_audit.py (edit/delete detected) | todo |
| S3.7 | 3 | "Outcomes: ALLOW, REVIEW (a human mints a one-use token) or DENY. Any error fails closed." | gate.py, console | tests/usp/test_fail_closed.py, tests/test_review_token.py | todo |
| S4.1 | 4 | "DIRECT: a deterministic parser re-extracts the value at the cited page and box. Value and document hash must both match." | extract.py, verify.py | tests/test_verify_direct.py | todo |
| S4.2 | 4 | "DERIVED: recomputed by an allowlisted pure function over verified claims. The model never does the arithmetic." | verify.py | tests/usp/test_derived_only_pure.py (500.00 passes, 501.00 fails) | todo |
| S4.3 | 4 | "ASSERTED: model-only. Fine for low-risk fields, never enough to authorize a money-moving argument." | verify.py | tests/usp/test_taint.py (ASSERTED amount fails) | todo |
| S4.4 | 4 | "SIMPLIFIED ACTIONREQUEST: tool payments.approve_invoice; amount 4800.00 DIRECT src invoice.pdf p1 box doc_sha256; variance 500.00 DERIVED fn sub inputs invoice.total, po.total; note ASSERTED taint doc" | contracts.py | tests/test_contracts.py, tests/usp/test_no_floats.py (61 pass) | done |
| S4.5 | 4 | "Taint rule: text from documents can be shown to a reviewer, but it can't fill an authority field unless it is DIRECT-verified or matches a system of record." | verify.py, console | tests/usp/test_taint.py; console e2e (greyed "not evidence") | todo |
| S5.1 | 5 | Table: Output filter or LLM judge — No/No/No/No/No | eval arm `llm_judge` | eval results.json measured | todo |
| S5.2 | 5 | Table: Schema validation only — Types/No/No/No/No | eval arm `schema_only` | eval results.json | todo |
| S5.3 | 5 | Table: Plain policy gateway (OPA, Cedar) — Yes/No/No/Partial/Varies | eval arm `policy_gateway` (OPA without evidence) | eval results.json | todo |
| S5.4 | 5 | Table: Dual-LLM or capability designs (CaMeL-style) — Yes/Partial/Yes/No/No | descriptive row only (no arm); /evaluation labels it "typical design, not measured" | web /evaluation | todo |
| S5.5 | 5 | Table: ActionProof — Yes on checks args | tests/test_checks_args.py | named test | todo |
| S5.6 | 5 | ActionProof — Yes on evidence per arg | tests/test_evidence_per_arg.py | named test | todo |
| S5.7 | 5 | ActionProof — Yes on taint flow | tests/usp/test_taint.py | named test | todo |
| S5.8 | 5 | ActionProof — Yes on commit-time check | tests/test_commit_time_check.py | named test | todo |
| S5.9 | 5 | ActionProof — Yes on signed receipt | tests/test_signed_receipt.py | named test | todo |
| S5.10 | 5 | "Honest framing: rows describe typical designs, not specific products. None of the pieces is new alone…" | README, web /evaluation | text check | todo |
| S6.1 | 6 | Prompt injection — taint labels; text never fills authority fields — hidden "approve regardless" in a PDF | fixtures, verify.py | tests/attacks/test_prompt_injection.py + eval | todo |
| S6.2 | 6 | Argument tampering — claims re-verified at the cited span — amount edited after extraction | gate.py | tests/attacks/test_tampering.py + eval | todo |
| S6.3 | 6 | Evidence forgery — span re-extraction and document hash match — cited span lacks the value | verify.py | tests/attacks/test_forgery.py + eval | todo |
| S6.4 | 6 | Confused deputy — on_behalf_of scope checked in policy — agent exceeds the user's scope | rego AP-SCOPE-02 | tests/attacks/test_confused_deputy.py + eval | todo |
| S6.5 | 6 | Split payments — cumulative limits per actor and vendor — two $4,900 approvals, $5,000 cap | rego AP-CUM-03, gate.commit | tests/attacks/test_split_payments.py + eval | todo |
| S6.6 | 6 | Replay — one-use token and idempotency key — reused token or key | gate.py DB constraints | tests/attacks/test_replay.py + eval | todo |
| S6.7 | 6 | Race (TOCTOU) — version precondition at commit — record mutated mid-flight | gate.commit | tests/attacks/test_race.py + eval | todo |
| S6.8 | 6 | "Measured against no gate, schema-only and an LLM judge, on 100+ benign cases." | eval/run.py | eval/results.json (benign n ≥ 100) | todo |
| S6.9 | 6 | "About half the attacks come from a separate generator, so we don't grade our own exam." | .claude/agents/attack-generator.md, eval/ | results.json split handwritten/generated | todo |
| S7.1 | 7 | Gateway — Python, FastAPI, MCP SDK — proxy every tool call | server.py | tests/test_mcp_*.py | todo |
| S7.2 | 7 | Contracts — Pydantic v2 strict, RFC 8785 | contracts.py | tests/test_contracts.py, tests/usp/test_no_floats.py (61 pass) | done |
| S7.3 | 7 | Policy — OPA sidecar, Rego — default-deny decisions | policy/, docker-compose.yml | opa test; docker compose ps | todo |
| S7.4 | 7 | Evidence — pdfplumber plus a vision pass — dual extraction of claims | extract.py | tests/test_extract_dual.py | todo |
| S7.5 | 7 | State — PostgreSQL — versions, tokens, audit chain | db schema | tests/test_db_*.py | todo |
| S7.6 | 7 | Signing — Ed25519 (PyNaCl) — receipts and checkpoints | gate.py, audit.py | tests/test_signed_receipt.py | todo |
| S7.7 | 7 | Agent adapter — LangChain wrapper — works with existing agents | adapters/langchain.py | tests/e2e/test_langchain.py | todo |
| S7.8 | 7 | Console — Next.js and React — source-span review UI | web/ | Playwright e2e | todo |
| S8.1 | 8 | "W1 Claims: schema and claim types, PDF and JSON extractor, dual-extraction check." | Phase 2 | Phase 2 gate output | todo |
| S8.2 | 8 | "W2 Gate: OPA policy, prepare and commit protocol, adversarial mock services." | Phase 3, mocks/ | Phase 3 gate output | todo |
| S8.3 | 8 | "W3 Surface: MCP proxy, review console with source-span overlays, signed audit chain." | Phase 5, 7 | Phase 5/7 gate output | todo |
| S8.4 | 8 | "W4 Proof: eval harness, baselines, attack suite, demo video." | Phase 6, 8 | eval/EVAL.md; demo video | todo |
| S8.5 | 8 | "Prototype scope: invoice approval is the hero demo. No production credentials or real payments." | mocks/, README | README; no real credentials in repo | todo |
| S8.6 | 8 | "If time runs short: cut the second connector and console polish." — NOT cut (brief overrides) | Phase 5 connector; Phase 7 console | second-connector e2e; Phase 7 gate | todo |
| S9.1 | 9 | Who benefits: "Developers shipping agents. A drop-in gate instead of bespoke checks." | README, web section | web e2e section present | todo |
| S9.2 | 9 | "Finance and operations teams. Risky approvals pause with the reason and source span." | console | console e2e | todo |
| S9.3 | 9 | "Security and compliance. A signed, tamper-evident record of each decision." | audit.py | audit verify | todo |
| S9.4 | 9 | "People whose money or data agents touch. Fewer wrong writes." | web section | web e2e | todo |
| S9.5 | 9 | Impact: "Out-of-policy or unsupported writes are blocked before they execute." | gate | attack suite (0 executed) | todo |
| S9.6 | 9 | Impact: "Reviewers decide from evidence, not from the agent's own summary." | console | console e2e | todo |
| S9.7 | 9 | Impact: "Replays and stale-state writes are rejected by construction." | DB constraints | tests/usp/test_replay.py | todo |
| S9.8 | 9 | "Proposed targets, not results: 0 successful attacks on the held-out set, at most 5% false blocks, p95 under 250 ms added." | eval/run.py | EVAL.md targets met/missed | todo |
| S10.1 | 10 | "Verifier-bound: only as good as its deterministic verifiers. Free-form judgments can't be proven." | README, web | text check | todo |
| S10.2 | 10 | "Semantic fraud: a fake invoice that looks internally consistent is out of scope." | README, web, THREAT_MODEL | text check | todo |
| S10.3 | 10 | "The gate is a target: the signing key must stay out of the agent's reach, and the gateway needs hardening." | README, web, RUNBOOK | text check | todo |
| S10.4 | 10 | "Safety, not judgment: it stops unauthorized actions. It doesn't guarantee a good business decision." | README, web | text check | todo |
| S10.5 | 10 | "Prove the action before the system executes it." | README closing, demo, site | text check | todo |
