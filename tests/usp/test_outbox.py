"""USP G2 (ADR-035): the execution outbox resolves UNKNOWN executions by signed lookup, never by redispatch.

`python -m actionproof.reconcile auto` enqueues every journaled UNKNOWN execution (one execution_outbox row each),
claims rows with FOR UPDATE SKIP LOCKED under a lease, and asks the adapter `lookup(idempotency_key)` OUTSIDE any
database transaction. Only a signed APPLIED (confirm) or a signed NOT_APPLIED whose provider window has closed
(definite failure) resolves, through Gate.release_quarantine with evidence (RECONCILIATION_* events, audited).
Everything else stays UNKNOWN with capped backoff. The worker never calls execute (TLA+ NoRedispatch), and cannot
create a second effect, a second reservation, or release a cap without that evidence. Real Postgres, real OPA.
"""
import threading
import time
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from gatekit import INVOICE_TOOL
from test_exec_faults import ExternalPSP, ProcessCrash
from test_exec_journal import _cli_env

from actionproof import db as dbmod, evidence, journal, outbox
from actionproof.signing import KeyRegistry, Signer, generate_key

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "adapter-evidence.seed"
ADAPTER = Signer.from_path(FIXTURE, "adapter-test-1")
TRUST = KeyRegistry.for_signer(ADAPTER)


class LookupPSP(ExternalPSP):
    """The external provider with a signed lookup (the mock's). lose_request: the provider saw the request, applied
    nothing, and the response was lost (an ambiguous timeout with no effect)."""

    def __init__(self, kit):
        super().__init__(kit.erp, kit.factory, idempotent=False)
        self.evidence_signer = ADAPTER
        self.lose_request = False
        self.lookups = 0
        real = self.lookup

        def counted(key):
            self.lookups += 1
            return real(key)

        self.lookup = counted

    def execute(self, req, expected_version, idempotency_key, conn):
        if self.lose_request:
            self._saw(req, idempotency_key)
            raise TimeoutError("response lost; nothing applied")
        return super().execute(req, expected_version, idempotency_key, conn)


@pytest.fixture
def ox(kit):
    kit.sql("TRUNCATE execution_outbox")  # not in db.TABLES: this suite owns the table's rows
    psp = LookupPSP(kit)
    kit.gate._tools[INVOICE_TOOL] = psp
    kit.gate._adapter_keys = TRUST
    kit.set_scope("5000.00")
    return kit, psp


def _now():
    return int(time.time()) + 5


def _run(kit, now, owner="w1", **kw):
    return outbox.run_once(kit.factory, kit.gate._tools, kit.gate.release_quarantine, TRUST, owner, now=now,
                           min_age=kw.pop("min_age", 0), **kw)


def _prepared(kit, invoice, total="4900.00"):
    req, docs = kit.json_request(invoice, total)
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW", r.reasons
    return req, r.receipt


def _crashed(kit, psp, invoice, total="4900.00"):
    """The provider applied the effect and the gate process died before recording it: UNKNOWN, unburned marker."""
    req, receipt = _prepared(kit, invoice, total)
    psp.crash_after = True
    with pytest.raises(ProcessCrash):
        kit.gate.commit(receipt, req)
    psp.crash_after = False
    return req, receipt


def _lost(kit, psp, invoice, total="4900.00"):
    """The provider applied nothing and the response was lost: UNKNOWN, burned and quarantined (ADR-010)."""
    req, receipt = _prepared(kit, invoice, total)
    psp.lose_request = True
    kit.gate.commit(receipt, req)
    psp.lose_request = False
    return req, receipt


def _status(kit, receipt):
    with kit.factory() as conn:
        return journal.of_nonces(conn, [receipt["payload"]["nonce"]])[receipt["payload"]["nonce"]]["status"]


def _events(kit, receipt):
    return [r[0] for r in kit.sql("SELECT event FROM execution_journal WHERE nonce = %s ORDER BY seq",
                                  (receipt["payload"]["nonce"],))]


