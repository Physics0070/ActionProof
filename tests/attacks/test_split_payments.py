"""Attack S6.5 split payments: two $4,900 approvals against a $5,000 actor+vendor cap -> AP-CUM-03 / G1.

Prepare-time AP-CUM-03 is advisory; the commit-time re-check inside the SERIALIZABLE tx is authoritative (ADR-006).
"""
from gatekit import rules

from actionproof.gate import Principal

from attacks._concurrency import race, reset_round

ROUNDS = 20


def _two_receipts(kit, n):
    out = []
    for i in (1, 2):
        req, docs = kit.json_request(f"INV-49{n:02d}{i}", "4900.00", idem=f"split-{n}-{i}")
        r = kit.gate.prepare(req, docs)
        assert r.decision == "ALLOW", r.reasons  # each alone is in scope and under the cap
        out.append((req, r.receipt))
    return out


def test_concurrent_split_payments(kit):
    """Two threads, own connections, distinct receipts/keys/nonces, same actor+vendor: exactly one executes."""
    for n in range(ROUNDS):
        reset_round(kit)
        (a, ra), (b, rb) = _two_receipts(kit, n)
        results = race(lambda: kit.gate.commit(ra, a), lambda: kit.gate.commit(rb, b))
        outcomes = sorted(r.outcome for r in results)
        assert outcomes == ["DENY", "EXECUTED"], (n, [(r.outcome, rules(r)) for r in results])
        denied = next(r for r in results if r.outcome == "DENY")
        if rules(denied) == ["AP-ERR-11"]:  # serialization failure after retries: retry once, sequentially
            loser = (b, rb) if results[1] is denied else (a, ra)
            denied = kit.gate.commit(loser[1], loser[0])
        assert [(x.rule, x.guarantee) for x in denied.reasons] == [("AP-CUM-03", "G1")], n
        assert len(kit.tool.calls) == 1 and kit.executes == 1, n
        assert kit.sql("SELECT SUM(amount)::text FROM commits") == [("4900.00",)], n


def test_sequential_split_payments(kit):
    """4900 then 4900: the second is AP-CUM-03 at commit (prepared earlier) AND at prepare (prepared later)."""
    (a, ra), (b, rb) = _two_receipts(kit, 99)
    assert kit.gate.commit(ra, a).outcome == "EXECUTED"
    c = kit.gate.commit(rb, b)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-CUM-03", "G1")]
    req, docs = kit.json_request("INV-49993", "4900.00", idem="split-late")
    p = kit.gate.prepare(req, docs)
    assert p.decision == "DENY" and rules(p) == ["AP-CUM-03"] and p.receipt is None
    assert len(kit.tool.calls) == 1


def test_split_across_principals_still_capped(kit):
    """The cap is per actor+vendor: changing on_behalf_of does not reset it."""
    kit.sql("INSERT INTO delegations (on_behalf_of, max_amount, vendors) VALUES ('user-456', 5000.00, ARRAY['V-ACME'])")
    a, da = kit.json_request("INV-49801", "4900.00", idem="p-1")
    b, db = kit.json_request("INV-49802", "4900.00", idem="p-2", on_behalf_of="user-456")
    for_456 = Principal("agent-7", "user-456")  # same agent, a session on behalf of user-456
    ra, rb = kit.gate.prepare(a, da).receipt, kit.gate.prepare(b, db, principal=for_456).receipt
    assert kit.gate.commit(ra, a).outcome == "EXECUTED"
    assert rules(kit.gate.commit(rb, b, principal=for_456)) == ["AP-CUM-03"]
    assert len(kit.tool.calls) == 1
