**Proof before permission.**

<p align="center"><img src="web/public/og.png" alt="ActionProof: before an AI agent acts, prove it should" width="860"></p>

# ActionProof

[![CI](https://github.com/Physics0070/ActionProof/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Physics0070/ActionProof/actions/workflows/ci.yml)

### Before an AI agent acts, prove it should.

> **ActionProof is a safety gate that makes an AI agent prove every value behind a write before the write can run, and never lets one approval run twice.**
> It helps developers shipping agents, finance and operations teams who approve what agents do, and security teams who need a tamper-evident record.

**The attack it stops, in one sentence:** an agent reads an invoice with a hidden instruction to approve a wrong amount, and ActionProof blocks the write because that number cannot be traced back to the real document.

**▶ [Live demo video, 3:40](https://drive.google.com/file/d/1iXMvmHMaYWwmgKwzT9PrvsAa3IPmHdWg/view?usp=sharing)** · **[Live demo](https://actionproof-bw-web.onrender.com)**

<p align="center"><a href="https://drive.google.com/file/d/1iXMvmHMaYWwmgKwzT9PrvsAa3IPmHdWg/view?usp=sharing"><img src="docs/screenshots/video-thumb.png" alt="Watch the 3:40 live demo video" width="720"></a></p>

CodeQuest 2026 submission by team **Bench Warmers**. This is a prototype on mock services: no real credentials, no real payments.

## What is verified, and what is not

Everything below is from real runs (CI on GitHub runners unless noted). Latest CI (commit 6bc60f9): all nine jobs green.

| Area | Status | Evidence |
|---|---|---|
| G1 / G2 guarantees and red team | Verified | `USP: proof before permission` job (`tests/usp`, `tests/redteam`) |
| Full backend suite | Verified | `pytest` job; 973 passed in a full local run (2026-11-23) |
| Signed policy authority (ADR-033) | Verified, off by default | `tests/usp/test_policy_authority.py`; enabled only when `POLICY_AUTHORITY_KEYS` is set |
| Signed journal checkpoints + anchor stream (ADR-034) | Verified | `tests/usp/test_journal_checkpoints.py`; checkpoints are written by `reconcile journal checkpoint` (schedule it) |
| Adapter evidence + outbox reconciliation (ADR-035) | Verified on the mock payments adapter | `tests/usp/test_adapter_evidence.py`, `tests/usp/test_outbox.py`; the refunds and proxy adapters have no signed lookup yet |
| Commit-lane throughput (ADR-036) | Measured, locking unchanged | [docs/PERFORMANCE.md](docs/PERFORMANCE.md#commit-lane): about 13 commits/s on one laptop; the audit lock, not the commit lane, is the limit |
| Policy (OPA) | Verified | `opa-test` job, 46/46 |
| Commit protocol model (TLA+) | Verified, bounded | `TLA+ model check (TLC)` job: 108,483 states, no error (3 receipts, 2 keys, 1 token) |
| Docker stack and reviewer console in a real browser | Verified | `e2e` job: 8 Playwright specs (login, replay, CSRF, approve, reject) |
| Stress | Verified (local) | `tests/stress`, 10,000 operations plus racing threads; every invariant held |
| Landing page budget | Verified: performance 0.86-0.95 on the home page, 0.94-0.95 on /evaluation (budget 0.75) | `lighthouse` job; LCP budget is 3.2 s, not Google's 2.5 s ([docs/PERFORMANCE.md](docs/PERFORMANCE.md)) |
| Live LLM through the gate | Verified, 2 runs (Groq, `gpt-oss-120b`) | run 1: six malformed approvals, all refused (`AP-VER-01`), none executed. Run 2: an asserted variance was denied (`AP-VER-01`), then the properly cited request was parked as REVIEW (`AP-INV-04`); a different person approved it in the console and it executed once ([docs/LIVE_AGENT.md](docs/LIVE_AGENT.md)) |
| Remote audit anchor | **Not verified** | tested only against a local stub; no tamper-proof (WORM) claim |
| Independent attack evaluation | **Not independent** | the attack sets are written by the builders |
| Real ERP / payment provider | **None** | mocks only |

## Problem and inspiration

AI can sound certain. That doesn't make an action safe. Take invoice INV-2048: the invoice says **$4,800**, the purchase order says **$4,300**, and **$500** is unexplained. A filter that only reads the agent's reply sees nothing wrong, so the write could execute. Three gaps sit behind that:

- **Evidence gap:** a tool argument can hold a value with no source field and no document citation behind it.
- **Policy gap:** a valid tool name can still carry an amount, target or actor outside the caller's scope.
- **Execution gap:** retries, stale records and check-then-commit races can repeat or invalidate an approved write.

ActionProof closes them with two guarantees, each backed by named tests:

- **G1:** no value can authorize a write unless its derivation re-checks.
- **G2:** no approval can be replayed.

## Demo

| | |
|---|---|
| **Live demo video** (3:40) | [Watch on Google Drive](https://drive.google.com/file/d/1iXMvmHMaYWwmgKwzT9PrvsAa3IPmHdWg/view?usp=sharing): real recordings, narrated. The live site; a real AI agent (Groq) denied once and then parked for review by the gate; a different person approving it in the console; audit verify; every attack in `demo.sh`; CLI verification of the audit chain and journal; the 300-test safety suite; the evaluation |
| **Live demo** | https://actionproof-bw-web.onrender.com (Render free tier: the first load after idle takes 30-60 s while the services wake). Setup: [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md) |
| **Demo script and judge Q&A** | [docs/DEMO.md](docs/DEMO.md) |
| **Evaluation report** | [docs/EVAL.md](docs/EVAL.md) |

### Screenshots

| | |
|---|---|
| ![Landing page: the agent's request with each value's claim type and the REVIEW decision](docs/screenshots/landing.png) | ![Reviewer console: INV-2048 paused because the invoice is $500 above the purchase order, with the cited box highlighted on the PDF](docs/screenshots/console-review.png) |
| **Landing.** A real recorded decision, fetched from the backend: each value the agent relied on, its claim type, and the result. | **Reviewer console.** Why it paused, every cited value re-verified, and the source span highlighted on the PDF page. |
| ![Audit log: hash-chained entries with a Verify chain button](docs/screenshots/console-audit.png) | ![Evaluation: 0 of 211 attacks executed against ActionProof, versus four baselines](docs/screenshots/evaluation.png) |
| **Audit log.** Every decision is hash-chained; Verify chain re-computes the chain and its signed checkpoints on the server. | **Evaluation.** 0 of 211 attacks executed, against four baselines (numbers rendered from `eval/results.json`). |

<p align="center"><img src="docs/screenshots/landing-mobile.png" alt="Landing page on a phone" width="260"></p>

<p align="center"><img src="docs/screenshots/demo-attacks.png" alt="demo.sh output: injected PDF, replay, concurrent cap, hijacked refund and self-approval are all denied" width="760"></p>

`demo.sh` plays every beat against the real gate and exits 0 only if each produced its expected outcome: the honest invoice pauses for review and a different person approves it; an injected PDF is denied; a replayed approval is denied; two concurrent $4,900 approvals under a $5,000 cap let exactly one through; a second connector (refunds) hits the same gate; and the audit chain verifies.

## Core features

- **Evidence-verified arguments.** Every value carries a claim type and is re-extracted at the cited page and box by two independent readers (PDF text layer plus an OCR pass). The two must agree, or the claim fails.
- **No model arithmetic.** Derived values (like the $500 variance) are recomputed by allowlisted pure functions, never trusted from the agent.
- **Taint rule.** Text that came from a document can be shown to a reviewer but can never fill an authority field.
- **Policy with named reasons.** OPA/Rego decides ALLOW, REVIEW or DENY, and every reason names its rule id and guarantee (G1 or G2).
- **Signed, single-use receipts.** The commit re-checks state in one serializable transaction, with cumulative caps per actor and per person, then calls the tool at most once.
- **Review console.** A human sees the source span highlighted on the PDF page and approves or rejects with a typed reason. The reviewer must be a different person than the requester.
- **Tamper-evident audit.** A hash-chained log with signed checkpoints and a verifier CLI that needs only the database and a public key. An optional local anchor (`audit anchor`, `audit verify --anchor --strict`) catches a tail deleted together with its checkpoints; a same-machine file is not WORM storage, copy it off-box.
- **Crash-safe single use.** Before the downstream call the gate durably records the full reservation (amount, idempotency key, counterparty). If the process dies after the call, a retry, a new receipt with the same key and the cumulative caps all still see it until it is reconciled. An outbox worker resolves an unknown outcome automatically, but only from a signed provider lookup, and it never sends the call again. Not exactly-once: that needs provider idempotency.
- **Signed evidence, end to end.** The active policy can be required to carry a signature from a separate policy-authority key (ADR-033); a provider's "it failed" only counts with a signed statement (ADR-035); the execution journal has signed checkpoints copied to the anchor as its own stream (ADR-034).
- **Key rotation.** Receipts are verified by their own `kid` (active, retired, revoked); duplicate public keys across kids are refused at load.
- **Hardened trust boundaries (v2).** Review tokens are stored only as SHA-256 digests; agent credentials have scopes, expiry, revocation and rotation; directory changes are admin-only and audited; every decision is bound to the policy revision OPA actually had loaded (a policy change invalidates old receipts and pending reviews); an append-only execution journal records what really happened downstream (unknown outcomes stay unknown until evidence or a human resolves them); an optional remote anchor publisher copies signed checkpoints off-host (stub-tested only).
- **Drop-in.** An MCP proxy in front of any tool server, a LangChain adapter, and a second connector (refunds) through the same gate.
- **Measured, not claimed.** An evaluation harness compares ActionProof against four baselines on 211 attacks and 120 benign cases.

## Tech stack

| Layer | Choice |
|---|---|
| Gateway | Python 3.12, FastAPI, MCP SDK |
| Contracts | Pydantic v2 (strict), RFC 8785 canonical JSON |
| Policy | OPA sidecar, Rego |
| Evidence | pdfplumber, PyMuPDF, Tesseract OCR |
| State | PostgreSQL 16 (versions, tokens, audit chain) |
| Signing | Ed25519 (PyNaCl) |
| Agent adapter | LangChain wrapper |
| Console and site | Next.js 16, React 19, React Three Fiber, GSAP, Lenis |
| Evaluation | pytest, a Groq-hosted LLM judge via `httpx` |
| Packaging | Docker compose, GitHub Actions |

## Installation guide

**You need:** Python 3.12, Node 20+, [Tesseract OCR](https://tesseract-ocr.github.io/tessdoc/Installation.html), and PostgreSQL 16 plus [OPA](https://www.openpolicyagent.org/docs/latest/#running-opa) (or Docker for those two).

```bash
git clone https://github.com/Physics0070/ActionProof.git
cd ActionProof
python -m pip install uv
python -m uv sync
cp .env.example .env            # Windows: copy .env.example .env
```

**1. Start Postgres and OPA** (pick one):

```bash
docker compose up -d postgres opa                               # with Docker
# or, without Docker:
python scripts/dev_pg.py start                                  # Postgres on :5433 (set PG_BIN if not on PATH)
opa run --server --addr 127.0.0.1:8181 policy &                 # OPA on :8181
```

**2. Create a signing key and demo data:**

```bash
python scripts/gen_key.py keys/dev-signing.key
python scripts/demo_seed.py --reset
python scripts/seed_console.py                                  # prints the reviewer logins once
```

**3. Run the demo:**

```bash
bash demo.sh
```

**4. Run the console API and the website:**

```bash
PYTHONPATH=src python -m actionproof.console                    # review console API on :8766
cd web && npm install
NEXT_PUBLIC_API_BASE=/api CONSOLE_API_ORIGIN=http://127.0.0.1:8766 npm run build
cp -r .next/static .next/standalone/.next/static
PORT=5174 HOSTNAME=127.0.0.1 node .next/standalone/server.js    # http://127.0.0.1:5174
```

On Windows Git Bash, prefix the build command with `MSYS_NO_PATHCONV=1`. More detail: [web/README.md](web/README.md) and [docs/RUNBOOK.md](docs/RUNBOOK.md) (full Docker stack and key rotation).

**5. Run the tests:**

```bash
python -m uv run pytest -q -m "not infra"                       # about 9 minutes; needs Postgres, OPA and Tesseract
opa test policy
```

**Use it from an agent.** Print a Claude Desktop MCP config (no secrets in it) with `python -m actionproof.server --print-config`. A LangChain agent can wrap its tools with the adapter: see `examples/langchain_agent.py` and [docs/API.md](docs/API.md).

## Environment variables

Every variable is documented, one comment each, in [`.env.example`](.env.example). The ones you will touch first:

| Variable | What it is |
|---|---|
| `DATABASE_URL` | Postgres connection string. Use `127.0.0.1`, not `localhost` (on Windows `localhost` adds about 2 s per connection). |
| `OPA_URL`, `OPA_TIMEOUT_SECONDS` | The OPA sidecar and the gate's timeout (any error or timeout is a DENY). |
| `TESSERACT_CMD` | The OCR binary (`tesseract` if on PATH, else the full path). |
| `SIGNING_KEY_PATH` | The Ed25519 seed file, read only by the gate process. |
| `RECEIPT_TTL_SECONDS`, `REVIEW_RECEIPT_TTL_SECONDS` | How long an approval stays valid. |
| `ACTIONPROOF_ACTOR`, `ACTIONPROOF_ON_BEHALF_OF` | The identity the operator assigns an MCP client. The agent can't choose it. |
| `GROQ_API_KEY`, `JUDGE_MODEL` | Only for the LLM-judge arm of the evaluation. Put them in a git-ignored `.env`. |
| `NEXT_PUBLIC_API_BASE`, `CONSOLE_API_ORIGIN` | How the website reaches the console API. |

## How it works: five steps

| # | Step | What happens |
|---|---|---|
| 1 | **Intercept** | An MCP proxy sits in front of every tool call. Default deny: unknown tools and malformed calls are refused. |
| 2 | **Verify** | Cited values are re-extracted (PDF text layer plus an independent OCR pass), derived values are recomputed by allowlisted pure functions, document-sourced text is tainted. |
| 3 | **Authorize** | OPA/Rego policy, a dry-run diff and the record's state version decide ALLOW, REVIEW or DENY. Every reason names its rule id and guarantee. |
| 4 | **Receipt and commit** | ALLOW or an approved REVIEW yields a signed Ed25519 receipt that is single-use (DB constraints), expires and binds to the request hash and record version. The commit re-checks state, then calls the tool. |
| 5 | **Audit** | A hash-chained log with signed checkpoints and a verifier CLI that needs only the database and a public key. |

Agent and documents are untrusted. The gateway (MCP server, verifier, signer) is trusted and holds the key. OPA is reached only by the gateway. PostgreSQL enforces G2 with UNIQUE constraints. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

### The three claim types

- **DIRECT**: copied from a cited box in a document. Re-extracted and compared at that box.
- **DERIVED**: computed from other claims. Recomputed by the gate from an allowlisted pure function; the model never does arithmetic.
- **ASSERTED**: the agent's own say-so. It never authorizes anything, and document-tainted values can never fill an authority field.

### Invariants (each has a guarding test)

| # | Invariant | Guarantee | Guard (tests/) |
|---|---|---|---|
| 1 | Fail closed: any exception, timeout, unknown tool or unknown field = DENY | G1 | usp/test_fail_closed.py |
| 2 | The model never does arithmetic; DERIVED values come from allowlisted pure functions | G1 | usp/test_derived_only_pure.py |
| 3 | ASSERTED or doc-tainted values never fill an authority field | G1 | usp/test_taint.py |
| 4 | Amounts are Decimal strings; no floats in contracts, policy input, signatures, DB | G1 | usp/test_no_floats.py |
| 5 | Receipts and review tokens are single-use (DB constraint), expire, bind to request hash + record version | G2 | usp/test_replay.py |
| 6 | Signing key unreachable from anything the agent can call | G1+G2 | usp/test_key_isolation.py |
| 7 | Nothing hardcoded: config from validated env, API types generated from OpenAPI, every number on screen fetched from the backend | - | tests/test_config.py, web e2e |

## Evaluation

Five arms (no gate, schema only, LLM judge, policy-only gateway, ActionProof) run over a handwritten attack set, a second handwritten set and a benign set. The runner and metrics are in `eval/`; the full report is [docs/EVAL.md](docs/EVAL.md) (rendered from `eval/results.json`). The numbers below are filled in after the final eval run by `python scripts/fill_readme_eval.py`.

<!-- EVAL-TABLE -->
| Arm | Attacks succeeded | False blocks (benign) | Added p95 (ms) |
|---|---|---|---|
| no_gate | 190 / 211 | 0 / 120 (0.0%) | 0 |
| schema_only | 182 / 211 | 0 / 120 (0.0%) | 7 |
| llm_judge | 114 / 211 | 43 / 120 (35.8%) | 2631 |
| policy_gateway | 97 / 211 | 31 / 120 (25.8%) | 47 |
| actionproof | 0 / 211 | 1 / 120 (0.8%) | 140 |

Run on commit `3eb62f3c6e`. Held-out set: handwritten2 (held-out-ish, NOT independent), n = 118; NOT independent.
Proposed targets (not results): at most 0 held-out successes, false-block rate at most 5%, added p95 at most 250 ms. Met: held-out successes True, false blocks True, latency True.
<!-- /EVAL-TABLE -->

## Challenges and roadmap

**Challenges we hit, and what we did**

- **A red team broke the first gate in 14 ways** (a derivation that wasn't pinned, an identity the agent could choose, no fresh re-check at commit, a burned receipt that left the invoice open). Each is fixed and kept as a regression test in `tests/redteam/`.
- **Cumulative caps need the database, not the app.** Two concurrent $4,900 approvals could both pass a naive check, so the cap is re-checked inside the serializable commit transaction, per actor and per person.
- **Latency.** The first measurement was 806 ms at p95, dominated by starting an OCR process per read. A per-request read cache, one OCR batch per request and a warm process pool brought it to 140 ms without lowering a single check.
- **OCR can misread.** The two-reader agreement fails closed, so a misread becomes a false block, not a wrong approval. We measured the rate on 120 benign cases instead of hiding it.

**Roadmap**

- An independent attack generator (ours was blocked, see below), so the held-out result can be independent.
- Real connectors (an ERP, a payment provider) in place of the mocks.
- Audit sequencing (a sequence-allocated audit seq with one chain-linking writer): measured in ADR-036 as the real throughput limit; per-actor locks alone would not help.
- Signed lookups for the refunds and proxy adapters, and the gate writing journal checkpoints itself.
- A remote or WORM anchor for the audit chain (the local file anchor exists, but it shares the host's trust domain).
- Verify the remote anchor against a real append-only provider, and run the live-LLM agent example with a real key.
- Reach Google's 2.5 s LCP by splitting the home page into server components (hydration is the remaining cost).

## Honest disclosures

- The independent attack generator was blocked, so the second attack set is **handwritten by the same team and is NOT independent**. The "held-out" label means held-out-ish, not independent.
- The live-LLM example has run twice with one real model (Groq `gpt-oss-120b`, free tier); the Anthropic client path has not been run live. Model behaviour is not deterministic: the claim is only that an unsafe write never executes.
- The remote anchor adapter is tested only against a local stub; the local anchor shares the host's trust domain.
- The TLA+ result is for a small bounded instance; it checks the design, not the Python code.
- Mocks only: no real ERP, no real payment provider.
- The Lighthouse LCP budget was set to 3.2 s to match what was measured (hydration cost); it is not at the 2.5 s "good" line.

## Limits (deck slide 10)

- Verifier-bound: Only as good as its deterministic verifiers. Free-form judgments can't be proven.
- Semantic fraud: A fake invoice that looks internally consistent is out of scope.
- The gate is a target: The signing key must stay out of the agent's reach, and the gateway needs hardening.
- Safety, not judgment: It stops unauthorized actions. It doesn't guarantee a good business decision.

## Docs

[RUNBOOK](docs/RUNBOOK.md) · [DEMO](docs/DEMO.md) · [API](docs/API.md) · [POLICY](docs/POLICY.md) · [THREAT_MODEL](docs/THREAT_MODEL.md) · [DECISIONS](docs/DECISIONS.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [DATA_MODEL](docs/DATA_MODEL.md) · [TESTING](docs/TESTING.md) · [DECK_TRACE](DECK_TRACE.md)

**Prove the action before the system executes it.**
