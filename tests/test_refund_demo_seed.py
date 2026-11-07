"""scripts/demo_seed.py --reset (ADR-009): one command resets the whole demo, then the refund beats land in order:
injected REF-311 -> DENY AP-VER-01 (taint on refund_to); clean 250.00 retry -> DENY AP-CUM-03 (4800 + 250 > 5000);
a small clean refund under the cap -> executes exactly once. The invoice hero is reseeded by the same command."""
import importlib.util
from pathlib import Path

import pytest
from gatekit import rules

import hero  # noqa: E402  (fixtures/ is on sys.path via gatekit)

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("demo_seed", ROOT / "scripts" / "demo_seed.py")
demo_seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo_seed)


@pytest.fixture
def demo(kit):
    kit.sql("INSERT INTO commits (nonce, idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount, "
            "record_id, created_at) VALUES ('junk', 'junk', 'h', 'agent-7', 'user-123', 'CUST-311', 4999.00, 'x', 1)")
    assert demo_seed.main(["--reset"]) == 0  # DATABASE_URL points at this session's private test database
    return kit


def test_reset_seeds_the_refund_and_invoice_state(demo):
    assert demo.sql("SELECT nonce FROM commits WHERE nonce = 'junk'") == []
    assert demo.sql("SELECT SUM(amount)::text FROM commits WHERE actor = 'agent-7' AND vendor_id = 'CUST-311'") \
        == [("4800.00",)]
    assert demo.sql("SELECT data, version FROM records WHERE record_id = 'payment:PAY-7731'") == [(
        {"customer_id": "CUST-311", "amount": "450.00", "method_id": "pm_card_4242", "status": "captured"}, 1)]
    assert demo.sql("SELECT data->>'status', version FROM records WHERE record_id = 'invoice:INV-2048'") \
        == [("open", 1)]
    assert demo.sql("SELECT count(*) FROM people WHERE login IN ('rev-alice', 'rev-bob', 'agent-7')") == [(3,)]
    assert demo.sql("SELECT count(*) FROM review_tokens") == [(0,)] and demo.sql("SELECT count(*) FROM quarantine") \
        == [(0,)]


def test_refund_beats_in_order(demo):
    inj, docs = demo.refund(hero.REFUND_INJECTED, "demo-inj", refund_to=hero.injected_refund_to())
    p = demo.gate.prepare(inj, docs)
    assert p.decision == "DENY" and p.receipt is None
    assert any(r.rule == "AP-VER-01" and r.guarantee == "G1" and r.msg.startswith("refund_to:") for r in p.reasons)

    clean, docs = demo.refund(hero.REFUND_CLEAN, "demo-clean")
    p = demo.gate.prepare(clean, docs)
    assert p.decision == "DENY" and [(r.rule, r.guarantee) for r in p.reasons] == [("AP-CUM-03", "G1")]

    small, docs = demo.refund(hero.REFUND_SMALL, "demo-small")
    p = demo.gate.prepare(small, docs)
    assert p.decision == "ALLOW", p.reasons
    assert demo.gate.commit(p.receipt, small).outcome == "EXECUTED"
    assert rules(demo.gate.commit(p.receipt, small)) == ["AP-REP-05"]
    assert len(demo.refunds.calls) == 1 and demo.refund_executes == 1


def test_reset_is_idempotent_and_restores_the_beats(demo):
    small, docs = demo.refund(hero.REFUND_SMALL, "demo-small")
    p = demo.gate.prepare(small, docs)
    assert demo.gate.commit(p.receipt, small).outcome == "EXECUTED"
    assert demo_seed.main(["--reset"]) == 0
    assert demo_seed.main(["--reset"]) == 0
    assert demo.version("payment:PAY-7731") == 1
    p = demo.gate.prepare(small, docs)  # same idempotency key works again after a reset
    assert p.decision == "ALLOW"
    hero_req, hero_docs = demo.hero()
    assert rules(demo.gate.prepare(hero_req, hero_docs)) == ["AP-INV-04"]


def test_seed_without_reset_keeps_existing_commits(demo):
    demo.prior_refunds("CUST-512", ["10.00"])
    assert demo_seed.main([]) == 0
    assert demo.sql("SELECT count(*) FROM commits WHERE vendor_id = 'CUST-512'") == [(1,)]
    assert demo.sql("SELECT SUM(amount)::text FROM commits WHERE vendor_id = 'CUST-311'") == [("4800.00",)]
