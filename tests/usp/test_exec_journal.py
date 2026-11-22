"""USP G1+G2 (ADR-029): the execution journal tells the truth about every dispatched execution.

Append-only, hash-chained, on its own connections. RESERVATION_CREATED and DISPATCH_STARTED are durable BEFORE the
tool runs; EXECUTION_CONFIRMED only after the tool returned; a raise is FAILED only when the adapter definitively says
so, else UNKNOWN; a crash leaves DISPATCH_STARTED with no outcome, which reads as UNKNOWN. Reconciliation (human or
evidence) is journaled; elapsed time alone never resolves anything. Real Postgres, real OPA, real killed process.
"""
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from gatekit import INVOICE_TOOL, rules
from test_exec_faults import ExternalPSP, ProcessCrash

from actionproof import audit, gate as gate_mod, journal

ROOT = Path(__file__).resolve().parents[2]
REFS = ("nonce", "request_hash", "idempotency_key", "record_id", "actor", "on_behalf_of", "vendor_id", "amount")


def _events(kit, nonce=None):
    q = (f"SELECT event, execution_id, {', '.join(REFS)}, detail FROM execution_journal "
         + ("WHERE nonce = %s " if nonce else "") + "ORDER BY seq")
    return kit.sql(q, (nonce,) if nonce else ())


def _prepared(kit, invoice, total="100.00", idem=None, psp=None):
    if psp is not None:
        kit.gate._tools[INVOICE_TOOL] = psp
    kit.set_scope("5000.00")
    req, docs = kit.json_request(invoice, total, idem=idem)
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW", r.reasons
    return req, r.receipt


def _crashed(kit, invoice, total="100.00", idem=None):
    psp = ExternalPSP(kit.erp, kit.factory, idempotent=False)
    req, receipt = _prepared(kit, invoice, total, idem, psp)
    psp.crash_after = True
    with pytest.raises(ProcessCrash):
        kit.gate.commit(receipt, req)
    psp.crash_after = False
    return psp, req, receipt


def _status(kit, nonce):
    with kit.factory() as conn:
        return {x["nonce"]: x for x in journal.executions(conn)}[nonce]["status"]


def _verify(kit):
    with kit.factory() as conn:
        return journal.verify(conn)


# ---- the commit path

def test_success_events_in_order_with_full_references(kit):
    req, receipt = _prepared(kit, "INV-J1", "4900.00", "idem-j1")
    assert kit.gate.commit(receipt, req).outcome == "EXECUTED"
    p = receipt["payload"]
    ev = _events(kit, p["nonce"])
    assert [e[0] for e in ev] == ["RESERVATION_CREATED", "DISPATCH_STARTED", "EXECUTION_CONFIRMED"]
    xid = journal.execution_id(p["nonce"])
    for e in ev:
        assert e[1] == xid
        assert e[2:10] == (p["nonce"], p["request_hash"], "idem-j1", "invoice:INV-J1", "agent-7", "user-123", "V-ACME",
                           Decimal("4900.00"))
    # the main audit commit entry references the CONFIRMED journal event (seq + hash), never a pre-dispatch claim
    conf = kit.sql("SELECT seq, entry_hash FROM execution_journal WHERE event = 'EXECUTION_CONFIRMED'")[0]
    entry = kit.sql("SELECT detail FROM audit_log WHERE kind = 'commit' AND decision = 'EXECUTED'")[0][0]
    assert entry["execution_id"] == xid and entry["journal"] == {"seq": conf[0], "entry_hash": conf[1]}
    assert _status(kit, p["nonce"]) == "CONFIRMED"
    assert _verify(kit) == 3
    with kit.factory() as conn:
        assert audit.verify(conn, kit.signer.public_key_b64())[0] > 0


def test_definite_failure_is_failed_and_still_single_use(kit):
    req, receipt = _prepared(kit, "INV-J2")

    def declined(*a, **kw):
        raise journal.DefiniteFailure("downstream declined; nothing applied")

    kit.tool.execute = declined
    res = kit.gate.commit(receipt, req)
    assert res.outcome == "DENY" and rules(res) == ["AP-ERR-11"]
    nonce = receipt["payload"]["nonce"]
    assert [e[0] for e in _events(kit, nonce)] == ["RESERVATION_CREATED", "DISPATCH_STARTED", "EXECUTION_FAILED"]
    assert _status(kit, nonce) == "FAILED"
    assert rules(kit.gate.commit(receipt, req)) == ["AP-REP-05"]   # the receipt stays spent
    assert not kit.sql("SELECT 1 FROM audit_log WHERE kind = 'commit' AND decision = 'EXECUTED'")


