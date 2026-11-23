# Formal model (TLA+) — ActionProof commit and execution protocol

`ActionProof.tla` + `ActionProof.cfg`: a bounded model of the receipt-commit-execute protocol: durable reservation before
dispatch, concurrent receipts for one request, a review token, the cumulative cap, crashes, ambiguous outcomes and
evidence-based reconciliation. `MAPPING.md` ties every action and invariant to source files and regression tests.
TLA+ is a design-time tool only: nothing here is a runtime dependency.

## Run (TLC)
```
java -cp tla2tools.jar tlc2.TLC -config formal/ActionProof.cfg formal/ActionProof.tla
```
(`tla2tools.jar` from https://github.com/tlaplus/tlaplus/releases, or the TLA+ Toolbox / VS Code extension.)
**Status: model-checked in CI (bounded).** The `TLA+ model check (TLC)` job in `.github/workflows/ci.yml` runs exactly the
command above (tla2tools v1.8.0, Temurin 21) on the committed `ActionProof.tla` + `ActionProof.cfg`. Result: "Model checking
completed. No error has been found." 108,483 states generated, 72,926 distinct, 0 left on the queue. The files were last
changed in commit f164dc4, which is the commit that run checked; any later edit to `formal/` must re-run that job and update
this paragraph. Scope: three nonces, two request keys, one token. It checks the design, not the Python code (see Assumptions).

## What is modelled
Prepare (a receipt exists), Reserve (atomic under the commit lane lock: key uniqueness, cap including every unresolved
reservation, token available, then the durable `tool_reached` row), Dispatch, the environment (`Land`: the call takes
effect even after a crash; `Drop`: the call is definitively rejected), Confirm, Fail (definite failure, reservation
burned), Crash (outcome ambiguous, nothing released, an in-flight call is not cancelled), ReconcileDone / ReconcileFailed
(evidence: effect observed, or neither happened nor can). There is no time-based release action.

## Properties checked (when TLC is run)
G2: `ResOnce` (one reservation per nonce), `KeyOnce` and `KeyEffectOnce` (one reservation and at most one effect per
idempotency key), `TokenOnce` (a token authorizes one commit). Spending: `SpendCap`, `UnknownHeld`. Execution:
`DispatchNeedsReservation`, `JournalOrder`, `ConfirmedTruthful`, `ReleasedHadNoEffect`. Recovery: `NoRedispatch`
(an UNKNOWN execution is never re-dispatched or re-confirmed; it stays unknown or is reconciled).

## Assumptions and limits (explicit)
- The model starts after a receipt is issued: G1 evidence verification, signatures, OPA decisions and the policy revision
  are outside it. Receipt expiry, record versions and stale-record checks are not modelled.
- `Reserve` is one atomic step: it stands for the global commit lane (`LOCK TABLE commits ... SHARE ROW EXCLUSIVE`) plus
  SERIALIZABLE; PostgreSQL's own concurrency behaviour is assumed, not modelled. The commit lane is a known contention limit.
- One actor/counterparty and one cap; amounts are small integers (cents scaled down). Decimal arithmetic is not modelled.
- Reconciliation evidence is assumed truthful (a wrong human decision, or a downstream that lies, breaks the properties).
  `Drop` and `Land` stand for provider behaviour; exactly-once for an arbitrary external system is NOT claimed.
- A failed (burned) reservation stays counted and its key stays held, as in ADR-010; the model has no un-burn.
- Bounded: three nonces, two keys, one token. A pass is evidence for this instance, not a proof for all sizes.
- The model does not prove the Python implementation; `MAPPING.md` lists the tests that exercise each transition.
