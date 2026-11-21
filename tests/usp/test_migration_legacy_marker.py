"""USP G1+G2: migration of a database from before ADR-022 that holds an UNRESOLVED tool_reached marker.

The old marker has no amount, actor, counterparty or idempotency key. Its spend is unknown, so it must NOT count as
zero: every cap-sensitive write (prepare and commit, any actor) fails closed until a human reconciles it, and that
reconciliation is audited. Real Postgres; the pre-ADR-022 shape is restored by dropping what ADR-022 added, then the
real migration (db.apply_schema) runs.
"""
from decimal import Decimal

import pytest
from gatekit import rules

from actionproof import audit, db

NEW_COLS = ("idempotency_key", "request_hash", "actor", "on_behalf_of", "vendor_id", "amount")


def _to_pre_adr022(kit):
    """Put tool_reached back in its ADR-019 shape: nonce, record_id, created_at only; no view, no unique index."""
    kit.sql("DROP VIEW IF EXISTS reservations")
    kit.sql("DROP INDEX IF EXISTS tool_reached_idem")
    for c in NEW_COLS:
        kit.sql(f"ALTER TABLE tool_reached DROP COLUMN IF EXISTS {c}")


def _legacy_db(kit, record="invoice:INV-LEG"):
    _to_pre_adr022(kit)
    kit.sql("INSERT INTO tool_reached (nonce, record_id, created_at) VALUES ('legacy-n1', %s, 1)", (record,))
    db.apply_schema(kit.db)  # the real migration, as the API does at boot
    kit.db.commit()


def _cols(kit):
    return {r[0] for r in kit.sql("SELECT column_name FROM information_schema.columns WHERE table_name='tool_reached'")}


def test_migration_keeps_the_legacy_row_and_adds_the_reservation_shape(kit):
    _legacy_db(kit)
    assert set(NEW_COLS) <= _cols(kit)
    row = kit.sql("SELECT nonce, record_id, amount, actor, vendor_id, idempotency_key FROM tool_reached")[0]
    assert row == ("legacy-n1", "invoice:INV-LEG", None, None, None, None)  # kept, unknowns stay NULL (not 0)
    assert kit.sql("SELECT count(*) FROM pg_views WHERE viewname='reservations'")[0][0] == 1
    db.apply_schema(kit.db)  # idempotent: running the migration again changes nothing
    kit.db.commit()
    assert kit.sql("SELECT count(*) FROM tool_reached")[0][0] == 1


def test_legacy_marker_blocks_prepare_and_commit_for_everyone(kit):
    """An unrelated actor, record and amount: the unknown spend makes the cumulative caps unprovable (AP-CUM-03 G1)."""
    kit.set_scope("5000.00")
    req, docs = kit.json_request("INV-LEG2", "100.00")
    ok = kit.gate.prepare(req, docs)
    assert ok.decision == "ALLOW"  # prepared BEFORE the legacy row appears, so we can test the commit block too
    _legacy_db(kit)
    c = kit.gate.commit(ok.receipt, req)
    assert rules(c) == ["AP-CUM-03"] and c.outcome != "EXECUTED" and kit.executes == 0 and kit.commits() == 0
    req2, docs2 = kit.json_request("INV-LEG3", "50.00")
    r2 = kit.gate.prepare(req2, docs2)
    assert r2.decision == "DENY" and "AP-CUM-03" in rules(r2)
    assert "unknown" in " ".join(x.msg for x in r2.reasons).lower()


def test_unknown_amount_is_not_counted_as_zero_in_the_reservation_view(kit):
    _legacy_db(kit)
    assert kit.sql("SELECT COALESCE(SUM(amount), 0) FROM reservations")[0][0] == Decimal("0")  # excluded, not guessed
    # ...which is exactly why the gate must not rely on the view alone: it refuses instead (test above).


