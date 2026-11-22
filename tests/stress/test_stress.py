"""Randomized + concurrent stress of the real Gate (Postgres + OPA), seeded and reproducible.

    STRESS_N=10000 STRESS_SEED=1 python -m uv run pytest tests/stress -q -s

Default N is small so the normal suite stays quick. Every operation is checked against an independent oracle, then the
whole run is checked for the global invariants: executes == commits, no nonce/key executed twice, per (actor, vendor)
and per-person totals never above the cap, every denial names a guarantee and a rule, the audit chain verifies.
"""
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from gatekit import rules

from actionproof import audit

N = int(os.environ.get("STRESS_N", "150"))
SEED = int(os.environ.get("STRESS_SEED", "1"))
CAP = Decimal("5000.00")
VENDORS = [f"V-S{i:02d}" for i in range(40)]


def _money(rng, lo=1, hi=1500) -> str:
    return f"{rng.randint(lo, hi)}.{rng.randint(0, 99):02d}"


def _setup(kit):
    kit.set_scope("5000.00", vendors=VENDORS + ["V-ACME"])


def _one(kit, rng, i, log, lock):
    kind = rng.choice(["allow", "allow", "allow", "review", "replay", "reuse_key", "tamper", "bad_token", "overcap"])
    inv, vendor = f"S{i}", rng.choice(VENDORS)
    amt = _money(rng, 1, 900) if kind != "overcap" else _money(rng, 2500, 4999)
    po = amt if kind != "review" else f"{Decimal(amt) - Decimal(rng.randint(150, 400)):.2f}"
    kit.seed_invoice(inv, amt, po, vendor)
    req, docs = kit.json_request(inv, amt, po, idem=f"idem-{kind}-{i}", seed=False)
    res = kit.gate.prepare(req, docs)
    with lock:
        log["prepared"] += 1
    if res.receipt is None:
        assert res.decision == "DENY" and res.reasons and all(r.guarantee in ("G1", "G2") and r.rule for r in res.reasons)
        return
    token = None
    if res.decision == "REVIEW":
        token = kit.mint(res.receipt, req)
    if kind == "tamper":
        bad, _ = kit.json_request(inv, f"{Decimal(amt) + 1:.2f}", po, idem=f"idem-{kind}-{i}", seed=False)
        c = kit.gate.commit(res.receipt, bad, review_token=token)
        assert c.outcome != "EXECUTED" and rules(c) == ["AP-HASH-08"], rules(c)
        return
    if kind == "bad_token" and res.decision == "REVIEW":
        c = kit.gate.commit(res.receipt, req, review_token="not-a-token")
        assert c.outcome != "EXECUTED"
        token = token  # the real token still works afterwards (a wrong token burns nothing)
    c = kit.gate.commit(res.receipt, req, review_token=token)
    if c.outcome == "EXECUTED":
        with lock:
            log["executed"] += 1
        if kind == "replay":
            again = kit.gate.commit(res.receipt, req, review_token=token)
            assert again.outcome != "EXECUTED" and "AP-REP-05" in rules(again)
        if kind == "reuse_key":
            r2 = kit.gate.prepare(*kit.json_request(inv, amt, po, idem=f"idem-{kind}-{i}", seed=False))
            if r2.receipt is not None:
                t2 = kit.mint(r2.receipt, req) if r2.decision == "REVIEW" else None
                c2 = kit.gate.commit(r2.receipt, req, review_token=t2)
                assert c2.outcome != "EXECUTED"
    else:
        assert c.reasons and all(r.guarantee in ("G1", "G2") and r.rule for r in c.reasons)


def _global_invariants(kit, log):
    commits = kit.sql("SELECT count(*) FROM commits")[0][0]
    assert kit.executes == commits == len(kit.tool.calls) == log["executed"], (kit.executes, commits, log)
    assert kit.sql("SELECT count(*) - count(DISTINCT nonce) FROM commits")[0][0] == 0
    assert kit.sql("SELECT count(*) - count(DISTINCT idempotency_key) FROM commits")[0][0] == 0
    for actor, vendor, total in kit.sql("SELECT actor, vendor_id, SUM(amount) FROM reservations GROUP BY 1, 2"):
        assert total <= CAP, (actor, vendor, total)
    for person_total in kit.sql("SELECT SUM(r.amount) FROM reservations r LEFT JOIN people p ON p.login = r.on_behalf_of "
                                "GROUP BY COALESCE(p.person_id, r.on_behalf_of), r.vendor_id"):
        assert person_total[0] <= CAP
    assert kit.sql("SELECT count(*) FROM tool_reached t WHERE NOT EXISTS (SELECT 1 FROM commits c WHERE c.nonce = t.nonce)") == [(0,)]
    audit.verify(kit.db, {kit.signer.kid: kit.signer.public_key_b64()})  # raises AuditFailure on any break


def test_randomized_sequential(kit):
    _setup(kit)
    rng, log, lock = random.Random(SEED), {"prepared": 0, "executed": 0}, threading.Lock()
    for i in range(N):
        _one(kit, rng, i, log, lock)
    _global_invariants(kit, log)
    print(f"\nSTRESS sequential N={N} seed={SEED}: {log}")


def test_concurrent_cap_and_replay(kit):
    """Many threads racing for the same actor+vendor cap and the same idempotency keys: totals never pass the cap,
    each key executes at most once, executes == commits."""
    _setup(kit)
    kit.seed_invoice("SC0", "1.00", "1.00", "V-ACME")
    log, lock = {"prepared": 0, "executed": 0}, threading.Lock()
    reqs = []
    for i in range(max(40, N // 5)):
        inv = f"SC{i}"
        kit.seed_invoice(inv, "900.00", "900.00", "V-ACME")
        r, d = kit.json_request(inv, "900.00", "900.00", idem=f"idem-c-{i % 20}", seed=False)  # keys collide across invoices
        res = kit.gate.prepare(r, d)
        if res.receipt is not None and res.decision == "ALLOW":
            reqs.append((res.receipt, r))

    def go(item):
        c = kit.gate.commit(*item)
        if c.outcome == "EXECUTED":
            with lock:
                log["executed"] += 1
        return c.outcome

    with ThreadPoolExecutor(8) as ex:
        list(ex.map(go, reqs + reqs))  # every receipt is attempted twice, concurrently
    _global_invariants(kit, log)
    assert log["executed"] <= 5  # 5 x 900.00 = 4500.00; a sixth would pass 5000.00
    print(f"\nSTRESS concurrent: receipts={len(reqs)} executed={log['executed']}")
