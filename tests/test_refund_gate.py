"""Refund connector end to end through the SAME Gate.prepare/commit (ADR-009). Real OPA + Postgres + OCR."""
import pytest
from gatekit import json_claim, json_doc, rules  # also puts fixtures/ on sys.path

import hero  # noqa: E402
from actionproof import audit
from actionproof.gate import ReviewRefused

G1_VER = ("AP-VER-01", "G1")


@pytest.fixture
def rk(kit):
    kit.seed_refunds()
    return kit


def pairs(res):
    return [(r.rule, r.guarantee) for r in res.reasons]


def _allow(kit, doc="refund/REF-512.pdf", idem="idem-ref", **kw):
    req, docs = kit.refund(doc, idem, **kw)
    p = kit.gate.prepare(req, docs)
    assert p.decision == "ALLOW", p.reasons
    return req, p


def test_happy_path_executes_exactly_once(rk):
    req, p = _allow(rk)
    assert p.diff == {"record_id": "payment:PAY-8102", "status": "captured->captured", "amount": "120.00",
                      "refund_to": "pm_card_1881"}
    c = rk.gate.commit(p.receipt, req)
    assert c.outcome == "EXECUTED" and c.reasons == []
    assert c.tool_result["amount"] == "120.00" and c.tool_result["refund_to"] == "pm_card_1881"
    assert len(rk.refunds.calls) == 1 and rk.refund_executes == 1
    assert rk.tool.calls == [] and rk.executes == 0  # the invoice tool was never touched
    assert rk.version("payment:PAY-8102") == 2
    row = rk.sql("SELECT actor, vendor_id, amount::text, record_id FROM commits")
    assert row == [("agent-7", "CUST-512", "120.00", "payment:PAY-8102")]  # counterparty = SoR customer (ADR-015)
    assert rk.sql("SELECT data->>'refunded' FROM records WHERE record_id = 'payment:PAY-8102'") == [("120.00",)]


def test_replay_denied(rk):
    req, p = _allow(rk)
    assert rk.gate.commit(p.receipt, req).outcome == "EXECUTED"
    c = rk.gate.commit(p.receipt, req)
    assert pairs(c) == [("AP-REP-05", "G2")] and len(rk.refunds.calls) == 1


def test_amount_over_remaining_denied_at_prepare(rk):
    """250.00 refunded already; another 250.00 on a 450.00 payment exceeds its refundable 200.00."""
    req, p = _allow(rk, "refund/REF-311-clean.pdf", "ref-1")
    assert rk.gate.commit(p.receipt, req).outcome == "EXECUTED"
    req2, docs = rk.refund("refund/REF-311-clean.pdf", "ref-2")
    p2 = rk.gate.prepare(req2, docs)
    assert p2.decision == "DENY" and p2.receipt is None
    assert G1_VER in pairs(p2) and any("refundable balance" in r.msg for r in p2.reasons)
    assert len(rk.refunds.calls) == 1


def test_amount_over_remaining_denied_inside_the_commit_tx(rk):
    """A refund on the same payment committed after prepare (another actor, so no cap or version effect):
    the commit re-reads committed refunds under the commit lock and refuses."""
    req, p = _allow(rk, "refund/REF-311-clean.pdf", "ref-1")
    rk.prior_refunds("CUST-311", ["300.00"], actor="agent-9")
    rk.sql("UPDATE commits SET record_id = 'payment:PAY-7731' WHERE actor = 'agent-9'")
    c = rk.gate.commit(p.receipt, req)
    assert c.outcome == "DENY" and G1_VER in pairs(c), c.reasons
    assert any("refundable balance" in r.msg for r in c.reasons)
    assert rk.refunds.calls == [] and rk.refund_executes == 0
    assert rk.sql("SELECT count(*) FROM commits WHERE actor = 'agent-7'") == [(0,)]


