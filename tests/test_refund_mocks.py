"""Mock refund tool (ADR-009): payment records in `records` (kind 'payment'), same hostile switches as MockPayments."""
import pytest

from actionproof import db as dbmod
from actionproof.contracts import ActionRequest
from actionproof.mocks import MockERP, MockRefunds, ToolError


def _req(amount: str = "250.00", payment_id: str = "PAY-7731", refund_to: str = "pm_card_4242") -> ActionRequest:
    return ActionRequest.model_validate({
        "tool": "payments.refund_payment", "on_behalf_of": "user-123", "actor": "agent-7", "idempotency_key": "ik-1",
        "args": {"amount": {"value": amount, "claim": "ASSERTED"},
                 "payment_id": {"value": payment_id, "claim": "ASSERTED"},
                 "refund_to": {"value": refund_to, "claim": "ASSERTED"}},
    })


@pytest.fixture
def refunds(pg, db):
    dbmod.seed_refunds(db)
    factory = lambda: dbmod.connect(url=pg)  # noqa: E731
    return MockRefunds(MockERP(factory), factory)


def _row(db):
    return db.execute("SELECT data->>'refunded', version FROM records WHERE record_id = 'payment:PAY-7731'").fetchone()


def test_seeded_payment_record(refunds):
    data, version = refunds.read_record("payment:PAY-7731")
    assert data == {"customer_id": "CUST-311", "amount": "450.00", "method_id": "pm_card_4242", "status": "captured"}
    assert version == 1


def test_sor_for_payment(refunds):
    assert refunds.sor_for("PAY-7731") == {"customer_id": "CUST-311", "refund_to": "pm_card_4242",
                                           "payment.amount": "450.00"}
    with pytest.raises(KeyError):
        refunds.sor_for("PAY-0000")


def test_dry_run(refunds):
    assert refunds.dry_run(_req()) == {"record_id": "payment:PAY-7731", "status": "captured->captured",
                                       "amount": "250.00", "refund_to": "pm_card_4242"}


def test_execute_applies_once(refunds, db):
    result = refunds.execute(_req(), 1, "k1", db)
    assert _row(db) == ("250.00", 2)
    assert result == {"record_id": "payment:PAY-7731", "status": "captured", "amount": "250.00",
                      "refund_to": "pm_card_4242", "refunded": "250.00", "version": 2}
    assert [(c["idempotency_key"], c["amount"], c["refund_to"]) for c in refunds.calls] == [("k1", "250.00", "pm_card_4242")]


def test_idempotency_key_dedupes(refunds, db):
    first = refunds.execute(_req(), 1, "k1", db)
    assert refunds.execute(_req(), 2, "k1", db) == first and len(refunds.calls) == 1 and _row(db) == ("250.00", 2)


def test_ignore_idempotency_applies_twice(refunds, db):
    refunds.ignore_idempotency = True
    refunds.execute(_req("100.00"), 1, "k1", db)
    refunds.execute(_req("100.00"), 2, "k1", db)
    assert len(refunds.calls) == 2 and _row(db) == ("200.00", 3)


def test_wrong_version_raises(refunds, db):
    with pytest.raises(ToolError):
        refunds.execute(_req(), 7, "k1", db)
    assert refunds.calls == [] and _row(db) == (None, 1)


def test_ignore_version(refunds, db):
    refunds.ignore_version = True
    refunds.execute(_req(), 7, "k1", db)
    assert _row(db) == ("250.00", 2)


def test_double_call(refunds, db):
    refunds.double_call = True
    refunds.execute(_req("100.00"), 1, "k1", db)
    assert len(refunds.calls) == 2 and _row(db) == ("200.00", 3)


def test_fail_after_effect(refunds, db):
    refunds.fail_after_effect = True
    with pytest.raises(ToolError):
        refunds.execute(_req(), 1, "k1", db)
    assert len(refunds.calls) == 1


def test_mutate_before_execute(refunds, db):
    refunds._erp.mutate_before_execute = lambda conn, rid: conn.execute(
        "UPDATE records SET version = version + 1 WHERE record_id = %s", (rid,))
    with pytest.raises(ToolError):
        refunds.execute(_req(), 1, "k1", db)
    assert refunds.calls == []
