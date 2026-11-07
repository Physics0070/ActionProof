"""Attack (ADR-009): split refunds against the 5000.00 cap keyed (transport actor, SoR customer) -> AP-CUM-03 / G1.

Advisory at prepare, authoritative inside the SERIALIZABLE commit tx (ADR-006/010), exactly like invoices.
"""
from gatekit import rules

import hero  # noqa: E402  (fixtures/ is on sys.path via gatekit)
from actionproof.gate import Principal

from attacks._concurrency import race, reset_round

CUM = [("AP-CUM-03", "G1")]
ROUNDS = 10


def pairs(res):
    return [(r.rule, r.guarantee) for r in res.reasons]


def test_cap_denies_at_prepare(kit):
    """The demo numbers: 4800.00 already refunded to CUST-311 by agent-7, clean 250.00 request -> 5050.00."""
    kit.seed_refunds()
    kit.prior_refunds("CUST-311", ["1200.00"] * 4)
    req, docs = kit.refund(hero.REFUND_CLEAN, "cap")
    p = kit.gate.prepare(req, docs)
    assert p.decision == "DENY" and pairs(p) == CUM and p.receipt is None
    assert p.reasons[0].msg == "actor+customer cumulative total exceeds 5000.00"
    assert kit.refunds.calls == []


def test_cap_key_customer_comes_from_the_payment_record(kit):
    """The request names another customer; the cap still counts CUST-311 (the payment's customer)."""
    kit.seed_refunds()
    kit.prior_refunds("CUST-311", ["4800.00"])
    req, docs = kit.refund(hero.REFUND_CLEAN, "key", customer_id={"value": "CUST-512", "claim": "ASSERTED"})
    p = kit.gate.prepare(req, docs)
    assert p.decision == "DENY" and "AP-CUM-03" in rules(p)


def test_cap_is_per_actor_and_other_agents_do_not_count(kit):
    kit.seed_refunds()
    kit.prior_refunds("CUST-311", ["4800.00"], actor="agent-9")
    req, docs = kit.refund(hero.REFUND_CLEAN, "other")
    assert kit.gate.prepare(req, docs).decision == "ALLOW"


def test_cap_is_not_reset_by_another_principal(kit):
    kit.seed_refunds()
    kit.prior_refunds("CUST-311", ["4800.00"])
    kit.sql("INSERT INTO delegations (on_behalf_of, max_amount, vendors, customers) "
            "VALUES ('user-456', 5000.00, ARRAY[]::text[], ARRAY['CUST-311'])")
    d = hero.refund_request(hero.REFUND_CLEAN, "p456").model_dump(mode="json")
    d["on_behalf_of"] = "user-456"
    p = kit.gate.prepare(d, hero.load_docs(), principal=Principal("agent-7", "user-456"))
    assert pairs(p) == CUM


def _setup_round(kit):
    reset_round(kit)
    kit.refunds.calls.clear()
    kit.refund_executes = 0
    for pid in ("PAY-9201", "PAY-9202"):
        kit.seed_payment(pid, "CUST-777", "600.00", "pm_card_7777")
    kit.prior_refunds("CUST-777", ["4200.00"])


def _two(kit, n):
    out = []
    for pid in ("PAY-9201", "PAY-9202"):
        req, docs = kit.refund_json(pid, "500.00", "CUST-777", "pm_card_7777", idem=f"rc-{n}-{pid}")
        p = kit.gate.prepare(req, docs)
        assert p.decision == "ALLOW", p.reasons  # 4200 + 500 alone is under the cap
        out.append((req, p.receipt))
    return out


def test_concurrent_refunds_one_executes(kit):
    """Two threads, two payments of one customer, 4200 + 500 + 500 > 5000: exactly one executes."""
    for n in range(ROUNDS):
        _setup_round(kit)
        (a, ra), (b, rb) = _two(kit, n)
        results = race(lambda: kit.gate.commit(ra, a), lambda: kit.gate.commit(rb, b))
        assert sorted(r.outcome for r in results) == ["DENY", "EXECUTED"], (n, [rules(r) for r in results])
        denied = next(r for r in results if r.outcome == "DENY")
        if rules(denied) == ["AP-ERR-11"]:  # serialization failure after retries: retry once, sequentially
            loser = (b, rb) if results[1] is denied else (a, ra)
            denied = kit.gate.commit(loser[1], loser[0])
        assert pairs(denied) == CUM, n
        assert len(kit.refunds.calls) == 1 and kit.refund_executes == 1, n
        assert kit.sql("SELECT SUM(amount)::text FROM commits WHERE vendor_id = 'CUST-777'") == [("4700.00",)], n


def test_sequential_refunds_capped_at_commit(kit):
    _setup_round(kit)
    (a, ra), (b, rb) = _two(kit, 99)
    assert kit.gate.commit(ra, a).outcome == "EXECUTED"
    c = kit.gate.commit(rb, b)
    assert pairs(c) == CUM and c.reasons[0].msg == "actor+customer cumulative total exceeds 5000.00"
    assert len(kit.refunds.calls) == 1
