"""Attack S6.6 replay: one-use receipt, idempotency key and review token -> AP-REP-05 / G2."""
from gatekit import rules


def test_replayed_receipt(kit):
    req, docs = kit.json_request("INV-8701", "100.00")
    receipt = kit.gate.prepare(req, docs).receipt
    assert kit.gate.commit(receipt, req).outcome == "EXECUTED"
    kit.tool.calls.clear()
    c = kit.gate.commit(receipt, req)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-REP-05", "G2")]
    assert kit.tool.calls == []


def test_reused_key(kit):
    req, docs = kit.json_request("INV-8702", "100.00")
    r1, r2 = kit.gate.prepare(req, docs).receipt, kit.gate.prepare(req, docs).receipt
    assert kit.gate.commit(r1, req).outcome == "EXECUTED"
    kit.tool.calls.clear()
    assert [(x.rule, x.guarantee) for x in kit.gate.commit(r2, req).reasons] == [("AP-REP-05", "G2")]
    assert kit.tool.calls == []


def test_reused_review_token(kit):
    req, docs = kit.json_request("INV-8703", "4800.00", "4300.00")
    r1, r2 = kit.gate.prepare(req, docs).receipt, kit.gate.prepare(req, docs).receipt
    token = kit.mint(req)
    assert kit.gate.commit(r1, req, token).outcome == "EXECUTED"
    kit.tool.calls.clear()
    assert [(x.rule, x.guarantee) for x in kit.gate.commit(r2, req, token).reasons] == [("AP-REP-05", "G2")]
    assert kit.tool.calls == []


def test_review_token_for_other_request(kit):
    a, da = kit.json_request("INV-8704", "4800.00", "4300.00")
    b, db = kit.json_request("INV-8705", "4800.00", "4300.00")
    rb = kit.gate.prepare(b, db).receipt
    token = kit.mint(a)
    assert [(x.rule, x.guarantee) for x in kit.gate.commit(rb, b, token).reasons] == [("AP-REV-10", "G2")]
    assert kit.tool.calls == []