def _row(kit, receipt):
    return kit.sql("SELECT state, attempts, next_attempt_at, lease_owner, last_result FROM execution_outbox "
                   "WHERE nonce = %s", (receipt["payload"]["nonce"],))[0]


# ---- resolution only on signed evidence

def test_signed_confirm_resolves_to_confirmed_once(ox):
    kit, psp = ox
    _, receipt = _crashed(kit, psp, "INV-O1")
    assert _status(kit, receipt) == "UNKNOWN"
    now = _now()
    out = _run(kit, now)
    assert out["enqueued"] == 1 and out["resolved"] == 1
    assert _status(kit, receipt) == "RESOLVED_CONFIRMED"
    assert kit.sql("SELECT amount FROM reservations") == [(Decimal("4900.00"),)]   # one reservation, kept
    assert psp.log == ["idem-INV-O1"]                                                # never redispatched
    assert _row(kit, receipt)[0::4] == ("DONE", "CONFIRMED")
    before = _events(kit, receipt)
    assert before.count("RECONCILIATION_COMPLETED") == 1
    assert _run(kit, now + 10_000)["claimed"] == 0                                  # DONE stays done
    assert _events(kit, receipt) == before and psp.log == ["idem-INV-O1"]
    started = kit.sql("SELECT detail FROM execution_journal WHERE event = 'RECONCILIATION_STARTED'")[0][0]
    assert started["resolver"]["kind"] == "evidence" and "adapter-test-1" in started["resolver"]["source"]


def test_lookup_says_unknown_stays_unknown_with_capped_backoff(ox):
    kit, psp = ox
    _, receipt = _crashed(kit, psp, "INV-O2")
    psp.lookup = lambda key: ADAPTER.sign(evidence.statement("lookup", key, "UNKNOWN", "4900.00", "V-ACME", b"?"))
    now = _now()
    assert _run(kit, now)["ambiguous"] == 1
    assert _row(kit, receipt)[:3] == ("PENDING", 1, now + outbox.BACKOFF_BASE)
    assert _run(kit, now + 1)["claimed"] == 0                                       # not due yet
    assert _run(kit, now + outbox.BACKOFF_BASE)["ambiguous"] == 1
    assert _row(kit, receipt)[:3] == ("PENDING", 2, now + 3 * outbox.BACKOFF_BASE)
    kit.sql("UPDATE execution_outbox SET attempts = 40")
    _run(kit, now + 10_000)
    assert _row(kit, receipt)[2] == now + 10_000 + outbox.BACKOFF_CAP
    assert _status(kit, receipt) == "UNKNOWN" and psp.log == ["idem-INV-O2"]
    assert kit.sql("SELECT amount FROM tool_reached") == [(Decimal("4900.00"),)]


@pytest.mark.parametrize("lie", ["unsigned", "rogue_key", "tampered", "wrong_amount", "wrong_key", "raises",
                                 "no_lookup", "execute_op"])
def test_lookup_without_valid_signed_evidence_stays_unknown(ox, tmp_path, lie):
    kit, psp = ox
    _, receipt = _crashed(kit, psp, "INV-O3")
    s = evidence.statement("lookup", "idem-INV-O3", "APPLIED", "4900.00", "V-ACME", b"ok", provider_ref="psp-1")
    if lie == "unsigned":
        psp.lookup = lambda key: {"payload": s, "sig": "", "kid": "adapter-test-1"}
    elif lie == "rogue_key":
        generate_key(tmp_path / "rogue.seed")
        psp.lookup = lambda key: Signer.from_path(tmp_path / "rogue.seed", "adapter-test-1").sign(s)
    elif lie == "tampered":
        env = ADAPTER.sign({**s, "status": "NOT_APPLIED", "reason": "NOT_FOUND", "provider_ref": ""})
        env["payload"] = s
        psp.lookup = lambda key: env
    elif lie == "wrong_amount":
        psp.lookup = lambda key: ADAPTER.sign({**s, "amount": "49.00"})
    elif lie == "wrong_key":
        psp.lookup = lambda key: ADAPTER.sign({**s, "idempotency_key": "idem-other"})
    elif lie == "raises":
        def boom(key):
            raise TimeoutError("provider down")
        psp.lookup = boom
    elif lie == "no_lookup":
        kit.gate._tools[INVOICE_TOOL] = object()
    elif lie == "execute_op":
        psp.lookup = lambda key: ADAPTER.sign({**s, "op": "execute"})
    assert _run(kit, _now())["ambiguous"] == 1
    assert _status(kit, receipt) == "UNKNOWN" and "RECONCILIATION_STARTED" not in _events(kit, receipt)
    assert kit.sql("SELECT amount FROM tool_reached") == [(Decimal("4900.00"),)]
    assert not kit.sql("SELECT 1 FROM audit_log WHERE kind = 'release_quarantine'")