def test_tool_raising_ambiguously_is_unknown(kit):
    psp = ExternalPSP(kit.erp, kit.factory, idempotent=False)
    req, receipt = _prepared(kit, "INV-J3", psp=psp)
    psp.timeout_after = True
    assert rules(kit.gate.commit(receipt, req)) == ["AP-ERR-11"]
    nonce = receipt["payload"]["nonce"]
    ev = _events(kit, nonce)
    assert [e[0] for e in ev] == ["RESERVATION_CREATED", "DISPATCH_STARTED", "EXECUTION_UNKNOWN"]
    assert ev[-1][-1] == {"error": "TimeoutError"}
    assert _status(kit, nonce) == "UNKNOWN" and len(psp.log) == 1


def test_crash_after_effect_leaves_dispatch_without_outcome(kit):
    psp, req, receipt = _crashed(kit, "INV-J4", idem="idem-j4")
    nonce = receipt["payload"]["nonce"]
    assert [e[0] for e in _events(kit, nonce)] == ["RESERVATION_CREATED", "DISPATCH_STARTED"]
    assert _status(kit, nonce) == "UNKNOWN"
    assert rules(kit.gate.commit(receipt, req)) == ["AP-REP-05"]   # retry: still refused, never redispatched
    assert len(psp.log) == 1 and len(_events(kit, nonce)) == 2     # and the refused retry journals nothing
    assert not kit.sql("SELECT 1 FROM audit_log WHERE kind = 'commit' AND decision = 'EXECUTED'")


def test_real_process_kill_after_effect_is_visible_unknown(kit, opa_url, signing_key_path, tmp_path, capsys):
    req, receipt = _prepared(kit, "INV-J5", "4900.00", "idem-j5")
    payload, log = tmp_path / "p.json", tmp_path / "downstream.log"
    payload.write_text(json.dumps({"receipt": receipt, "request": req.model_dump(mode="json")}))
    env = {**os.environ, "DATABASE_URL": kit.pg, "OPA_URL": opa_url, "SIGNING_KEY_PATH": str(signing_key_path),
           "SIGNING_KID": kit.settings.signing_kid, "TESSERACT_CMD": kit.settings.tesseract_cmd,
           "PYTHONPATH": str(ROOT / "src")}
    child = ROOT / "tests" / "usp" / "_crash_child.py"
    run = subprocess.run([sys.executable, str(child), str(payload), str(log)], env=env, cwd=ROOT,
                         capture_output=True, timeout=120)
    assert run.returncode == 137, run.stderr.decode()[-400:]
    assert log.read_text().splitlines() == ["idem-j5"] and kit.commits() == 0
    nonce = receipt["payload"]["nonce"]
    assert [e[0] for e in _events(kit, nonce)] == ["RESERVATION_CREATED", "DISPATCH_STARTED"]
    assert _status(kit, nonce) == "UNKNOWN"
    retry = subprocess.run([sys.executable, str(child), str(payload), str(log), "retry"], env=env, cwd=ROOT,
                           capture_output=True, timeout=120)
    assert retry.returncode == 0, retry.stderr.decode()[-400:]
    assert json.loads(retry.stdout.decode().strip().splitlines()[-1])["rules"] == ["AP-REP-05"]
    assert log.read_text().splitlines() == ["idem-j5"] and len(_events(kit, nonce)) == 2
    from actionproof import reconcile
    assert reconcile.main(["journal", "list"], env=_cli_env(kit, opa_url, signing_key_path)) == 0
    out = capsys.readouterr().out
    assert journal.execution_id(nonce) in out and "UNKNOWN" in out and "4900.00" in out


# ---- tamper evidence, money type

def test_journal_is_append_only(kit):
    kit.gate.commit(*reversed(_prepared(kit, "INV-J6")))
    for q in ("UPDATE execution_journal SET amount = 1.00", "DELETE FROM execution_journal",
              "TRUNCATE execution_journal"):
        with pytest.raises(psycopg.errors.RaiseException):
            kit.sql(q)
        kit.db.rollback()
    assert _verify(kit) == 3