def test_release_without_a_reservation_for_an_executed_legacy_marker_is_refused(kit):
    _legacy_db(kit)
    with pytest.raises(ValueError):
        kit.gate.release_quarantine("invoice:INV-LEG", "rev-alice", executed=True)            # no amount known
    with pytest.raises(ValueError):
        kit.gate.release_quarantine("invoice:INV-LEG", "rev-alice", executed=True,
                                    reservation={"amount": "100.00"})                         # incomplete
    with pytest.raises(ValueError):
        kit.gate.release_quarantine("invoice:INV-LEG", "rev-alice", executed=True, reservation={
            "idempotency_key": "k", "request_hash": "h", "actor": "agent-7", "on_behalf_of": "user-123",
            "vendor_id": "V-ACME", "amount": "49.999"})                                       # not 2dp
    with pytest.raises(ValueError):
        kit.gate.release_quarantine("invoice:INV-LEG", "rev-alice", executed=False, reservation={
            "idempotency_key": "k", "request_hash": "h", "actor": "a", "on_behalf_of": "o", "vendor_id": "v",
            "amount": "1.00"})                                                                # only for executed
    assert kit.sql("SELECT count(*) FROM tool_reached")[0][0] == 1                            # nothing changed
    assert kit.sql("SELECT count(*) FROM audit_log WHERE kind = 'release_quarantine'")[0][0] == 0


def test_attesting_it_did_not_execute_is_audited_and_resumes_writes(kit):
    _legacy_db(kit)
    assert kit.gate.release_quarantine("invoice:INV-LEG", "rev-alice") is True
    assert kit.sql("SELECT count(*) FROM tool_reached")[0][0] == 0
    kit.set_scope("5000.00")
    req, docs = kit.json_request("INV-LEG4", "100.00")
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW" and kit.gate.commit(r.receipt, req).outcome == "EXECUTED"
    rel = kit.sql("SELECT decision, detail FROM audit_log WHERE kind = 'release_quarantine'")[0]
    assert rel[0] == "RELEASED" and rel[1]["executed"] is False
    assert rel[1]["unresolved"] == [{"nonce": "legacy-n1", "amount": None}]
    with kit.factory() as conn:
        assert audit.verify(conn, kit.signer.public_key_b64())[0] > 0


def test_confirming_it_executed_requires_the_reservation_and_then_counts_it(kit):
    _legacy_db(kit)
    res = {"idempotency_key": "legacy-idem", "request_hash": "ab" * 32, "actor": "agent-7",
           "on_behalf_of": "user-123", "vendor_id": "V-ACME", "amount": "4900.00"}
    assert kit.gate.release_quarantine("invoice:INV-LEG", "rev-alice", executed=True, reservation=res) is True
    assert kit.sql("SELECT amount, actor, vendor_id, idempotency_key FROM commits WHERE nonce = 'legacy-n1'") == [
        (Decimal("4900.00"), "agent-7", "V-ACME", "legacy-idem")]
    kit.set_scope("5000.00")
    req, docs = kit.json_request("INV-LEG5", "250.00")
    r = kit.gate.prepare(req, docs)
    if r.decision == "DENY":
        assert "AP-CUM-03" in rules(r)
    else:
        assert rules(kit.gate.commit(r.receipt, req)) == ["AP-CUM-03"]  # 4900 + 250 > 5000: the human's figure counts
    rel = kit.sql("SELECT detail FROM audit_log WHERE kind = 'release_quarantine'")[0][0]
    assert rel["executed"] is True and rel["unresolved"] == [{"nonce": "legacy-n1", "amount": None}]
    assert rel["reservation_supplied"] == {**res, "amount": "4900.00"}


def test_a_marker_with_any_null_reservation_field_is_legacy(kit):
    """Partially filled rows (e.g. amount set, actor missing) are also unprovable and also block."""
    kit.sql("INSERT INTO tool_reached (nonce, record_id, created_at, idempotency_key, request_hash, on_behalf_of, "
            "vendor_id, amount) VALUES ('partial', 'invoice:INV-P', 1, 'kp', 'h', 'user-123', 'V-ACME', 10.00)")
    kit.set_scope("5000.00")
    req, docs = kit.json_request("INV-LEG6", "100.00")
    assert rules(kit.gate.prepare(req, docs)) == ["AP-CUM-03"]
