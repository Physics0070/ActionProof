"""USP G2: the execution gap (deck S2.4) -- retries, stale records and check-then-commit races cannot repeat or
invalidate an approved write. The gate re-checks state in the commit tx and calls the tool at most once.
"""
from gatekit import rules


def _ready(kit, invoice_id="INV-8001", total="100.00"):
    req, docs = kit.json_request(invoice_id, total)
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW", r.reasons
    return req, r.receipt


def test_mutated_mid_flight_by_hook(kit):
    """USP G2: a record mutated inside the commit, right before the tool applies, is AP-STALE-07; nothing paid."""
    req, receipt = _ready(kit)

    def bump(conn, record_id):
        conn.execute("UPDATE records SET version = version + 1 WHERE record_id = %s", (record_id,))

    kit.erp.mutate_before_execute = bump
    c = kit.gate.commit(receipt, req)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-STALE-07", "G2")]
    assert kit.tool.calls == [] and kit.version("invoice:INV-8001") == 1  # rolled back
    kit.erp.mutate_before_execute = None
    assert rules(kit.gate.commit(receipt, req)) == ["AP-REP-05"]  # the tool was reached: receipt is spent
    assert kit.tool.calls == []


def test_mutated_between_prepare_and_commit(kit):
    """USP G2: a direct DB version bump between prepare and commit is AP-STALE-07; the tool is never called."""
    req, receipt = _ready(kit)
    kit.sql("UPDATE records SET version = version + 1 WHERE record_id = 'invoice:INV-8001'")
    c = kit.gate.commit(receipt, req)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-STALE-07", "G2")]
    assert kit.tool.calls == [] and kit.executes == 0 and kit.commits() == 0


def test_data_changed_without_version_bump(kit):
    """USP G2: the diff hash binds the before-state, so a silent data edit (same version) is AP-STALE-07."""
    req, receipt = _ready(kit)
    kit.sql("UPDATE records SET data = data || '{\"vendor_id\": \"V-EVIL\"}'::jsonb WHERE record_id = 'invoice:INV-8001'")
    assert rules(kit.gate.commit(receipt, req)) == ["AP-STALE-07"]
    assert kit.tool.calls == []


def test_retried_write_pays_once(kit):
    """USP G2: the tool fails after its side effect; the client retries with the same receipt; one payment."""
    req, receipt = _ready(kit)
    kit.tool.fail_after_effect = True
    first = kit.gate.commit(receipt, req)
    assert rules(first) == ["AP-ERR-11"]
    assert len(kit.tool.calls) == 1  # the effect happened tool-side
    retry = kit.gate.commit(receipt, req)
    assert rules(retry) in (["AP-REP-05"], ["AP-ERR-11"])
    assert rules(retry) == ["AP-REP-05"]  # as built: the reached-tool receipt is burned
    assert len(kit.tool.calls) == 1 and kit.executes == 1


def test_stale_read_lie_does_not_bypass_gate(kit):
    """USP G2: the tool lies about the version at prepare and skips its own check; the gate's DB check holds."""
    kit.seed_invoice("INV-8002", "100.00", "100.00")
    kit.sql("UPDATE records SET version = 2 WHERE record_id = 'invoice:INV-8002'")
    kit.erp.stale_read = True
    kit.tool.ignore_version = True
    req, docs = kit.json_request("INV-8002", "100.00", seed=False)
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW" and r.receipt["payload"]["version"] == 1  # the lie made it into the receipt
    c = kit.gate.commit(r.receipt, req)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-STALE-07", "G2")]
    assert kit.tool.calls == [] and kit.executes == 0


def test_ignore_version_tool_with_mid_flight_mutation(kit):
    """USP G2: a tool that skips its own version check still cannot commit over a mid-flight mutation."""
    req, receipt = _ready(kit)
    kit.tool.ignore_version = True
    kit.erp.mutate_before_execute = lambda conn, rid: conn.execute(
        "UPDATE records SET version = version + 1 WHERE record_id = %s", (rid,))
    c = kit.gate.commit(receipt, req)
    assert rules(c) == ["AP-STALE-07"]
    assert kit.executes == 1 and kit.version("invoice:INV-8001") == 1  # DB write rolled back
    # ponytail: the hostile tool already recorded its (mock) side effect; tool-side idempotency bounds it.


def test_double_call_tool_bounded(kit):
    """USP G2: the GATE calls execute once. A tool that applies twice is caught by the post-execute version check
    and rolled back.
    # ponytail: tool-side hostility (a real double payment) is bounded only by the tool's idempotency key;
    # the gate guarantees its own at-most-once call and a consistent system of record.
    """
    req, receipt = _ready(kit)
    kit.tool.double_call = True
    c = kit.gate.commit(receipt, req)
    assert kit.executes == 1
    assert rules(c) == ["AP-STALE-07"] and kit.version("invoice:INV-8001") == 1
    assert rules(kit.gate.commit(receipt, req)) == ["AP-REP-05"] and kit.executes == 1


def test_tool_error_before_effect(kit, monkeypatch):
    """USP G2: a tool that raises is AP-ERR-11, rolled back, and the receipt is spent (outcome unknown)."""
    req, receipt = _ready(kit)

    def broken(*a, **kw):
        raise RuntimeError("upstream 502 with secret body")

    monkeypatch.setattr(kit.tool, "execute", broken)
    c = kit.gate.commit(receipt, req)
    assert rules(c) == ["AP-ERR-11"] and "secret" not in c.reasons[0].msg
    assert kit.version("invoice:INV-8001") == 1
    assert rules(kit.gate.commit(receipt, req)) == ["AP-REP-05"]