def test_verify_detects_a_tampered_row(kit, opa_url, signing_key_path):
    req, receipt = _prepared(kit, "INV-J7", "4900.00")
    kit.gate.commit(receipt, req)
    from actionproof import reconcile
    env = _cli_env(kit, opa_url, signing_key_path)
    assert reconcile.main(["journal", "verify"], env=env) == 0
    # The owner/superuser can switch the trigger off: exactly the tampering the hash chain exists to detect.
    kit.sql("ALTER TABLE execution_journal DISABLE TRIGGER USER")
    kit.sql("UPDATE execution_journal SET amount = 49.00 WHERE event = 'EXECUTION_CONFIRMED'")
    kit.sql("ALTER TABLE execution_journal ENABLE TRIGGER USER")
    with pytest.raises(journal.JournalFailure) as f:
        _verify(kit)
    assert f.value.seq == 3
    assert reconcile.main(["journal", "verify"], env=env) == 1


def test_verify_detects_a_deleted_row(kit):
    kit.gate.commit(*reversed(_prepared(kit, "INV-J8")))
    kit.sql("ALTER TABLE execution_journal DISABLE TRIGGER USER")
    kit.sql("DELETE FROM execution_journal WHERE seq = 2")
    kit.sql("ALTER TABLE execution_journal ENABLE TRIGGER USER")
    with pytest.raises(journal.JournalFailure):
        _verify(kit)


def test_no_float_anywhere(kit):
    t = kit.sql("SELECT data_type, numeric_precision, numeric_scale FROM information_schema.columns "
                "WHERE table_name = 'execution_journal' AND column_name = 'amount'")
    assert t == [("numeric", 18, 2)]
    ref = {k: "x" for k in REFS}
    for bad in (100.0, "100.5", "1e2", -1):
        with kit.factory() as conn, pytest.raises((TypeError, ValueError)):
            journal.append(conn, "RESERVATION_CREATED", {**ref, "amount": bad})
    with kit.factory() as conn, pytest.raises(TypeError):
        journal.append(conn, "RESERVATION_CREATED", {**ref, "amount": "1.00"}, {"x": 1.5})
    with kit.factory() as conn, pytest.raises(ValueError):
        journal.append(conn, "NOT_AN_EVENT", {**ref, "amount": "1.00"})
    assert kit.sql("SELECT count(*) FROM execution_journal")[0][0] == 0


# ---- reconciliation

def test_human_release_not_executed_is_journaled(kit):
    psp, req, receipt = _crashed(kit, "INV-J9", "4900.00")
    nonce = receipt["payload"]["nonce"]
    assert kit.gate.release_quarantine("invoice:INV-J9", "rev-alice") is True
    ev = _events(kit, nonce)
    assert [e[0] for e in ev] == ["RESERVATION_CREATED", "DISPATCH_STARTED", "RECONCILIATION_STARTED",
                                  "RECONCILIATION_COMPLETED"]
    done = ev[-1][-1]
    assert done["resolution"] == "FAILED" and done["resolver"] == {"kind": "human", "reviewer": "rev-alice"}
    started = kit.sql("SELECT seq, entry_hash FROM execution_journal WHERE event = 'RECONCILIATION_STARTED'")[0]
    rel = kit.sql("SELECT seq, detail FROM audit_log WHERE kind = 'release_quarantine'")[0]
    assert rel[1]["journal"] == [{"execution_id": journal.execution_id(nonce), "seq": started[0],
                                  "entry_hash": started[1]}]
    assert done["audit_seq"] == rel[0]
    assert _status(kit, nonce) == "RESOLVED_FAILED"
    assert kit.sql("SELECT COALESCE(SUM(amount), 0) FROM reservations")[0][0] == Decimal("0")
    assert _verify(kit) == 4


def test_human_release_executed_keeps_the_money(kit):
    _, _, receipt = _crashed(kit, "INV-J10", "4900.00")
    nonce = receipt["payload"]["nonce"]
    assert kit.gate.release_quarantine("invoice:INV-J10", "rev-alice", executed=True) is True
    assert _status(kit, nonce) == "RESOLVED_CONFIRMED"
    assert kit.sql("SELECT amount FROM commits WHERE nonce = %s", (nonce,)) == [(Decimal("4900.00"),)]


def _evidence(status, **over):
    return {"source": "psp.lookup_by_idempotency_key", "idempotency_key": "idem-ev", "status": status,
            "amount": "4900.00", "counterparty": "V-ACME", **over}


