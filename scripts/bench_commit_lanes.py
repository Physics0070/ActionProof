"""Commit-lane benchmark (ADR-036): is the global commit lane, or the audit lock, what serialises Gate.commit?

    python scripts/bench_commit_lanes.py [--n 200] [--reps 3] [--workers 1,4,8,16] [--out results.json]

Real Postgres (a private throwaway database on the dev server, like tests/conftest.py) and a real OPA server over
policy/. Per point: n invoices are prepared sequentially (not timed), then committed by `workers` threads; the
commit phase is timed. Two pair layouts: `same` (every commit on one (actor, vendor) pair) and `spread` (every
commit on its own vendor). Two lock variants, both measured with the unchanged gate code:

- `lane`: production (LOCK TABLE commits ..., then the audit lock).
- `no_lane`: the bench-only connection wrapper drops the LOCK TABLE commits statement, so only the audit lock
  remains. This is the upper bound of ANY lane replacement (a per-(actor, vendor) lock can never beat no lane).

Attribution is wall-clock timing around the two LOCK statements and from "audit lock acquired" to the tx end
(commit/rollback), measured by a connection wrapper on the gate's own connection factory; gate.py is not modified.
After every point the global invariants of tests/stress are re-checked (executes == commits rows, unique nonces and
keys, per-pair and per-person totals <= 5000.00, the audit chain verifies).
"""
import argparse
import collections
import json
import os
import secrets
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import httpx  # noqa: E402
import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402

import gatekit  # noqa: E402
from actionproof import audit, policy, signing  # noqa: E402
from actionproof import db as dbmod  # noqa: E402

LANE = "LOCK TABLE commits IN SHARE ROW EXCLUSIVE MODE"
AUDIT = "LOCK TABLE audit_log IN EXCLUSIVE MODE"
CAP = Decimal("5000.00")
_T = threading.local()


def _stats() -> dict:
    return {"lane_wait": 0.0, "audit_wait": 0.0, "audit_hold": 0.0, "lane_hold": 0.0}


class Timed:
    """Bench-only wrapper over the gate's pooled connection: times the two LOCK statements and the audit hold."""

    def __init__(self, conn, variant: str):
        object.__setattr__(self, "_c", conn)
        object.__setattr__(self, "_v", variant)
        object.__setattr__(self, "_from", {})  # lock -> acquired at; per connection (the marker conn has none)

    def __getattr__(self, name):
        return getattr(self._c, name)

    def __setattr__(self, name, value):
        setattr(self._c, name, value)

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        self._end()
        return self._c.__exit__(et, ev, tb)

    def execute(self, q, *a, **kw):
        if q not in (LANE, AUDIT):
            return self._c.execute(q, *a, **kw)
        if q == LANE and self._v == "no_lane":
            return None
        s = getattr(_T, "s", None) or _stats()
        t0 = time.perf_counter()
        r = self._c.execute(q, *a, **kw)
        t1 = time.perf_counter()
        s["lane_wait" if q == LANE else "audit_wait"] += t1 - t0
        self._from.setdefault("audit_hold" if q == AUDIT else "lane_hold", t1)  # audit.append re-locks (no-op)
        return r

    def _end(self):
        s = getattr(_T, "s", None)
        now = time.perf_counter()
        for acc, start in self._from.items():
            if s is not None:
                s[acc] += now - start
        self._from.clear()

    def commit(self):
        r = self._c.commit()
        self._end()
        return r

    def rollback(self):
        r = self._c.rollback()
        self._end()
        return r

    def close(self):
        self._c.close()
        self._end()


class _BigPooled(gatekit._Pooled):
    """gatekit's pool keeps at most 16 idle connections; 16 workers use ~3 each per commit (tx, marker, journal),
    and a new backend costs ~240 ms on Windows, which would be measured as lock hold (the marker connection is
    opened under the audit lock). The bench pool keeps up to 128 and is pre-warmed, so no point pays connects."""

    def close(self):
        c = self._c
        if c.closed:
            return
        try:
            c.rollback()
            c.isolation_level = None
        except Exception:
            c.close()
            return
        self._pool.append(c) if len(self._pool) < 128 else c.close()


