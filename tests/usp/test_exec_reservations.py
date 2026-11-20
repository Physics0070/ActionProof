"""USP G1+G2: an execution whose outcome is unknown KEEPS its reservation (amount, idempotency key, counterparty,
actor, person) until an authorized reconciliation, so a crash after a successful external action cannot widen the
cumulative caps or free the request idempotency key. Real Postgres; the crash is a BaseException, or a real killed
process with a file-backed downstream (test_real_process_kill_*).
"""
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from _crash_child import FilePSP
from gatekit import INVOICE_TOOL, rules
from test_exec_faults import ExternalPSP, ProcessCrash

from actionproof import audit

ROOT = Path(__file__).resolve().parents[2]


def _crashed(kit, invoice, total, idem):
    """prepare + commit a request whose process dies after the downstream succeeded. Returns (psp, receipt, req)."""
    psp = kit.gate._tools.get(INVOICE_TOOL)
    if not isinstance(psp, ExternalPSP):
        psp = ExternalPSP(kit.erp, kit.factory, idempotent=False)
        kit.gate._tools[INVOICE_TOOL] = psp
    kit.set_scope("5000.00")
    req, docs = kit.json_request(invoice, total, idem=idem)
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW", r.reasons
    psp.crash_after = True
    with pytest.raises(ProcessCrash):
        kit.gate.commit(r.receipt, req)
    psp.crash_after = False
    return psp, r.receipt, req


def _next(kit, invoice, total, idem):
    req, docs = kit.json_request(invoice, total, idem=idem)
    return req, kit.gate.prepare(req, docs)


def test_marker_holds_the_complete_reservation(kit):
    _, receipt, _ = _crashed(kit, "INV-8501", "4900.00", "idem-a")
    nonce = receipt["payload"]["nonce"]
    row = kit.sql("SELECT idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount, record_id "
                  "FROM tool_reached WHERE nonce = %s", (nonce,))[0]
    assert row[0] == "idem-a" and len(row[1]) == 64 and row[2:5] == ("agent-7", "user-123", "V-ACME")
    assert row[5] == Decimal("4900.00") and row[6] == "invoice:INV-8501"
    assert kit.commits() == 0  # nothing committed: the reservation is the marker alone


def test_crash_after_4900_counts_toward_the_cap(kit):
    """A $4,900 external action succeeded and the process died: a further $250 for the same actor/vendor/person
    must hit AP-CUM-03 (4900 + 250 > 5000) and must not reach the downstream."""
    psp, *_ = _crashed(kit, "INV-8601", "4900.00", "idem-big")
    assert len(psp.log) == 1 and kit.commits() == 0
    assert kit.sql("SELECT COALESCE(SUM(amount), 0) FROM reservations")[0][0] == Decimal("4900.00")
    req, r = _next(kit, "INV-8602", "250.00", "idem-small")
    if r.decision == "DENY":
        assert "AP-CUM-03" in rules(r)
    else:
        assert rules(kit.gate.commit(r.receipt, req)) == ["AP-CUM-03"]
    assert len(psp.log) == 1 and kit.commits() == 0


def test_crash_then_same_idempotency_key_on_another_record_is_refused(kit):
    psp, *_ = _crashed(kit, "INV-8701", "100.00", "idem-shared")
    req, r = _next(kit, "INV-8702", "100.00", "idem-shared")
    assert r.decision == "ALLOW", r.reasons
    c = kit.gate.commit(r.receipt, req)
    assert rules(c) == ["AP-REP-05"] and c.outcome != "EXECUTED"
    assert len(psp.log) == 1 and kit.commits() == 0


def test_idempotency_key_is_unique_in_the_database_itself(kit):
    """Backstop below the gate check: two unresolved executions cannot share a request idempotency key."""
    _crashed(kit, "INV-8801", "100.00", "idem-dup")
    with pytest.raises(psycopg.errors.UniqueViolation):
        kit.sql("INSERT INTO tool_reached (nonce, record_id, created_at, idempotency_key, request_hash, actor, "
                "on_behalf_of, vendor_id, amount) VALUES ('other', 'invoice:INV-X', 1, 'idem-dup', 'h', 'agent-7', "
                "'user-123', 'V-ACME', 1.00)")


def test_reservation_is_kept_until_an_authorized_release(kit):
    psp, receipt, req = _crashed(kit, "INV-8901", "4900.00", "idem-keep")
    total = lambda: kit.sql("SELECT COALESCE(SUM(amount), 0) FROM reservations")[0][0]  # noqa: E731
    for _ in range(2):  # retries never release it
        assert rules(kit.gate.commit(receipt, req)) == ["AP-REP-05"]
    assert total() == Decimal("4900.00")
    assert kit.gate.release_quarantine("invoice:INV-8901", "rev-alice") is True
    assert total() == Decimal("0")  # the human attests it did not execute: reservation and key are freed
    assert kit.sql("SELECT count(*) FROM tool_reached")[0][0] == 0


def test_release_with_confirmed_execution_keeps_the_amount_counted(kit):
    psp, receipt, _ = _crashed(kit, "INV-9001", "4900.00", "idem-confirmed")
    nonce = receipt["payload"]["nonce"]
    assert kit.gate.release_quarantine("invoice:INV-9001", "rev-alice", executed=True) is True
    assert kit.sql("SELECT amount FROM commits WHERE nonce = %s", (nonce,))[0][0] == Decimal("4900.00")
    assert kit.sql("SELECT COALESCE(SUM(amount), 0) FROM reservations")[0][0] == Decimal("4900.00")
    req, r = _next(kit, "INV-9002", "250.00", "idem-after")
    if r.decision == "DENY":
        assert "AP-CUM-03" in rules(r)
    else:
        assert rules(kit.gate.commit(r.receipt, req)) == ["AP-CUM-03"]
    with pytest.raises(ValueError):
        kit.gate.release_quarantine("invoice:INV-9001", "rev-alice", executed="yes")