def test_evidence_applied_resolves_confirmed(kit):
    _, _, receipt = _crashed(kit, "INV-J11", "4900.00", "idem-ev")
    nonce = receipt["payload"]["nonce"]
    assert kit.gate.release_quarantine("invoice:INV-J11", "ops-1", evidence=_evidence("APPLIED")) is True
    assert _status(kit, nonce) == "RESOLVED_CONFIRMED"
    done = _events(kit, nonce)[-1][-1]
    assert done["resolver"] == {"kind": "evidence", "source": "psp.lookup_by_idempotency_key", "operator": "ops-1"}
    assert kit.sql("SELECT amount FROM commits WHERE nonce = %s", (nonce,)) == [(Decimal("4900.00"),)]


def test_evidence_not_applied_frees_the_reservation(kit):
    _, _, receipt = _crashed(kit, "INV-J12", "4900.00", "idem-ev")
    assert kit.gate.release_quarantine("invoice:INV-J12", "ops-1", evidence=_evidence("NOT_APPLIED")) is True
    assert _status(kit, receipt["payload"]["nonce"]) == "RESOLVED_FAILED"
    assert kit.sql("SELECT count(*) FROM tool_reached")[0][0] == 0


@pytest.mark.parametrize("bad", [
    {"amount": "4899.99"}, {"amount": "4900.0"}, {"amount": 4900.0}, {"idempotency_key": "other"},
    {"counterparty": "V-EVIL"}, {"status": "MAYBE"}, {"extra": "x"}, {"source": ""}])
def test_untrustworthy_evidence_changes_nothing(kit, bad):
    _, _, receipt = _crashed(kit, "INV-J13", "4900.00", "idem-ev")
    nonce = receipt["payload"]["nonce"]
    with pytest.raises(ValueError):
        kit.gate.release_quarantine("invoice:INV-J13", "ops-1", evidence={**_evidence("APPLIED"), **bad})
    assert _status(kit, nonce) == "UNKNOWN" and len(_events(kit, nonce)) == 2
    assert kit.sql("SELECT amount FROM tool_reached") == [(Decimal("4900.00"),)]
    assert not kit.sql("SELECT 1 FROM audit_log WHERE kind = 'release_quarantine'")


def test_evidence_and_human_flags_are_exclusive(kit):
    _crashed(kit, "INV-J14", "4900.00", "idem-ev")
    with pytest.raises(ValueError):
        kit.gate.release_quarantine("invoice:INV-J14", "ops-1", executed=True, evidence=_evidence("APPLIED"))


def test_confirmed_execution_cannot_be_released_as_not_executed(kit):
    """The tool returned success (CONFIRMED is journaled) and the process died before the main commit: freeing that
    reservation on a human's 'it did not happen' would widen the caps against the downstream's own confirmation."""
    req, receipt = _prepared(kit, "INV-J15", "4900.00", "idem-j15")
    real = kit.gate._audit

    def crash_on_real_entry(conn, kind, **kw):
        if kind == "commit" and "journal" in kw.get("detail", {}):
            raise ProcessCrash("after confirmation, before the main commit")
        return real(conn, kind, **kw)

    kit.gate._audit = crash_on_real_entry
    with pytest.raises(ProcessCrash):
        kit.gate.commit(receipt, req)
    kit.gate._audit = real
    nonce = receipt["payload"]["nonce"]
    assert _status(kit, nonce) == "CONFIRMED" and kit.commits() == 0
    with pytest.raises(ValueError):
        kit.gate.release_quarantine("invoice:INV-J15", "rev-alice")
    with pytest.raises(ValueError):
        kit.gate.release_quarantine("invoice:INV-J15", "ops-1", evidence=_evidence("NOT_APPLIED",
                                                                                     idempotency_key="idem-j15"))
    assert kit.sql("SELECT amount FROM reservations") == [(Decimal("4900.00"),)]
    assert kit.gate.release_quarantine("invoice:INV-J15", "rev-alice", executed=True) is True
    assert _status(kit, nonce) == "RESOLVED_CONFIRMED"


