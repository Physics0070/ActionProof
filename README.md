**Proof before permission.**

<p align="center"><img src="web/public/og.png" alt="ActionProof: before an AI agent acts, prove it should" width="860"></p>

# ActionProof

### Before an AI agent acts, prove it should.

> **ActionProof is a safety gate that makes an AI agent prove every value behind a write before the write can run, and never lets one approval run twice.**
> It helps developers shipping agents, finance and operations teams who approve what agents do, and security teams who need a tamper-evident record.

CodeQuest 2026 submission by team **Bench Warmers**. This is a prototype on mock services: no real credentials, no real payments.

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
| **Pitch video** (2:50) | _add the upload link here before submitting_ |
| **Live deployment** | https://actionproof-web.onrender.com (Render free tier: the first request after idle takes ~1 min to wake; the demo database resets about 30 days after creation). Local alternative: `bash demo.sh` (see [Installation](#installation-guide)) |
| **Demo script and judge Q&A** | [docs/DEMO.md](docs/DEMO.md) |
| **Evaluation report** | [docs/EVAL.md](docs/EVAL.md) |

`demo.sh` plays every beat against the real gate and exits 0 only if each produced its expected outcome: the honest invoice pauses for review and a different person approves it; an injected PDF is denied; a replayed approval is denied; two concurrent $4,900 approvals under a $5,000 cap let exactly one through; a second connector (refunds) hits the same gate; and the audit chain verifies.

## Core features

- **Evidence-verified arguments.** Every value carries a claim type and is re-extracted at the cited page and box by two independent readers (PDF text layer plus an OCR pass). The two must agree, or the claim fails.
- **No model arithmetic.** Derived values (like the $500 variance) are recomputed by allowlisted pure functions, never trusted from the agent.
- **Taint rule.** Text that came from a document can be shown to a reviewer but can never fill an authority field.
- **Policy with named reasons.** OPA/Rego decides ALLOW, REVIEW or DENY, and every reason names its rule id and guarantee (G1 or G2).
- **Signed, single-use receipts.** The commit re-checks state in one serializable transaction, with cumulative caps per actor and per person, then calls the tool at most once.
- **Review console.** A human sees the source span highlighted on the PDF page and approves or rejects with a typed reason. The reviewer must be a different person than the requester.
- **Tamper-evident audit.** A hash-chained log with signed checkpoints and a verifier CLI that needs only the database and a public key.
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
- Per-actor commit locks and an outbox, so throughput isn't limited by one commit lane.
- An external anchor for the audit chain, so deleting the newest entries together with their checkpoints is detectable.
- Run the Docker stack, the Playwright end-to-end specs and Lighthouse on a real machine.

## Honest disclosures

- The independent attack generator was blocked, so the second attack set is **handwritten by the same team and is NOT independent**. The "held-out" label means held-out-ish, not independent. Targets in the deck (0 successful attacks on the held-out set, at most 5% false blocks, p95 under 250 ms added) are proposed targets, not results.
- The Docker compose stack has never been run on the build machine (no Docker engine). The local no-Docker path is the one exercised.
- The Playwright end-to-end specs and the Lighthouse budgets are written but were never run.
- Mocks only: no real ERP, no real payment provider.

## Limits (deck slide 10)

- Verifier-bound: Only as good as its deterministic verifiers. Free-form judgments can't be proven.
- Semantic fraud: A fake invoice that looks internally consistent is out of scope.
- The gate is a target: The signing key must stay out of the agent's reach, and the gateway needs hardening.
- Safety, not judgment: It stops unauthorized actions. It doesn't guarantee a good business decision.

## Docs

[RUNBOOK](docs/RUNBOOK.md) · [DEMO](docs/DEMO.md) · [API](docs/API.md) · [POLICY](docs/POLICY.md) · [THREAT_MODEL](docs/THREAT_MODEL.md) · [DECISIONS](docs/DECISIONS.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [DATA_MODEL](docs/DATA_MODEL.md) · [TESTING](docs/TESTING.md) · [DECK_TRACE](DECK_TRACE.md)

**Prove the action before the system executes it.**