def test_signed_no_effect_before_the_window_closes_stays_unknown(ox):
    kit, psp = ox
    psp.window_seconds = 3600
    req, receipt = _lost(kit, psp, "INV-O4", "100.00")
    assert _status(kit, receipt) == "UNKNOWN" and psp.log == []
    now = _now()
    assert _run(kit, now)["ambiguous"] == 1                    # NOT_APPLIED, but the provider could still apply it
    assert _status(kit, receipt) == "UNKNOWN"
    psp.seen["idem-INV-O4"]["ts"] -= 3600                      # the request was sent an hour ago: window closed
    assert _run(kit, now + 10_000)["resolved"] == 1
    assert _status(kit, receipt) == "RESOLVED_FAILED" and psp.log == []
    # ADR-010 unchanged: the burned reservation and the spent receipt stay; only the quarantine is lifted.
    assert kit.sql("SELECT amount FROM reservations") == [(Decimal("100.00"),)]
    assert not kit.sql("SELECT 1 FROM quarantine")
    assert [r.rule for r in kit.gate.commit(receipt, req).reasons] == ["AP-REP-05"]


def test_window_is_judged_by_the_worker_clock_and_the_statement_time():
    x = {"idempotency_key": "k", "amount": "1.00", "vendor_id": "V"}

    def env(ts, closes):
        return ADAPTER.sign(evidence.statement("lookup", "k", "NOT_APPLIED", "1.00", "V", b"", reason="NOT_FOUND",
                                               ts=ts, window_closes_at=closes))

    assert evidence.lookup_outcome(env(200, 100), x, TRUST, 300)[0] == evidence.DEFINITE_FAILURE
    assert evidence.lookup_outcome(env(200, 100), x, TRUST, 99)[0] == evidence.AMBIGUOUS     # worker: not yet
    assert evidence.lookup_outcome(env(50, 100), x, TRUST, 300)[0] == evidence.AMBIGUOUS     # said before close
    assert evidence.lookup_outcome(env(200, 0), x, TRUST, 300)[0] == evidence.AMBIGUOUS      # no window stated
    assert evidence.lookup_outcome(env(10**9, 100), x, TRUST, 300)[0] == evidence.AMBIGUOUS  # from the future


# ---- leases and races

def test_worker_crash_mid_lookup_lease_expires_and_one_worker_resolves(ox):
    kit, psp = ox
    _, receipt = _crashed(kit, psp, "INV-O5")
    now = _now()
    with kit.factory() as conn:
        assert outbox.enqueue(conn, now, 0) == 1
        dead = outbox.claim(conn, "w-dead", now, lease=30)        # claims, then dies mid-lookup
    assert len(dead) == 1 and _row(kit, receipt)[3] == "w-dead"
    assert _run(kit, now + 10, owner="w2")["claimed"] == 0        # the lease still holds
    with kit.factory() as conn:
        mine = outbox.claim(conn, "w2", now + 31, lease=30)        # expired: w2 takes over
    assert len(mine) == 1 and mine[0]["attempts"] == 2
    # The dead worker wakes up late: its lease is gone, it resolves nothing.
    args = (kit.factory, kit.gate._tools, kit.gate.release_quarantine, TRUST)
    assert outbox.process(*args, dead[0], "w-dead", now + 5) == "LEASE_LOST"
    assert _status(kit, receipt) == "UNKNOWN"
    assert outbox.process(*args, mine[0], "w2", now + 31) == evidence.CONFIRMED
    assert outbox.process(*args, dead[0], "w-dead", now + 40) == "ALREADY_RESOLVED"
    assert _events(kit, receipt).count("RECONCILIATION_COMPLETED") == 1
    assert kit.sql("SELECT count(*) FROM commits")[0][0] == 1 and psp.log == ["idem-INV-O5"]


