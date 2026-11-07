"""USP G1: the policy gap (deck S2.3) -- a valid tool name can still carry an amount, target or actor outside the
caller's scope; on_behalf_of scope is enforced (AP-SCOPE-02) and the tool is never reached.
"""
from gatekit import rules


def _assert_scope_denied(kit, r):
    assert r.decision == "DENY" and r.receipt is None
    assert {(x.rule, x.guarantee) for x in r.reasons} == {("AP-SCOPE-02", "G1")}
    assert kit.tool.calls == [] and kit.executes == 0


def test_amount_over_user_scope(kit):
    """USP G1: user-123 may approve up to 1000.00; a verified 4800.00 approval is AP-SCOPE-02."""
    kit.set_scope("1000.00")
    _assert_scope_denied(kit, kit.gate.prepare(*kit.hero()))


def test_vendor_outside_user_scope(kit):
    """USP G1: the vendor comes from the system of record, so the agent cannot relabel it into scope."""
    kit.set_scope("5000.00", vendors=["V-OTHER"])
    _assert_scope_denied(kit, kit.gate.prepare(*kit.json_request("INV-7101", "100.00")))


def test_no_delegation_no_scope(kit):
    """USP G1: an on_behalf_of with no delegation row has an empty scope (never a default grant)."""
    from actionproof.gate import Principal  # the session really is user-404's: the scope, not the binding, denies
    _assert_scope_denied(kit, kit.gate.prepare(*kit.json_request("INV-7102", "100.00", on_behalf_of="user-404"),
                                               principal=Principal("agent-7", "user-404")))


def test_scope_cannot_be_swapped_at_commit(kit):
    """USP G1: a receipt for an in-scope principal cannot be committed for another principal (hash bound)."""
    req, docs = kit.json_request("INV-7103", "100.00")
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW"
    c = kit.gate.commit(r.receipt, req.model_copy(update={"on_behalf_of": "user-999"}))
    assert rules(c) == ["AP-HASH-08"] and kit.tool.calls == []