def test_audit_chain_after_recovery_never_claims_success(kit):
    """The crashed attempt is not in the chain as EXECUTED; the denial and the reconciliation are, and it verifies."""
    psp, receipt, req = _crashed(kit, "INV-9101", "100.00", "idem-audit")
    nonce = receipt["payload"]["nonce"]
    kit.gate.commit(receipt, req)  # denied retry, audited
    kit.gate.release_quarantine("invoice:INV-9101", "rev-alice")
    rows = kit.sql("SELECT kind, decision, detail FROM audit_log ORDER BY seq")
    assert not [r for r in rows if r[0] == "commit" and r[1] == "EXECUTED" and (r[2] or {}).get("nonce") == nonce]
    assert any(r[0] == "commit" and r[1] == "DENY" for r in rows)
    rel = [r for r in rows if r[0] == "release_quarantine"][-1]
    assert rel[1] == "RELEASED" and rel[2]["executed"] is False
    assert rel[2]["unresolved"] == [{"nonce": nonce, "amount": "100.00"}]
    with kit.factory() as conn:
        n, m = audit.verify(conn, kit.signer.public_key_b64())
    assert n > 0 and m > 0


# ---- a real process, really killed, with a downstream log that lives outside every process

def test_real_process_kill_after_the_effect(kit, opa_url, signing_key_path, tmp_path):
    kit.set_scope("5000.00")
    req, docs = kit.json_request("INV-9201", "4900.00", idem="idem-kill")
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW", r.reasons
    payload, log = tmp_path / "p.json", tmp_path / "downstream.log"
    payload.write_text(json.dumps({"receipt": r.receipt, "request": req.model_dump(mode="json")}))
    env = {**os.environ, "DATABASE_URL": kit.pg, "OPA_URL": opa_url, "SIGNING_KEY_PATH": str(signing_key_path),
           "SIGNING_KID": kit.settings.signing_kid, "TESSERACT_CMD": kit.settings.tesseract_cmd,
           "PYTHONPATH": str(ROOT / "src")}
    child = subprocess.run([sys.executable, str(Path(__file__).with_name("_crash_child.py")), str(payload), str(log)],
                           env=env, cwd=ROOT, capture_output=True, timeout=120)
    assert child.returncode == 137, child.stderr.decode()[-400:]  # terminated by os._exit, not a clean return
    assert log.read_text().splitlines() == ["idem-kill"]          # the downstream effect exists, outside the DB
    assert kit.commits() == 0                                      # and the database rolled back
    assert kit.sql("SELECT amount FROM tool_reached")[0][0] == Decimal("4900.00")

    # Recovery in a NEWLY INITIALISED Gate process (new interpreter, new DB connections), same receipt, same downstream
    retry = subprocess.run([sys.executable, str(Path(__file__).with_name("_crash_child.py")), str(payload), str(log),
                            "retry"], env=env, cwd=ROOT, capture_output=True, timeout=120)
    assert retry.returncode == 0, retry.stderr.decode()[-400:]
    out = json.loads(retry.stdout.decode().strip().splitlines()[-1])
    assert out["outcome"] != "EXECUTED" and out["rules"] == ["AP-REP-05"]
    assert log.read_text().splitlines() == ["idem-kill"]          # no second effect
    kit.gate._tools[INVOICE_TOOL] = FilePSP(kit.erp, kit.factory, log)
    req2, r2 = _next(kit, "INV-9202", "250.00", "idem-kill-2")     # and the cap still sees the $4,900
    if r2.decision != "DENY":
        assert rules(kit.gate.commit(r2.receipt, req2)) == ["AP-CUM-03"]
    assert log.read_text().splitlines() == ["idem-kill"]


def test_crashed_refund_counts_toward_the_customer_cap(kit):
    """The refund connector reads the same reservations: a refund that executed and crashed still counts."""
    kit.seed_payment("PAY-9901", "CUST-9901", "900.00", "pm_card_4242")
    kit.seed_payment("PAY-9902", "CUST-9901", "300.00", "pm_card_4242")
    kit.prior_refunds("CUST-9901", ["1200.00", "1200.00", "1200.00", "500.00"])  # 4100.00 committed earlier
    real = kit.refunds.execute

    def crash_after(*a, **kw):
        real(*a, **kw)
        raise ProcessCrash("after the refund executed")

    req, docs = kit.refund_json("PAY-9901", "900.00", "CUST-9901", "pm_card_4242", idem="idem-r1")
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW", r.reasons
    kit.refunds.execute = crash_after
    with pytest.raises(ProcessCrash):
        kit.gate.commit(r.receipt, req)
    kit.refunds.execute = real
    assert len(kit.refunds.calls) == 1 and kit.commits() == 4  # only the four prior rows are commits
    assert kit.sql("SELECT COALESCE(SUM(amount), 0) FROM reservations")[0][0] == Decimal("5000.00")  # 4100 + the crashed 900
    req2, docs2 = kit.refund_json("PAY-9902", "100.00", "CUST-9901", "pm_card_4242", idem="idem-r2")
    r2 = kit.gate.prepare(req2, docs2)
    if r2.decision == "DENY":
        assert "AP-CUM-03" in rules(r2)
    else:
        assert rules(kit.gate.commit(r2.receipt, req2)) == ["AP-CUM-03"]
    assert len(kit.refunds.calls) == 1
