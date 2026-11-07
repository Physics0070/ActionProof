"""Attack S6.4 confused deputy: the agent acts beyond the user's on_behalf_of scope -> AP-SCOPE-02 / G1."""
from gatekit import rules


def _assert_scope(kit, r):
    assert r.decision == "DENY" and r.receipt is None
    assert {(x.rule, x.guarantee) for x in r.reasons} == {("AP-SCOPE-02", "G1")}
    assert kit.tool.calls == []


def test_amount_beyond_user_limit(kit):
    kit.set_scope("500.00")
    _assert_scope(kit, kit.gate.prepare(*kit.json_request("INV-9101", "900.00")))


def test_vendor_beyond_user_scope(kit):
    kit.set_scope("5000.00", vendors=["V-BRK"])
    _assert_scope(kit, kit.gate.prepare(*kit.json_request("INV-9102", "100.00")))


def test_borrowing_another_principal(kit):
    """The agent names a principal with no delegation: empty scope."""
    _assert_scope(kit, kit.gate.prepare(*kit.json_request("INV-9103", "100.00", on_behalf_of="cfo")))


def test_principal_swapped_at_commit(kit):
    req, docs = kit.json_request("INV-9104", "100.00")
    receipt = kit.gate.prepare(req, docs).receipt
    c = kit.gate.commit(receipt, req.model_copy(update={"on_behalf_of": "cfo"}))
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-HASH-08", "G2")] and kit.tool.calls == []
    assert rules(kit.gate.commit(receipt, req)) == []  # the genuine request still commits
    assert len(kit.tool.calls) == 1