NEW_CONNS = [0]


def big_pool(url: str, warm: int):
    pool: list = []

    def factory():
        try:
            conn = pool.pop()
        except IndexError:
            NEW_CONNS[0] += 1
            conn = dbmod.connect(url=url)
        return _BigPooled(pool, conn)

    pool.extend(dbmod.connect(url=url) for _ in range(warm))
    return factory, pool


def _start_opa() -> tuple[subprocess.Popen, str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log = open(Path(tempfile.gettempdir()) / f"bench-opa-{port}.log", "wb")
    proc = subprocess.Popen([os.environ.get("OPA_BIN", "opa"), "run", "--server", "--log-level", "error",
                             "--disable-telemetry", "--addr", f"127.0.0.1:{port}", str(ROOT / "policy")],
                            stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{url}/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        raise RuntimeError("OPA did not become healthy")
    warm = {"tool": "payments.approve_invoice", "actor": "agent-7", "on_behalf_of": "user-123",
            "verify": {"ok": True, "reasons": []},
            "args": {"amount": "4800.00", "variance": "500.00", "vendor_id": "V-ACME"},
            "scope": {"max_amount": "5000.00", "vendors": ["V-ACME"]},
            "cumulative": {"committed": "0.00", "person_committed": "0.00"}}
    for _ in range(3):
        policy.decide(warm, url, 5)
    return proc, url


def _check(kit, executed: int) -> None:
    commits = kit.sql("SELECT count(*) FROM commits")[0][0]
    assert commits == executed, (commits, executed)
    assert kit.sql("SELECT count(*) - count(DISTINCT nonce) FROM commits")[0][0] == 0
    assert kit.sql("SELECT count(*) - count(DISTINCT idempotency_key) FROM commits")[0][0] == 0
    for _, _, total in kit.sql("SELECT actor, vendor_id, SUM(amount) FROM reservations GROUP BY 1, 2"):
        assert total <= CAP
    for (total,) in kit.sql("SELECT SUM(r.amount) FROM reservations r LEFT JOIN people p ON p.login = r.on_behalf_of "
                            "GROUP BY COALESCE(p.person_id, r.on_behalf_of), r.vendor_id"):
        assert total <= CAP
    audit.verify(kit.db, {kit.signer.kid: kit.signer.public_key_b64()})


def run_point(kit, base, layout: str, workers: int, n: int, variant: str, tag: str) -> dict:
    dbmod.reset(kit.db)
    dbmod.seed_hero(kit.db)
    vendors = ["V-ACME"] if layout == "same" else [f"V-B{i:04d}" for i in range(n)]
    kit.set_scope("5000.00", vendors=vendors)
    items = []
    for i in range(n):
        inv = f"B{tag}-{i}"
        kit.seed_invoice(inv, "1.00", "1.00", vendors[0] if layout == "same" else vendors[i])
        r, d = kit.json_request(inv, "1.00", "1.00", idem=f"idem-{tag}-{i}", seed=False)
        for _ in range(5):  # setup only (not timed): an OPA timeout at prepare (0.2 s budget) is retried
            res = kit.gate.prepare(r, d)
            if res.decision == "ALLOW":
                break
            assert [x.rule for x in res.reasons] == ["AP-POL-FAIL"], res.reasons
        assert res.decision == "ALLOW", res.reasons
        items.append((res.receipt, r))
    plain = kit.gate._conn_factory
    kit.gate._conn_factory = lambda: Timed(base(), variant)
    new0 = NEW_CONNS[0]

    def go(item):
        _T.s = _stats()
        t0, cpu0 = time.perf_counter(), time.thread_time()
        c = kit.gate.commit(*item)
        dt = time.perf_counter() - t0
        s, _T.s = _T.s, None
        s["cpu"] = time.thread_time() - cpu0
        s["rules"] = ",".join(x.rule for x in c.reasons)
        return c.outcome, dt, s

    try:
        t0 = time.perf_counter()
        with ThreadPoolExecutor(workers) as ex:
            out = list(ex.map(go, items))
        wall = time.perf_counter() - t0
    finally:
        kit.gate._conn_factory = plain
    executed = sum(o == "EXECUTED" for o, _, _ in out)
    _check(kit, executed)
    lat = sorted(dt for _, dt, _ in out)
    mean = lambda k: statistics.fmean(s[k] for _, _, s in out) * 1000  # noqa: E731
    return {"layout": layout, "variant": variant, "workers": workers, "n": n, "executed": executed,
            "commits_per_s": executed / wall, "p50_ms": statistics.median(lat) * 1000,
            "p95_ms": statistics.quantiles(lat, n=20)[18] * 1000,
            "lane_wait_ms": mean("lane_wait"), "audit_wait_ms": mean("audit_wait"),
            "audit_hold_ms": mean("audit_hold"), "lane_hold_ms": mean("lane_hold"),
            "cpu_ms": mean("cpu"), "total_ms": statistics.fmean(lat) * 1000,
            "new_conns": NEW_CONNS[0] - new0,
            "denied": dict(collections.Counter(s["rules"] for o, _, s in out if o != "EXECUTED"))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--workers", default="1,4,8,16")
    ap.add_argument("--variants", default="lane,no_lane")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    dsn = urlsplit(os.environ["DATABASE_URL"])
    admin = urlunsplit(dsn._replace(path="/postgres"))
    name = f"actionproof_bench_{os.getpid()}_{secrets.token_hex(4)}"
    with psycopg.connect(admin, autocommit=True, connect_timeout=5) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = urlunsplit(dsn._replace(path=f"/{name}"))
    os.environ["DATABASE_URL"] = url
    proc, opa_url = _start_opa()
    os.environ["OPA_URL"] = opa_url
    rows = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "bench.key"
            signing.generate_key(key)
            conn = dbmod.connect(url=url)
            dbmod.apply_schema(conn)
            kit = gatekit.Kit(url, opa_url, key, conn)
            base, pool = big_pool(url, 64)
            for variant in a.variants.split(","):
                for layout in ("same", "spread"):
                    for w in (int(x) for x in a.workers.split(",")):
                        for rep in range(a.reps):
                            r = run_point(kit, base, layout, w, a.n, variant, f"{variant}-{layout}-{w}-{rep}")
                            r["rep"] = rep
                            rows.append(r)
                            print(json.dumps({k: round(v, 2) if isinstance(v, float) else v for k, v in r.items()}),
                                  flush=True)
            for c in pool:
                c.close()
            conn.close()
    finally:
        proc.kill()
        proc.wait()
        for c in gatekit._POOLS.pop(url, []):
            c.close()
        with psycopg.connect(admin, autocommit=True, connect_timeout=5) as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("\nvariant layout workers | commits/s med [min-max] | p50 ms med [min-max] | p95 ms med [min-max] | "
          "lane wait / audit wait / audit hold / cpu / total ms (median of reps)")
    keys = sorted({(r["variant"], r["layout"], r["workers"]) for r in rows},
                  key=lambda k: (k[0] != "lane", k[1], k[2]))
    for k in keys:
        g = [r for r in rows if (r["variant"], r["layout"], r["workers"]) == k]

        def f(m):
            v = [r[m] for r in g]
            return f"{statistics.median(v):.1f} [{min(v):.1f}-{max(v):.1f}]"

        med = lambda m: statistics.median(r[m] for r in g)  # noqa: E731
        print(f"{k[0]:7} {k[1]:6} {k[2]:2} | {f('commits_per_s')} | {f('p50_ms')} | {f('p95_ms')} | "
              f"{med('lane_wait_ms'):.1f} / {med('audit_wait_ms'):.1f} / {med('audit_hold_ms'):.1f} / {med('cpu_ms'):.1f} / "
              f"{med('total_ms'):.1f}")


if __name__ == "__main__":
    main()