def test_full_refund_up_to_the_payment_amount_allowed(rk):
    rk.seed_payment("PAY-9300", "CUST-512", "120.00", "pm_card_1881")
    req, docs = rk.refund_json("PAY-9300", "120.00", "CUST-512", "pm_card_1881", idem="full")
    p = rk.gate.prepare(req, docs)
    assert p.decision == "ALLOW", p.reasons
    req, docs = rk.refund_json("PAY-9300", "120.01", "CUST-512", "pm_card_1881", idem="over")
    assert G1_VER in pairs(rk.gate.prepare(req, docs))


@pytest.mark.parametrize("claim", [{"value": "CUST-999", "claim": "ASSERTED"},
                                   {"value": "CUST-512", "claim": "ASSERTED"}])
def test_customer_id_mismatch_denied(rk, claim):
    req, docs = rk.refund("refund/REF-311-clean.pdf", "ref-cust", customer_id=claim)
    p = rk.gate.prepare(req, docs)
    assert p.decision == "DENY" and G1_VER in pairs(p) and p.receipt is None
    assert any(r.msg.startswith("customer_id:") for r in p.reasons)


def test_customer_id_direct_from_a_document_must_still_match_the_record(rk):
    """A self-made export can say any customer; the payment record decides (gate check, not only verify)."""
    rk.seed_payment("PAY-9301", "CUST-311", "100.00", "pm_card_4242")
    req, docs = rk.refund_json("PAY-9301", "50.00", "CUST-311", "pm_card_4242", idem="dc")
    blob = json_doc(customer_id="CUST-512")
    d = req.model_dump(mode="json")
    d["args"]["customer_id"] = json_claim("cust.json", blob, "customer_id", "CUST-512")
    p = rk.gate.prepare(d, {**docs, "cust.json": blob})
    assert p.decision == "DENY" and any(r.msg.startswith("customer_id:") for r in p.reasons)


def test_unknown_payment_denied(rk):
    blob = json_doc(payment_id="PAY-0000", amount="10.00")
    req = {"tool": "payments.refund_payment", "on_behalf_of": "user-123", "actor": "agent-7", "idempotency_key": "u",
           "args": {"payment_id": json_claim("x.json", blob, "payment_id", "PAY-0000"),
                    "customer_id": {"value": "CUST-311", "claim": "ASSERTED"},
                    "refund_to": {"value": "pm_card_4242", "claim": "ASSERTED"},
                    "amount": json_claim("x.json", blob, "amount", "10.00")}}
    p = rk.gate.prepare(req, {"x.json": blob})
    assert pairs(p) == [G1_VER] and "not in the system of record" in p.reasons[0].msg


def test_refund_customer_out_of_scope_denied(rk):
    rk.sql("UPDATE delegations SET customers = ARRAY['CUST-311'] WHERE on_behalf_of = 'user-123'")
    req, docs = rk.refund("refund/REF-512.pdf", "scope")
    p = rk.gate.prepare(req, docs)
    assert pairs(p) == [("AP-SCOPE-02", "G1")] and p.reasons[0].msg == "customer not in on_behalf_of scope"


def test_review_above_1000_needs_a_token_from_a_different_person(rk):
    """1200.00 > 1000.00 -> REVIEW AP-REF-13 (G1); no token -> AP-REV-10; the submitter's own reviewer login ->
    AP-SEP-12 (unchanged); a different person -> executes once."""
    req, docs = rk.refund("refund/REF-420.pdf", "ref-big")
    p = rk.gate.prepare(req, docs)
    assert p.decision == "REVIEW" and pairs(p) == [("AP-REF-13", "G1")]
    assert p.reasons[0].msg == "refund amount exceeds 1000.00"
    assert pairs(rk.gate.commit(p.receipt, req)) == [("AP-REV-10", "G2")]
    rk.sql("INSERT INTO people (login, person_id, roles) VALUES ('rev-user123', 'p-user123', ARRAY['reviewer'])")
    with pytest.raises(ReviewRefused) as e:
        rk.mint(p.receipt, req, "rev-user123")
    assert (e.value.reason.rule, e.value.reason.guarantee) == ("AP-SEP-12", "G2")
    token = rk.mint(p.receipt, req, "rev-alice")
    c = rk.gate.commit(p.receipt, req, review_token=token)
    assert c.outcome == "EXECUTED" and len(rk.refunds.calls) == 1
    assert rules(rk.gate.commit(p.receipt, req, review_token=token)) == ["AP-REP-05"]


