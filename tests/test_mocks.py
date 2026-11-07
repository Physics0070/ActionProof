"""Adversarial mock services (Phase 3, task 3): ERP reader, payments adapter, vendor master.

Real Postgres via the `pg` / `db` fixtures; each mock gets a fresh connection from the factory.
"""
import pytest

from actionproof import db as dbmod
from actionproof.contracts import ActionRequest
from actionproof.mocks import MockERP, MockPayments, MockVendorMaster, ToolError


def _req(amount: str = "4800.00", invoice_id: str = "INV-2048") -> ActionRequest:
    return ActionRequest.model_validate({
        "tool": "payments.approve_invoice",
        "on_behalf_of": "user-123",
        "actor": "agent-7",
        "idempotency_key": "ik-1",
        "args": {
            "amount": {"value": amount, "claim": "ASSERTED"},
            "invoice_id": {"value": invoice_id, "claim": "ASSERTED"},
        },
    })


@pytest.fixture
def factory(pg):
    return lambda: dbmod.connect(url=pg)


@pytest.fixture
def erp(factory):
    return MockERP(factory)


@pytest.fixture
def payments(erp, factory):
    return MockPayments(erp, factory)


def _row(db, record_id: str):
    return db.execute("SELECT data->>'status', version FROM records WHERE record_id = %s", (record_id,)).fetchone()


# --- ERP reader ---------------------------------------------------------------

def test_read_record_returns_data_and_version(erp, db):
    data, version = erp.read_record("invoice:INV-2048")
    assert data == {"vendor_id": "V-ACME", "total": "4800.00", "status": "open"}
    assert version == 1


def test_stale_read_lies(erp, db):
    db.execute("UPDATE records SET version = 3, data = data || '{\"status\": \"approved\"}'::jsonb "
               "WHERE record_id = 'invoice:INV-2048'")
    db.commit()
    assert erp.read_record("invoice:INV-2048")[1] == 3
    erp.stale_read = True
    data, version = erp.read_record("invoice:INV-2048")
    assert version == 2
    assert data["status"] == "open"


def test_sor_for_returns_po_total_and_vendor(erp, db):
    db.execute("UPDATE records SET data = data || '{\"po_id\": \"PO-2048\"}'::jsonb "
               "WHERE record_id = 'invoice:INV-2048'")
    db.commit()
    assert erp.sor_for("INV-2048") == {"po.total": "4300.00", "vendor_id": "V-ACME"}


# --- payments adapter ---------------------------------------------------------

def test_read_record_delegates_to_erp(payments, db):
    assert payments.read_record("invoice:INV-2048") == ({"vendor_id": "V-ACME", "total": "4800.00", "status": "open"}, 1)


def test_dry_run_content(payments):
    assert payments.dry_run(_req()) == {
        "record_id": "invoice:INV-2048",
        "status": "open->approved",
        "amount": "4800.00",
    }


def test_dry_run_missing_claim_raises(payments):
    req = ActionRequest.model_validate({
        "tool": "payments.approve_invoice", "on_behalf_of": "user-123", "actor": "agent-7",
        "idempotency_key": "ik-1", "args": {"invoice_id": {"value": "INV-2048", "claim": "ASSERTED"}},
    })
    with pytest.raises(ValueError):
        payments.dry_run(req)


def test_execute_applies_and_records_exactly_one_call(payments, db):
    result = payments.execute(_req(), 1, "k1", db)
    assert _row(db, "invoice:INV-2048") == ("approved", 2)
    assert result["version"] == 2
    assert len(payments.calls) == 1
    call = payments.calls[0]
    assert call["idempotency_key"] == "k1"
    assert call["record_id"] == "invoice:INV-2048"
    assert call["amount"] == "4800.00"


def test_wrong_expected_version_raises_and_records_nothing(payments, db):
    with pytest.raises(ToolError):
        payments.execute(_req(), 7, "k1", db)
    assert payments.calls == []
    assert _row(db, "invoice:INV-2048") == ("open", 1)


def test_repeated_idempotency_key_is_deduped(payments, db):
    first = payments.execute(_req(), 1, "k1", db)
    second = payments.execute(_req(), 2, "k1", db)
    assert second == first
    assert len(payments.calls) == 1
    assert _row(db, "invoice:INV-2048") == ("approved", 2)


def test_ignore_idempotency_double_records(payments, db):
    payments.ignore_idempotency = True
    payments.execute(_req(), 1, "k1", db)
    payments.execute(_req(), 2, "k1", db)
    assert len(payments.calls) == 2
    assert _row(db, "invoice:INV-2048") == ("approved", 3)


def test_double_call_records_two(payments, db):
    payments.double_call = True
    payments.execute(_req(), 1, "k1", db)
    assert len(payments.calls) == 2


def test_fail_after_effect_records_one_and_raises(payments, db):
    payments.fail_after_effect = True
    with pytest.raises(ToolError):
        payments.execute(_req(), 1, "k1", db)
    assert len(payments.calls) == 1


def test_ignore_version_applies_on_mismatch(payments, db):
    payments.ignore_version = True
    payments.execute(_req(), 7, "k1", db)
    assert len(payments.calls) == 1
    assert _row(db, "invoice:INV-2048") == ("approved", 2)


def test_mutate_before_execute_bumps_version_and_well_behaved_execute_raises(payments, erp, db):
    def bump(conn, record_id):
        conn.execute("UPDATE records SET version = version + 1 WHERE record_id = %s", (record_id,))

    erp.mutate_before_execute = bump
    with pytest.raises(ToolError):
        payments.execute(_req(), 1, "k1", db)
    assert payments.calls == []


# --- vendor master ------------------------------------------------------------

def test_vendor_bank_roundtrip_and_change_bank_records(factory, db):
    vendors = MockVendorMaster(factory)
    assert vendors.bank_last4("V-ACME") is None
    vendors.set_bank("V-ACME", "1234")
    assert vendors.bank_last4("V-ACME") == "1234"
    assert vendors.calls == []
    vendors.change_bank("V-ACME", "9999")
    assert vendors.bank_last4("V-ACME") == "9999"
    assert len(vendors.calls) == 1
    assert vendors.calls[0]["vendor_id"] == "V-ACME"
    assert vendors.calls[0]["last4"] == "9999"
