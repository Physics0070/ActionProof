**Proof before permission.**

# ActionProof

**Before an AI agent acts, prove it should.**

ActionProof is a safety gate between an AI agent and the tools that change real systems: it re-checks every value the agent cites against the source document and the system of record, then issues a signed, single-use, human-approvable receipt before anything is written.

- **G1:** no value can authorize a write unless its derivation re-checks.
- **G2:** no approval can be replayed.

This is a prototype. Invoice approval is the hero demo; a refund connector uses the same gate. Services are mocks: no real credentials, no real payments.

## How it works: five steps

| # | Step | What happens |
|---|---|---|
| 1 | **Intercept** | An MCP proxy sits in front of every tool call. Default deny: unknown tools and malformed calls are refused. |
| 2 | **Verify** | Cited values are re-extracted (PDF text layer plus an independent OCR pass), derived values are recomputed by allowlisted pure functions, document-sourced text is tainted. |
| 3 | **Authorize** | OPA/Rego policy, a dry-run diff and the record's state version decide ALLOW, REVIEW or DENY. Every reason names its rule id and guarantee. |
| 4 | **Receipt and commit** | ALLOW or an approved REVIEW yields a signed Ed25519 receipt that is single-use (DB constraints), expires and binds to the request hash and record version. The commit re-checks state, then calls the tool. |
| 5 | **Audit** | A hash-chained log with signed checkpoints and a verifier CLI that needs only the database and a public key. |

## The three claim types

Every value an agent sends carries a claim type:

- **DIRECT**: copied from a cited box in a document. Re-extracted and compared at that box.
- **DERIVED**: computed from other claims. Recomputed by the gate from an allowlisted pure function; the model never does arithmetic.
- **ASSERTED**: the agent's own say-so. It never authorizes anything, and document-tainted values can never fill an authority field.

## Invariants (each has a guarding test)

| # | Invariant | Guarantee | Guard (tests/) |
|---|---|---|---|
| 1 | Fail closed: any exception, timeout, unknown tool or unknown field = DENY | G1 | usp/test_fail_closed.py |
| 2 | The model never does arithmetic; DERIVED values come from allowlisted pure functions | G1 | usp/test_derived_only_pure.py |
| 3 | ASSERTED or doc-tainted values never fill an authority field | G1 | usp/test_taint.py |
| 4 | Amounts are Decimal strings; no floats in contracts, policy input, signatures, DB | G1 | usp/test_no_floats.py |
| 5 | Receipts and review tokens are single-use (DB constraint), expire, bind to request hash + record version | G2 | usp/test_replay.py |
| 6 | Signing key unreachable from anything the agent can call | G1+G2 | usp/test_key_isolation.py |
| 7 | Nothing hardcoded: config from validated env, API types generated from OpenAPI, every number on screen fetched from the backend | - | tests/test_config.py, web e2e |

## Architecture

Agent and documents are untrusted. The gateway (MCP server, verifier, signer) is trusted and holds the key. OPA is reached only by the gateway. PostgreSQL enforces G2 with UNIQUE constraints. A Next.js review console shows reviewers the source span behind every claim. Details, sequence diagrams and trust boundaries: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Data model: [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

## Quickstart

Python 3.12, `python -m uv sync` first.

### Path A: Docker compose
Full steps and caveats are in [docs/RUNBOOK.md](docs/RUNBOOK.md).
```bash
python scripts/gen_key.py keys/signing.key
python -c "import secrets,sys;sys.stdout.write(secrets.token_hex(24))" > keys/pg_password
cp .env.example .env
DEMO_SEED=1 docker compose -f docker-compose.yml up -d --build   # DEMO_SEED=1 wipes all tables
# web http://127.0.0.1:5173, api http://127.0.0.1:8766
```

### Path B: no Docker (dev)
```bash
python scripts/dev_pg.py start                 # local Postgres on :5433
opa run --server --addr 127.0.0.1:8181 --watch policy &   # any local OPA binary (OPA_BIN in .env.example)
python scripts/gen_key.py keys/dev-signing.key
python scripts/demo_seed.py --reset && python scripts/seed_console.py
python -m actionproof.console                  # review console API
cd web && npm install && npm run dev           # http://localhost:5173
```

### Run the demo
```bash
bash demo.sh        # plays every beat against the real gate; exit 0 only if each produced its expected outcome
DEMO_PAUSE=1 bash demo.sh
```
It uses its own database and starts local Postgres and OPA if they are not reachable. Script of the video and judge Q&A: [docs/DEMO.md](docs/DEMO.md).

### Use it from an agent
Claude Desktop (MCP stdio): print a config snippet, with no secrets in it, and paste it into your `mcpServers`.
```bash
python -m actionproof.server --print-config
```
A LangChain agent can wrap its existing tools with the adapter: see `examples/langchain_agent.py` and [docs/API.md](docs/API.md).

## Evaluation

Five arms (no gate, schema only, LLM judge, policy-only gateway, ActionProof) run over a handwritten attack set, a second handwritten set and a benign set. The runner and metrics are in `eval/`; the full report is [docs/EVAL.md](docs/EVAL.md) (rendered from `eval/results.json`). The numbers below are filled in after the final eval run by `python scripts/fill_readme_eval.py`.

<!-- EVAL-TABLE -->
**Not run yet.** The evaluation numbers are filled in after the final eval run (`python -m eval.run`, then `python scripts/fill_readme_eval.py`). Until then this README claims none.
<!-- /EVAL-TABLE -->

## Honest disclosures

- The independent attack generator was blocked, so the second attack set is **handwritten by the same team and is NOT independent**. The "held-out" label means held-out-ish, not independent. Targets in the deck (0 successful attacks on the held-out set, at most 5% false blocks, p95 under 250 ms added) are proposed targets, not results.
- The Docker compose stack has never been run on the build machine (no Docker engine). The local no-Docker path is the one exercised.
- Mocks only: no real ERP, no real payment provider.

## Limits (deck slide 10)

- Verifier-bound: Only as good as its deterministic verifiers. Free-form judgments can't be proven.
- Semantic fraud: A fake invoice that looks internally consistent is out of scope.
- The gate is a target: The signing key must stay out of the agent's reach, and the gateway needs hardening.
- Safety, not judgment: It stops unauthorized actions. It doesn't guarantee a good business decision.

## Docs

[RUNBOOK](docs/RUNBOOK.md) · [DEMO](docs/DEMO.md) · [API](docs/API.md) · [POLICY](docs/POLICY.md) · [THREAT_MODEL](docs/THREAT_MODEL.md) · [DECISIONS](docs/DECISIONS.md) · [ARCHITECTURE](docs/ARCHITECTURE.md)

**Prove the action before the system executes it.**