def test_refund_at_1000_is_allow(rk):
    rk.seed_payment("PAY-9302", "CUST-420", "1000.00", "pm_card_5555")
    req, docs = rk.refund_json("PAY-9302", "1000.00", "CUST-420", "pm_card_5555", idem="k1000")
    assert rk.gate.prepare(req, docs).decision == "ALLOW"
    rk.seed_payment("PAY-9302", "CUST-420", "1000.01", "pm_card_5555")
    req, docs = rk.refund_json("PAY-9302", "1000.01", "CUST-420", "pm_card_5555", idem="k1000c")
    assert pairs(rk.gate.prepare(req, docs)) == [("AP-REF-13", "G1")]


def test_audit_entries_for_refund_beats(rk):
    inj, docs = rk.refund("refund/REF-311.pdf", "ref-inj", refund_to=hero.injected_refund_to())
    assert rk.gate.prepare(inj, docs).decision == "DENY"
    req, p = _allow(rk, "refund/REF-311-clean.pdf", "ref-ok")
    assert rk.gate.commit(p.receipt, req).outcome == "EXECUTED"
    rows = rk.sql("SELECT kind, decision, actor, record_id, rules FROM audit_log ORDER BY seq")
    assert [(k, d, a, r) for k, d, a, r, _ in rows] == [
        ("prepare", "DENY", "agent-7", "payment:PAY-7731"),
        ("prepare", "ALLOW", "agent-7", "payment:PAY-7731"),
        ("commit", "EXECUTED", "agent-7", "payment:PAY-7731"),
    ]
    assert any(x["rule"] == "AP-VER-01" and "refund_to" in x["msg"] for x in rows[0][4])
    assert audit.verify(rk.db, rk.signer.public_key_b64())[0] == 3


def test_burned_refund_quarantines_the_payment(rk):
    """Same hostile switch as the invoice tool: effect then failure = unknown outcome -> burn + quarantine."""
    req, p = _allow(rk)
    rk.refunds.fail_after_effect = True
    c = rk.gate.commit(p.receipt, req)
    assert c.outcome == "DENY" and "AP-ERR-11" in rules(c) and len(rk.refunds.calls) == 1
    rk.refunds.fail_after_effect = False
    assert rk.sql("SELECT record_id FROM quarantine") == [("payment:PAY-8102",)]
    req2, docs = rk.refund("refund/REF-512.pdf", "idem-ref-2")
    assert pairs(rk.gate.prepare(req2, docs)) == [("AP-REP-05", "G2")]


def test_tool_double_call_detected(rk):
    req, p = _allow(rk)
    rk.refunds.double_call = True
    c = rk.gate.commit(p.receipt, req)
    assert c.outcome == "DENY" and rules(c)[0] == "AP-STALE-07"
    assert rk.version("payment:PAY-8102") == 1  # rolled back


def test_invoice_hero_unchanged_on_the_same_gate(rk):
    req, docs = rk.hero()
    p = rk.gate.prepare(req, docs)
    assert p.decision == "REVIEW" and rules(p) == ["AP-INV-04"]


def test_refund_card_names_the_destination(rk):
    inj, docs = rk.refund("refund/REF-311.pdf", "card", refund_to=hero.injected_refund_to())
    card = rk.gate.prepare(inj, docs).card()
    assert "action: refund_payment" in card and "refund_to: pm_attacker_9999 [ASSERTED]" in card
    assert "decision: DENY" in card
