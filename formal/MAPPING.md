# Model to code mapping

Paths are in the repo; tests marked (P3) are added by the Phase 3 execution-journal work (ADR-029) and may be named
`tests/usp/test_exec_journal*.py`. Verify the names against the tree before citing them.

## Actions
| Model action | Stands for | Source | Regression tests |
|---|---|---|---|
| `Prepare` | gate-signed receipt (nonce, request hash, idempotency key) | `src/actionproof/gate.py` `_prepare` | tests/test_prepare.py, tests/usp/test_replay.py |
| `Reserve` | commit lane lock, nonce/key UNIQUE, cumulative cap over `reservations`, review token consume check, durable `tool_reached` row on its own connection | `gate.py` `_attempt`, `schema.sql` (`commits`, `tool_reached`, `reservations`, `review_tokens`) | tests/usp/test_replay.py, tests/usp/test_exec_reservations.py, tests/test_commit.py |
| `Dispatch` | DISPATCH_STARTED, then `tool.execute(...)` | `gate.py` `_attempt`; journal `src/actionproof/journal.py` (P3) | tests/usp/test_exec_reservations.py, (P3) journal tests |
| `Land` / `Drop` | downstream provider behaviour (environment) | mock adapters `src/actionproof/mocks/*` | tests/usp/test_exec_faults.py |
| `Confirm` | tool returned, main tx commits, token consumed, EXECUTION_CONFIRMED | `gate.py` `_attempt` end | tests/test_commit.py, (P3) |
| `Fail` | tool raised a definite failure; `_burn` keeps the amount counted and quarantines | `gate.py` `_burn` | tests/usp/test_exec_faults.py |
| `Crash` | process killed / connection lost / serialization failure after dispatch | `tests/usp/_crash_child.py` | tests/usp/test_exec_reservations.py::test_real_process_kill_after_the_effect, (P3) |
| `ReconcileDone` / `ReconcileFailed` | audited reconciliation with evidence or an authorized human | `gate.py` `release_quarantine`, `src/actionproof/reconcile.py`, (P3) journal resolve | tests/usp/test_migration_legacy_marker.py, (P3) |

## Invariants
| Invariant | Code that enforces it | Tests |
|---|---|---|
| `ResOnce`, `KeyOnce`, `KeyEffectOnce` | `commits.nonce` / `idempotency_key` UNIQUE, `tool_reached` PK and the unresolved-key check in `_attempt` | tests/usp/test_replay.py, test_exec_reservations.py |
| `TokenOnce` | atomic `UPDATE review_tokens ... used_at IS NULL` (ADR-025) | tests/usp/test_replay.py, test_review_token_hashed.py |
| `SpendCap`, `UnknownHeld` | `reservations` view in every cap sum (ADR-022); markers keep their amount until released | tests/usp/test_exec_reservations.py, test_migration_legacy_marker.py |
| `DispatchNeedsReservation`, `JournalOrder` | marker committed on a separate connection before `tool.execute` | tests/usp/test_exec_reservations.py, (P3) |
| `ConfirmedTruthful`, `ReleasedHadNoEffect` | success recorded only after the tool returns; release only through audited reconciliation | (P3) journal tests, test_gap_execution.py |
| `NoRedispatch` | unresolved marker => AP-REP-05 on retry (nonce or key) | tests/usp/test_exec_reservations.py |

## Not covered by the model
G1 evidence verification, signatures and key resolution, OPA and policy revision, receipt expiry and record versions, the
audit chain and anchors, separation of duties, credential scopes, and PostgreSQL's SERIALIZABLE behaviour itself.
