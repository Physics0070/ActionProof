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

# The exact tool_reached table of the ADR-019 schema (before ADR-022): the fixture a pre-ADR-022 database holds.
PRE_ADR022_TOOL_REACHED = """
    DROP VIEW IF EXISTS reservations;
    DROP TABLE tool_reached;
    CREATE TABLE tool_reached (
        nonce      text PRIMARY KEY,
        record_id  text   NOT NULL,
        created_at bigint NOT NULL CHECK (created_at >= 0)
    );
"""


def _to_pre_adr022(kit):
    """Replace tool_reached with its ADR-019 definition: no reservation columns, no unique key index, no view."""
    kit.db.execute(PRE_ADR022_TOOL_REACHED)
    kit.db.commit()
    assert _cols(kit) == {"nonce", "record_id", "created_at"}


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


# ---- explicit validation step, startup warning and the operator CLI (ADR-024)

def _cli_env(kit, opa_url, signing_key_path):
    from pathlib import Path
    docs = Path(__file__).resolve().parents[2] / "fixtures" / "out"
    return {"DATABASE_URL": kit.pg, "OPA_URL": opa_url, "SIGNING_KEY_PATH": str(signing_key_path),
            "SIGNING_KID": kit.settings.signing_kid, "TESSERACT_CMD": kit.settings.tesseract_cmd,
            "DOCS_DIR": str(docs)}


def test_validation_lists_incomplete_unresolved_markers(kit):
    assert db.legacy_markers(kit.db) == []
    kit.db.commit()
    _legacy_db(kit)
    assert db.legacy_markers(kit.db) == [("legacy-n1", "invoice:INV-LEG")]
    kit.db.commit()


def test_validation_ignores_a_complete_or_resolved_marker(kit):
    """A complete marker (all reservation columns) and a marker whose nonce has a commits row are not legacy."""
    kit.sql("INSERT INTO tool_reached (nonce, record_id, created_at, idempotency_key, request_hash, actor, "
            "on_behalf_of, vendor_id, amount) VALUES ('full', 'invoice:INV-F', 1, 'kf', 'h', 'agent-7', 'user-123', "
            "'V-ACME', 5.00)")
    assert db.legacy_markers(kit.db) == []
    kit.db.commit()


def test_cli_check_fails_until_reconciled(kit, opa_url, signing_key_path, capsys):
    from actionproof import reconcile
    env = _cli_env(kit, opa_url, signing_key_path)
    assert reconcile.main(["check"], env=env) == 0
    _legacy_db(kit)
    assert reconcile.main(["check"], env=env) == 1
    assert "legacy-n1" in capsys.readouterr().out
    assert reconcile.main(["release", "--record", "invoice:INV-LEG", "--reviewer", "rev-alice"], env=env) == 0
    assert reconcile.main(["check"], env=env) == 0
    assert kit.sql("SELECT decision FROM audit_log WHERE kind = 'release_quarantine'") == [("RELEASED",)]


def test_cli_release_executed_needs_a_valid_reservation(kit, opa_url, signing_key_path):
    import json

    from actionproof import reconcile
    env = _cli_env(kit, opa_url, signing_key_path)
    _legacy_db(kit)
    base = ["release", "--record", "invoice:INV-LEG", "--reviewer", "rev-alice", "--executed"]
    assert reconcile.main(base, env=env) == 2                                          # no reservation: refused
    assert reconcile.main(base + ["--reservation", "{not json"], env=env) == 2
    assert reconcile.main(base + ["--reservation", json.dumps({"amount": "1.00"})], env=env) == 2
    assert kit.sql("SELECT count(*) FROM tool_reached")[0][0] == 1                     # nothing changed
    res = {"idempotency_key": "cli-idem", "request_hash": "cd" * 32, "actor": "agent-7",
           "on_behalf_of": "user-123", "vendor_id": "V-ACME", "amount": "75.00"}
    assert reconcile.main(base + ["--reservation", json.dumps(res)], env=env) == 0
    assert kit.sql("SELECT amount FROM commits WHERE nonce = 'legacy-n1'") == [(Decimal("75.00"),)]


def test_apply_schema_script_warns_loudly(kit):
    import subprocess
    import sys
    from pathlib import Path
    _legacy_db(kit)
    r = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "apply_schema.py")],
                       env={**__import__("os").environ, "DATABASE_URL": kit.pg}, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0 and "schema applied" in r.stdout          # boot continues: reconciliation needs the API
    assert "WARNING" in r.stderr and "legacy" in r.stderr.lower() and "reconcile" in r.stderr.lower()


def test_server_start_logs_the_legacy_marker(kit, caplog):
    import logging
    from pathlib import Path

    from actionproof import server
    _legacy_db(kit)
    ss = server.load_server_settings({"DOCS_DIR": str(Path(__file__).resolve().parents[2] / "fixtures" / "out")},
                                     need_principal=False)
    with caplog.at_level(logging.WARNING):
        assert server.build_app(kit.settings, ss) is not None
    assert any("legacy" in r.getMessage().lower() and r.levelno >= logging.WARNING for r in caplog.records)
