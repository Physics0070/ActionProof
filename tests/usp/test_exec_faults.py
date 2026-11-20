"""USP G2: failure injection on Gate.commit against real Postgres.

The fake downstream keeps its OWN side-effect log in process memory, outside the DB transaction, so a rollback or
a crash of the gate cannot erase what the "remote" system did. The question each test answers: can an external
effect happen without a recorded commit, and can a retry of the same receipt cause a second effect?

A crash is simulated with a BaseException (ProcessCrash): the gate's `except Exception` handlers do not run, exactly
as when the OS kills the process. Races use a threading.Barrier, never sleeps.
"""
import threading

import pytest
from gatekit import INVOICE_TOOL, rules

from actionproof.mocks import MockPayments


class ProcessCrash(BaseException):
    """The process dies here: no gate cleanup (burn, rollback handlers) gets to run."""


class ExternalPSP(MockPayments):
    """A downstream with its own durable log. idempotent=True models a provider that dedupes on the key
    the gate passes (Mode A); False models one that does not (Mode C)."""

    def __init__(self, erp, factory, idempotent: bool):
        super().__init__(erp, factory)
        self.idempotent = idempotent
        self.log: list[str] = []          # external side effects, never rolled back
        self.crash_before = False
        self.crash_after = False
        self.timeout_after = False

    def execute(self, req, expected_version, idempotency_key, conn):
        if self.crash_before:
            raise ProcessCrash("before call")
        if not (self.idempotent and idempotency_key in self.log):
            self.log.append(idempotency_key)  # the money moves
        result = super().execute(req, expected_version, idempotency_key, conn)
        if self.crash_after:
            raise ProcessCrash("after call, before DB commit")
        if self.timeout_after:
            raise TimeoutError("ambiguous: response lost")
        return result


def _setup(kit, idempotent, invoice="INV-8101"):
    psp = ExternalPSP(kit.erp, kit.factory, idempotent)
    kit.gate._tools[INVOICE_TOOL] = psp
    req, docs = kit.json_request(invoice, "100.00")
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW", r.reasons
    return psp, req, r.receipt


@pytest.mark.parametrize("idempotent", [True, False])
def test_crash_before_call_no_effect_and_no_double(kit, idempotent):
    """Process dies before the downstream is reached: nothing happened, a retry never causes two effects."""
    psp, req, receipt = _setup(kit, idempotent)
    psp.crash_before = True
    with pytest.raises(ProcessCrash):
        kit.gate.commit(receipt, req)
    assert psp.log == [] and kit.commits() == 0
    psp.crash_before = False
    kit.gate.commit(receipt, req)  # executes once, or is refused: either is safe
    assert len(psp.log) <= 1 and kit.commits() <= 1


@pytest.mark.parametrize("idempotent", [True, False])
def test_crash_after_call_retry_must_not_double_execute(kit, idempotent):
    """Process dies after the downstream succeeded but before the DB commit. The DB rolled back (no commit row),
    yet the effect exists. A retry of the SAME receipt must not cause a second effect, even for a provider with
    no idempotency (Mode C): the gate itself must remember that the tool was reached."""
    psp, req, receipt = _setup(kit, idempotent)
    psp.crash_after = True
    with pytest.raises(ProcessCrash):
        kit.gate.commit(receipt, req)
    assert len(psp.log) == 1                      # the effect happened outside the DB
    assert kit.commits() == 0                     # and the DB has no record of it (rolled back)
    psp.crash_after = False
    retry = kit.gate.commit(receipt, req)         # a new process, same receipt
    assert len(psp.log) == 1, "second external effect after a crash: the gate re-called the downstream"
    if not idempotent:
        assert retry.outcome != "EXECUTED"


def test_ambiguous_timeout_burns_receipt_and_quarantines(kit):
    """The downstream effect happened but the response was lost (timeout). The tx rolls back; the gate burns the
    receipt, counts the amount toward the cap and quarantines the record. No second effect on retry."""
    psp, req, receipt = _setup(kit, idempotent=False)
    psp.timeout_after = True
    first = kit.gate.commit(receipt, req)
    assert rules(first) == ["AP-ERR-11"] and len(psp.log) == 1
    assert kit.sql("SELECT count(*) FROM commits")[0][0] == 1          # burn row: amount counts
    assert kit.sql("SELECT count(*) FROM quarantine")[0][0] == 1       # record frozen until a human reconciles
    psp.timeout_after = False
    assert rules(kit.gate.commit(receipt, req)) == ["AP-REP-05"]
    assert len(psp.log) == 1


def test_concurrent_same_receipt_one_effect(kit):
    """Eight threads commit the same receipt behind a barrier: exactly one EXECUTED, exactly one external effect."""
    psp, req, receipt = _setup(kit, idempotent=False)
    n, barrier, out = 8, threading.Barrier(8), []

    def go():
        barrier.wait()
        out.append(kit.gate.commit(receipt, req))

    ts = [threading.Thread(target=go) for _ in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sum(r.outcome == "EXECUTED" for r in out) == 1
    assert len(psp.log) == 1 and kit.commits() == 1


def test_audit_append_failure_means_tool_never_reached(kit):
    """If the EXECUTED audit entry cannot be written, the downstream is never called and nothing is consumed."""
    psp, req, receipt = _setup(kit, idempotent=False)
    real = kit.gate._audit

    def broken(conn, kind, **kw):
        if kind == "commit" and kw.get("decision") == "EXECUTED":
            raise RuntimeError("audit store unavailable")
        return real(conn, kind, **kw)

    kit.gate._audit = broken
    try:
        res = kit.gate.commit(receipt, req)
    finally:
        kit.gate._audit = real
    assert rules(res) == ["AP-ERR-11"]
    assert psp.log == [] and kit.commits() == 0 and kit.sql("SELECT count(*) FROM quarantine")[0][0] == 0
    assert kit.gate.commit(receipt, req).outcome == "EXECUTED" and len(psp.log) == 1  # the receipt was not consumed
