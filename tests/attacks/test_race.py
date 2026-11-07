"""Attack S6.7 race (TOCTOU): version precondition at commit -> AP-STALE-07 / G2; concurrent commits execute once."""
import threading

from gatekit import rules

from actionproof import db as dbmod
from attacks._concurrency import race, reset_round

ROUNDS = 20


def _ready(kit, invoice_id, idem, seed=True):
    req, docs = kit.json_request(invoice_id, "100.00", idem=idem, seed=seed)
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW", r.reasons
    return req, r.receipt


def test_record_mutated_mid_flight(kit):
    req, receipt = _ready(kit, "INV-8101", "race-1")
    kit.sql("UPDATE records SET version = version + 1 WHERE record_id = 'invoice:INV-8101'")
    c = kit.gate.commit(receipt, req)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-STALE-07", "G2")]
    assert kit.tool.calls == []


def test_same_receipt_twice_concurrently(kit):
    """Two threads commit the SAME receipt: one EXECUTED, one AP-REP-05, one tool call."""
    for n in range(ROUNDS):
        reset_round(kit)
        req, receipt = _ready(kit, f"INV-82{n:02d}", f"dup-{n}")
        results = race(lambda: kit.gate.commit(receipt, req), lambda: kit.gate.commit(receipt, req))
        assert sorted(r.outcome for r in results) == ["DENY", "EXECUTED"], n
        assert rules(next(r for r in results if r.outcome == "DENY")) == ["AP-REP-05"], n
        assert len(kit.tool.calls) == 1 and kit.executes == 1, n


def test_two_receipts_same_record_concurrently(kit):
    """Two receipts (different keys) for one invoice at the same version: one executes, the other is stale."""
    for n in range(ROUNDS):
        reset_round(kit)
        a, ra = _ready(kit, f"INV-83{n:02d}", f"a-{n}")
        b, rb = _ready(kit, f"INV-83{n:02d}", f"b-{n}", seed=False)
        results = race(lambda: kit.gate.commit(ra, a), lambda: kit.gate.commit(rb, b))
        assert sorted(r.outcome for r in results) == ["DENY", "EXECUTED"], n
        assert rules(next(r for r in results if r.outcome == "DENY")) == ["AP-STALE-07"], n
        assert len(kit.tool.calls) == 1 and kit.version(f"invoice:INV-83{n:02d}") == 2, n


def test_review_token_raced(kit):
    """Two receipts for one REVIEW request share one human token: exactly one consumes it."""
    for n in range(ROUNDS):
        reset_round(kit)
        req, docs = kit.json_request(f"INV-84{n:02d}", "4800.00", "4300.00", idem=f"tok-{n}")
        r1, r2 = kit.gate.prepare(req, docs).receipt, kit.gate.prepare(req, docs).receipt
        token = kit.mint(r1, req)
        results = race(lambda: kit.gate.commit(r1, req, token), lambda: kit.gate.commit(r2, req, token))
        assert sorted(r.outcome for r in results) == ["DENY", "EXECUTED"], n
        assert rules(next(r for r in results if r.outcome == "DENY")) == ["AP-REP-05"], n
        assert len(kit.tool.calls) == 1, n


def test_external_writer_races_commit(kit):
    """An outside writer bumps the record while the commit runs: either it lands first (STALE, no call) or it
    waits for the gate's row lock (EXECUTED, one call). Never both, never an exception, never a lost bump."""
    seen = set()
    for n in range(ROUNDS):
        reset_round(kit)
        rid = f"invoice:INV-85{n:02d}"
        req, receipt = _ready(kit, f"INV-85{n:02d}", f"ext-{n}")

        def bump():
            with dbmod.connect(url=kit.pg) as conn:
                conn.execute("UPDATE records SET version = version + 1 WHERE record_id = %s", (rid,))
            return "bumped"

        res, _ = race(lambda: kit.gate.commit(receipt, req), bump)
        if res.outcome == "EXECUTED":
            assert len(kit.tool.calls) == 1 and kit.version(rid) == 3, n  # gate +1, writer +1
        else:
            assert rules(res) == ["AP-STALE-07"] and kit.tool.calls == [] and kit.version(rid) == 2, n
        seen.add(res.outcome)
    assert seen  # both interleavings are legal; the invariants above hold for whichever happened


def test_many_commits_one_receipt(kit):
    """Eight threads replay one receipt at once: exactly one tool call."""
    req, receipt = _ready(kit, "INV-8601", "many")
    results = race(*[lambda: kit.gate.commit(receipt, req)] * 8)
    assert [r.outcome for r in results].count("EXECUTED") == 1
    assert {tuple(rules(r)) for r in results if r.outcome == "DENY"} == {("AP-REP-05",)}
    assert len(kit.tool.calls) == 1 and threading.active_count() >= 1