def test_audit_store_down_before_dispatch_journals_nothing(kit):
    """The commit entry is rehearsed before dispatch: an audit store that cannot take it stops the tool, and the
    journal records no execution (nothing was reserved or dispatched)."""
    req, receipt = _prepared(kit, "INV-J16")
    real = kit.gate._audit

    def broken(conn, kind, **kw):
        if kind == "commit" and kw.get("decision") == "EXECUTED":
            raise RuntimeError("audit store unavailable")
        return real(conn, kind, **kw)

    kit.gate._audit = broken
    assert rules(kit.gate.commit(receipt, req)) == ["AP-ERR-11"]
    kit.gate._audit = real
    assert kit.executes == 0 and kit.sql("SELECT count(*) FROM execution_journal")[0][0] == 0


def test_elapsed_time_never_releases(kit, monkeypatch):
    _, req, receipt = _crashed(kit, "INV-J17", "4900.00", "idem-old")
    nonce = receipt["payload"]["nonce"]
    kit.sql("UPDATE tool_reached SET created_at = 0")                 # the marker is ancient
    later = gate_mod._now() + 10 * 365 * 86400
    monkeypatch.setattr(gate_mod, "_now", lambda: later)               # and ten years have passed
    req2, docs2 = kit.json_request("INV-J18", "100.00", idem="idem-old")
    r2 = kit.gate.prepare(req2, docs2)
    if r2.decision != "DENY":
        assert rules(kit.gate.commit(r2.receipt, req2)) == ["AP-REP-05"]  # the key is still held
    assert kit.sql("SELECT COALESCE(SUM(amount), 0) FROM reservations")[0][0] == Decimal("4900.00")
    assert _status(kit, nonce) == "UNKNOWN"


def test_legacy_marker_gets_no_journal_backfill(kit):
    kit.sql("INSERT INTO tool_reached (nonce, record_id, created_at) VALUES ('legacy-n1', 'invoice:INV-LEG', 1)")
    assert kit.gate.release_quarantine("invoice:INV-LEG", "rev-alice") is True
    assert kit.sql("SELECT count(*) FROM execution_journal")[0][0] == 0
    rel = kit.sql("SELECT detail FROM audit_log WHERE kind = 'release_quarantine'")[0][0]
    assert "journal" not in rel


def test_schema_migration_is_idempotent(kit):
    from actionproof import db
    kit.gate.commit(*reversed(_prepared(kit, "INV-J19")))
    db.apply_schema(kit.db)
    db.apply_schema(kit.db)
    assert kit.sql("SELECT count(*) FROM execution_journal")[0][0] == 3 and _verify(kit) == 3


# ---- CLI

def _cli_env(kit, opa_url, signing_key_path):
    return {"DATABASE_URL": kit.pg, "OPA_URL": opa_url, "SIGNING_KEY_PATH": str(signing_key_path),
            "SIGNING_KID": kit.settings.signing_kid, "TESSERACT_CMD": kit.settings.tesseract_cmd,
            "DOCS_DIR": str(ROOT / "fixtures" / "out")}


def test_cli_resolve_by_human_and_by_evidence(kit, opa_url, signing_key_path, capsys):
    from actionproof import reconcile
    env = _cli_env(kit, opa_url, signing_key_path)
    _, _, r1 = _crashed(kit, "INV-J20", "100.00", "idem-c1")
    _, _, r2 = _crashed(kit, "INV-J21", "200.00", "idem-ev")
    x1, x2 = (journal.execution_id(r["payload"]["nonce"]) for r in (r1, r2))
    assert reconcile.main(["journal", "resolve", "--execution", x1, "--reviewer", "rev-alice"], env=env) == 2
    assert reconcile.main(["journal", "resolve", "--execution", "ex-nope", "--reviewer", "rev-alice",
                           "--not-executed"], env=env) == 2
    assert reconcile.main(["journal", "resolve", "--execution", x1, "--reviewer", "rev-alice", "--not-executed"],
                          env=env) == 0
    ev = json.dumps(_evidence("APPLIED", amount="200.00"))
    assert reconcile.main(["journal", "resolve", "--execution", x2, "--reviewer", "ops-1", "--evidence", "{bad"],
                          env=env) == 2
    assert reconcile.main(["journal", "resolve", "--execution", x2, "--reviewer", "ops-1", "--evidence", ev],
                          env=env) == 0
    assert _status(kit, r1["payload"]["nonce"]) == "RESOLVED_FAILED"
    assert _status(kit, r2["payload"]["nonce"]) == "RESOLVED_CONFIRMED"
    capsys.readouterr()
    assert reconcile.main(["journal", "list"], env=env) == 0
    assert "0 unresolved" in capsys.readouterr().out
