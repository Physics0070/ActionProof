"""Red team (Phase 3 gate), G1: principal, actor and scope values that authorize a write without a re-check.

Every assertion encodes the SAFE behavior. A failing test here is a finding.
"""
import pytest
from gatekit import AGENT, rules

from actionproof.gate import Principal


@pytest.mark.parametrize("alias", ["Agent-7", "agent-7 ", "agent-7​", "agent-8"])
def test_cumulative_cap_bypass_by_actor_alias(kit, alias):
    """AP-CUM-03 sums by the request's `actor` string, which the (untrusted) agent writes itself.
    Two 4900.00 approvals to the same vendor by the same agent under two spellings must not both execute."""
    a, da = kit.json_request("INV-RTA1", "4900.00", idem="alias-1")
    b, db = kit.json_request("INV-RTA2", "4900.00", idem="alias-2", actor=alias)
    ra = kit.gate.prepare(a, da)
    assert kit.gate.commit(ra.receipt, a).outcome == "EXECUTED"
    rb = kit.gate.prepare(b, db, principal=AGENT)  # the transport knows it is still agent-7
    if rb.receipt is not None:
        kit.gate.commit(rb.receipt, b, principal=AGENT)
    assert len(kit.tool.calls) == 1, "cap 5000.00 per agent+vendor exceeded via actor alias"
    assert kit.sql("SELECT SUM(amount)::text FROM commits WHERE vendor_id = 'V-ACME'") == [("4900.00",)]


def test_borrow_delegated_principal(kit):
    """`on_behalf_of` is agent-written and not bound to the actor: agent-7, delegated 500.00 by user-123, names a
    richer principal ('cfo', 5000.00) and is allowed 900.00."""
    kit.set_scope("500.00")
    kit.sql("INSERT INTO delegations (on_behalf_of, max_amount, vendors) VALUES ('cfo', 5000.00, ARRAY['V-ACME'])")
    req, docs = kit.json_request("INV-RTA3", "900.00", on_behalf_of="cfo")
    p = kit.gate.prepare(req, docs, principal=AGENT)  # the session is agent-7 for user-123, not cfo
    if p.receipt is not None:
        kit.gate.commit(p.receipt, req, principal=AGENT)
    assert p.decision == "DENY" and kit.tool.calls == []


def test_scope_revoked_between_prepare_and_commit(kit):
    """Delegation cut to 0.00 / no vendors after prepare: commit re-checks state (ARCHITECTURE step 4) but not scope."""
    req, docs = kit.json_request("INV-RTA4", "900.00")
    p = kit.gate.prepare(req, docs)
    assert p.decision == "ALLOW"
    kit.set_scope("0.00", vendors=[])
    c = kit.gate.commit(p.receipt, req)
    assert c.outcome == "DENY" and kit.tool.calls == []


def test_vendor_removed_from_scope_between_prepare_and_commit(kit):
    req, docs = kit.json_request("INV-RTA5", "900.00")
    p = kit.gate.prepare(req, docs)
    assert p.decision == "ALLOW"
    kit.set_scope("5000.00", vendors=["V-OTHER"])
    c = kit.gate.commit(p.receipt, req)
    assert c.outcome == "DENY" and kit.tool.calls == []


def test_po_total_changed_between_prepare_and_commit(kit):
    """The PO (a SOR input of the variance derivation) drops 1000.00 -> 500.00 after an ALLOW prepare: the true
    variance is now 500.00 (REVIEW). Commit re-checks only the invoice record's version and diff, not the PO."""
    req, docs = kit.json_request("INV-RTA8", "1000.00", "1000.00")
    p = kit.gate.prepare(req, docs)
    assert p.decision == "ALLOW"
    kit.sql("UPDATE records SET data = data || '{\"total\": \"500.00\"}'::jsonb, version = version + 1 "
            "WHERE record_id = 'po:PO-INV-RTA8'")
    c = kit.gate.commit(p.receipt, req)
    assert c.outcome == "DENY" and kit.tool.calls == []


def test_cap_counts_same_actor_across_principals(kit):
    """Regression guard: the cap key ignores on_behalf_of (HELD; mirrors tests/attacks)."""
    kit.sql("INSERT INTO delegations (on_behalf_of, max_amount, vendors) VALUES ('user-456', 5000.00, ARRAY['V-ACME'])")
    a, da = kit.json_request("INV-RTA6", "4900.00", idem="pp-1")
    b, db = kit.json_request("INV-RTA7", "4900.00", idem="pp-2", on_behalf_of="user-456")
    assert kit.gate.commit(kit.gate.prepare(a, da).receipt, a).outcome == "EXECUTED"
    rb = kit.gate.prepare(b, db, principal=Principal("agent-7", "user-456"))
    assert rb.receipt is None and "AP-CUM-03" in rules(rb)
    assert len(kit.tool.calls) == 1