def test_two_workers_racing_one_row_one_wins(ox):
    kit, psp = ox
    _crashed(kit, psp, "INV-O6")
    now = _now()
    with kit.factory() as conn:
        outbox.enqueue(conn, now, 0)
    barrier, got = threading.Barrier(2), {}

    def worker(name):
        conn = dbmod.connect(url=kit.pg)
        try:
            barrier.wait()
            got[name] = outbox.claim(conn, name, now, lease=30)
        finally:
            conn.close()

    ts = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(len(v) for v in got.values()) == [0, 1]


def test_fresh_dispatch_is_left_to_the_gate(ox):
    kit, psp = ox
    _crashed(kit, psp, "INV-O7")
    assert _run(kit, _now(), min_age=3600)["enqueued"] == 0 and psp.lookups == 0


def test_resolved_executions_are_never_looked_up(ox):
    kit, psp = ox
    req, receipt = _prepared(kit, "INV-O8", "100.00")
    assert kit.gate.commit(receipt, req).outcome == "EXECUTED"
    out = _run(kit, _now())
    assert out["enqueued"] == 0 and out["claimed"] == 0 and psp.lookups == 0
    assert _row(kit, receipt)[0::4] == ("DONE", "CONFIRMED")


def test_outbox_rows_are_append_only_once_done(ox):
    kit, psp = ox
    _, receipt = _crashed(kit, psp, "INV-O9")
    _run(kit, _now())
    for q in ("DELETE FROM execution_outbox", "UPDATE execution_outbox SET state = 'PENDING'"):
        with pytest.raises(psycopg.errors.RaiseException):
            kit.sql(q)
        kit.db.rollback()
    assert _row(kit, receipt)[0] == "DONE"


# ---- surfaced, never silently dropped; CLI

def test_stuck_rows_are_surfaced_by_journal_verify(ox, opa_url, signing_key_path, capsys):
    from actionproof import reconcile
    kit, psp = ox
    _crashed(kit, psp, "INV-O10")
    psp.lookup = lambda key: None
    _run(kit, _now())
    kit.sql("UPDATE execution_outbox SET attempts = %s", (outbox.STUCK_ATTEMPTS,))
    capsys.readouterr()
    assert reconcile.main(["journal", "verify"], env=_cli_env(kit, opa_url, signing_key_path)) == 0
    assert "outbox: 1 pending, 0 in flight, 1 stuck" in capsys.readouterr().out


def test_cli_auto_needs_adapter_trust_and_never_resolves_without_evidence(ox, opa_url, signing_key_path, tmp_path,
                                                                           capsys):
    import json
    from actionproof import reconcile
    kit, psp = ox
    _, receipt = _crashed(kit, psp, "INV-O11")
    env = _cli_env(kit, opa_url, signing_key_path)
    assert reconcile.main(["auto", "--once"], env=env) == 2                          # no trusted adapter key
    keys = tmp_path / "adapter-keys.json"
    keys.write_text(json.dumps({"keys": {"adapter-test-1": {"pub": ADAPTER.public_key_b64(), "status": "active"}}}))
    capsys.readouterr()
    # The CLI's own (unsigned) mock adapter has no evidence: the execution stays UNKNOWN, the row stays PENDING.
    assert reconcile.main(["auto", "--once", "--min-age", "0"], env={**env, "ADAPTER_EVIDENCE_KEYS": str(keys)}) == 0
    assert "1 ambiguous" in capsys.readouterr().out
    assert _status(kit, receipt) == "UNKNOWN" and _row(kit, receipt)[:2] == ("PENDING", 1)
