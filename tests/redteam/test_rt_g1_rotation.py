"""Red team, G1: split payments by actor rotation (ADR-016).

agent-7 spends 4900.00 on a vendor for user-123; agent-8, another agent of the same human (people table), spends
another 4900.00 on the same vendor. The per-actor cap alone lets both execute; the per-person cap must not.
"""
from gatekit import rules

from actionproof.gate import Principal

from attacks._concurrency import race, reset_round

AGENT8 = Principal("agent-8", "user-123")
ROUNDS = 10


def _agent8(kit):
    kit.sql("INSERT INTO people (login, person_id, roles) VALUES ('agent-8', 'p-user123', ARRAY['agent']) "
            "ON CONFLICT (login) DO NOTHING")


def test_actor_rotation_second_spend_denied(kit):
    _agent8(kit)
    a, da = kit.json_request("INV-ROT1", "4900.00", idem="rot-1")
    assert kit.gate.commit(kit.gate.prepare(a, da).receipt, a).outcome == "EXECUTED"
    b, db = kit.json_request("INV-ROT2", "4900.00", idem="rot-2", actor="agent-8")
    p = kit.gate.prepare(b, db, principal=AGENT8)
    assert p.decision == "DENY" and p.receipt is None
    assert [(r.rule, r.guarantee, r.msg) for r in p.reasons] == [
        ("AP-CUM-03", "G1", "person+vendor cumulative total exceeds 5000.00")]
    assert len(kit.tool.calls) == 1


def test_actor_rotation_denied_at_commit(kit):
    """Both prepared while nothing was committed (each ALLOW); the commit tx is authoritative."""
    _agent8(kit)
    a, da = kit.json_request("INV-ROT3", "4900.00", idem="rot-3")
    b, db = kit.json_request("INV-ROT4", "4900.00", idem="rot-4", actor="agent-8")
    ra, rb = kit.gate.prepare(a, da), kit.gate.prepare(b, db, principal=AGENT8)
    assert ra.decision == rb.decision == "ALLOW"
    assert kit.gate.commit(ra.receipt, a).outcome == "EXECUTED"
    c = kit.gate.commit(rb.receipt, b, principal=AGENT8)
    assert [(r.rule, r.guarantee, r.msg) for r in c.reasons] == [
        ("AP-CUM-03", "G1", "person+vendor cumulative total exceeds 5000.00")]
    assert len(kit.tool.calls) == 1


def test_rotation_via_second_login_of_the_same_person(kit):
    """on_behalf_of differs (user-123 vs sub-user123) but both logins are p-user123: one person, one cap."""
    _agent8(kit)
    kit.sql("INSERT INTO delegations (on_behalf_of, max_amount, vendors) VALUES ('sub-user123', 5000.00, "
            "ARRAY['V-ACME']) ON CONFLICT (on_behalf_of) DO NOTHING")
    who = Principal("agent-8", "sub-user123")
    a, da = kit.json_request("INV-ROT5", "4900.00", idem="rot-5")
    b, db = kit.json_request("INV-ROT6", "4900.00", idem="rot-6", actor="agent-8", on_behalf_of="sub-user123")
    ra, rb = kit.gate.prepare(a, da), kit.gate.prepare(b, db, principal=who)
    assert kit.gate.commit(ra.receipt, a).outcome == "EXECUTED"
    assert rules(kit.gate.commit(rb.receipt, b, principal=who)) == ["AP-CUM-03"]
    assert len(kit.tool.calls) == 1


def test_other_person_not_capped(kit):
    """The per-person cap does not leak across people: user-456 (unmapped, its own key) is not p-user123."""
    _agent8(kit)
    kit.sql("INSERT INTO delegations (on_behalf_of, max_amount, vendors) VALUES ('user-456', 5000.00, "
            "ARRAY['V-ACME']) ON CONFLICT (on_behalf_of) DO NOTHING")
    who = Principal("agent-8", "user-456")
    a, da = kit.json_request("INV-ROT7", "4900.00", idem="rot-7")
    b, db = kit.json_request("INV-ROT8", "4900.00", idem="rot-8", actor="agent-8", on_behalf_of="user-456")
    assert kit.gate.commit(kit.gate.prepare(a, da).receipt, a).outcome == "EXECUTED"
    assert kit.gate.commit(kit.gate.prepare(b, db, principal=who).receipt, b, principal=who).outcome == "EXECUTED"
    assert len(kit.tool.calls) == 2


def test_actor_rotation_concurrent_one_executes(kit):
    """agent-7 and agent-8 (same person) race two 4900.00 commits on one vendor: exactly one executes."""
    _agent8(kit)
    for n in range(ROUNDS):
        reset_round(kit)
        a, da = kit.json_request(f"INV-RC{n}A", "4900.00", idem=f"rc-{n}-a")
        b, db = kit.json_request(f"INV-RC{n}B", "4900.00", idem=f"rc-{n}-b", actor="agent-8")
        ra, rb = kit.gate.prepare(a, da), kit.gate.prepare(b, db, principal=AGENT8)
        assert ra.decision == rb.decision == "ALLOW", n
        out = race(lambda: kit.gate.commit(ra.receipt, a), lambda: kit.gate.commit(rb.receipt, b, principal=AGENT8))
        assert sorted(o.outcome for o in out) == ["DENY", "EXECUTED"], (n, [(o.outcome, rules(o)) for o in out])
        denied = next(o for o in out if o.outcome == "DENY")
        assert rules(denied) in (["AP-CUM-03"], ["AP-ERR-11"]), (n, denied.reasons)
        assert len(kit.tool.calls) == 1 and kit.executes == 1, n
        assert kit.sql("SELECT SUM(amount)::text FROM commits") == [("4900.00",)], n
