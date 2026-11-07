# ActionProof — project rules

**USP: Proof before permission.** No value can authorize a write unless its derivation re-checks (**G1**), and no approval can be replayed (**G2**).
Source of truth: the CodeQuest 2026 deck (`D:\SOHAM ALL\hackathons\ALL IDEA\ActionProof — CodeQuest 2026.pdf`), traced row by row in `DECK_TRACE.md`.

## Invariants (a test guards each; never weaken)
| # | Invariant | Guarantee | Guard (tests/) |
|---|---|---|---|
| 1 | Fail closed: any exception, timeout, unknown tool or unknown field = DENY | G1 | usp/test_fail_closed.py |
| 2 | The model never does arithmetic; DERIVED values come from allowlisted pure functions | G1 | usp/test_derived_only_pure.py |
| 3 | ASSERTED or doc-tainted values never fill an authority field | G1 | usp/test_taint.py |
| 4 | Amounts are Decimal strings; no floats in contracts, policy input, signatures, DB | G1 | usp/test_no_floats.py |
| 5 | Receipts and review tokens are single-use (DB constraint), expire, bind to request hash + record version | G2 | usp/test_replay.py |
| 6 | Signing key unreachable from anything the agent can call | G1+G2 | usp/test_key_isolation.py |
| 7 | Nothing hardcoded: config from validated env, API types generated from OpenAPI, every number on screen fetched from the backend | — | tests/test_config.py, web e2e |

## Working rules
- Docs are written WITH the code. A phase gate fails if its docs or DECK_TRACE rows are stale.
- A gate passes only with real command output shown. Never claim an unrun check.
- Minimum code (ponytail). No abstraction with one implementation. Ask before adding a dependency not named in the brief/deck.
- Deliberate shortcut: `# ponytail: <ceiling>, <upgrade path>`. A shortcut never removes a deck item.
- Every DENY/REVIEW reason names the guarantee (G1/G2) and the rule id.
- Each phase gate adds one line to PROGRESS.md: "USP: what this phase proved about G1/G2."
- On "continue": read PROGRESS.md, DECK_TRACE.md, docs/IMPLEMENTATION.md, resume.

## Subagent routing (subagent-driven-development)
| Task kind | Model | Examples |
|---|---|---|
| Hard: security-critical, concurrency, multi-file design, red-team, final reviews | `opus` (Opus 5.5) | contracts, extract, verify, gate.commit, policy, gate-reviewer |
| Mechanical: spec fully written, 1-2 files, docs, fixtures, boilerplate | `haiku` (Haiku 5.5) | fixtures/make.py, THREAT_MODEL/TESTING docs, mocks scaffolds, CI yaml |
Always set `model` explicitly on dispatch. One implementer at a time per file set; briefs and reports passed as files in `.superpowers/sdd/`. Controller verifies by running tests itself.

## Conventions
- bbox = `[x0, top, x1, bottom]`, PDF points, top-left origin, pages 1-indexed. Times are UTC epoch seconds.
- Amounts: `Decimal` parsed from strings with 2 dp. Canonical bytes = RFC 8785; `request_hash = sha256(canonical)`.
- Python 3.12, src layout (`src/actionproof/`), tests in `tests/`, USP suite in `tests/usp/` (CI runs it first as "USP: proof before permission").

## Commands
| Task | Command |
|---|---|
| Install | `python -m uv sync` |
| Infra up | `docker compose up -d postgres opa` |
| All tests | `python -m uv run pytest` |
| USP suite | `python -m uv run pytest tests/usp -v` |
| OPA tests | `C:/Users/Soham/tools/opa/opa.exe test policy -v` (or `docker run --rm -v ./policy:/p openpolicyagent/opa test /p -v`) |
| Local Postgres (no Docker) | `python scripts/dev_pg.py start` (port 5433; binaries in `C:/Users/Soham/tools/pgsql`) |
