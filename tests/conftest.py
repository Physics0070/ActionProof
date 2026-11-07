import os
from pathlib import Path

# Dev default for the Tesseract binary, taken from .env.example (no secrets there).
for line in (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8").splitlines():
    key, sep, value = line.partition("=")
    if sep and key.strip() == "TESSERACT_CMD":
        os.environ.setdefault("TESSERACT_CMD", value.strip())


# --- Postgres fixtures (Phase 3, task 2). Real local Postgres via scripts/dev_pg.py; no Docker needed.
import subprocess  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]


def _dev_database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    for line in (_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "DATABASE_URL":
            return value.strip()
    raise RuntimeError("DATABASE_URL not set and not in .env.example")


@pytest.fixture(scope="session")
def pg() -> str:
    """DSN of a PRIVATE database for this pytest process, with the schema applied.

    Every process gets `actionproof_test_<pid>_<random>` on the dev Postgres server (created through the
    `postgres` maintenance DB and dropped at session end, even on failure), and DATABASE_URL points at it for the
    session. So two pytest runs never truncate each other's tables. Starts the dev cluster if needed.
    """
    import secrets
    from urllib.parse import urlsplit, urlunsplit

    import psycopg
    from psycopg import sql

    from actionproof import db

    base = urlsplit(_dev_database_url())

    def with_db(name: str) -> str:
        return urlunsplit(base._replace(path=f"/{name}"))

    admin = with_db("postgres")
    try:
        psycopg.connect(admin, connect_timeout=3).close()
    except psycopg.OperationalError:
        subprocess.run([sys.executable, str(_ROOT / "scripts" / "dev_pg.py"), "start"], check=True)
    name = f"actionproof_test_{os.getpid()}_{secrets.token_hex(4)}"
    with psycopg.connect(admin, autocommit=True, connect_timeout=5) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = with_db(name)
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        with db.connect(url=url) as conn:
            db.apply_schema(conn)
        yield url
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
        _close_pools(url)
        with psycopg.connect(admin, autocommit=True, connect_timeout=5) as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def _close_pools(url: str) -> None:
    """Close the gate tests' pooled connections so DROP DATABASE does not have to kill them."""
    gk = sys.modules.get("gatekit")
    for conn in (gk._POOLS.pop(url, []) if gk is not None else []):
        try:
            conn.close()
        except Exception:
            pass


@pytest.fixture
def db(pg):
    """Fresh connection to an emptied database with the hero scenario seeded."""
    from actionproof import db as dbmod

    conn = dbmod.connect(url=pg)
    dbmod.reset(conn)
    dbmod.seed_hero(conn)
    yield conn
    conn.rollback()
    conn.close()


# --- Gate fixtures (Phase 3, task 4). Real OPA binary + real Postgres; helpers live in tests/gatekit.py.
import socket  # noqa: E402
import time  # noqa: E402

_OPA_BIN = os.environ.get("OPA_BIN", "C:/Users/Soham/tools/opa/opa.exe")


@pytest.fixture(scope="session")
def opa_url(tmp_path_factory):
    """THE one OPA server for the session (gate and policy tests share it), loaded with policy/.
    Logs go to a file, never an unread pipe (it blocks OPA)."""
    import httpx

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log = tmp_path_factory.mktemp("opa-gate") / "opa.log"
    log_f = log.open("wb")
    proc = subprocess.Popen(
        [_OPA_BIN, "run", "--server", "--log-level", "error", "--disable-telemetry",
         "--addr", f"127.0.0.1:{port}", str(_ROOT / "policy")],
        stdout=log_f, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if proc.poll() is not None:
                raise RuntimeError(f"OPA exited: {log.read_text(errors='replace')}")
            try:
                if httpx.get(f"{url}/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("OPA did not become healthy")
        # Warm up on a full input (compiles every rule) and through policy.decide's shared client, so the first
        # real decision of the session is not paying cold-start cost against the 0.2 s policy timeout.
        from actionproof import policy

        warm = {"tool": "payments.approve_invoice", "actor": "agent-7", "on_behalf_of": "user-123",
                "verify": {"ok": True, "reasons": []},
                "args": {"amount": "4800.00", "variance": "500.00", "vendor_id": "V-ACME"},
                "scope": {"max_amount": "5000.00", "vendors": ["V-ACME"]}, "cumulative": {"committed": "0.00"}}
        httpx.post(f"{url}/v1/data/actionproof/decision", json={"input": warm}, timeout=5)
        for _ in range(3):
            policy.decide(warm, url, 5)
        yield url
    finally:
        proc.kill()
        proc.wait()
        log_f.close()


@pytest.fixture
def opa(opa_url, monkeypatch):
    monkeypatch.setenv("OPA_URL", opa_url)


@pytest.fixture(scope="session")
def signing_key_path(tmp_path_factory):
    from actionproof import signing

    p = tmp_path_factory.mktemp("gate-key") / "gate.key"
    signing.generate_key(p)
    return p


@pytest.fixture
def kit(db, pg, opa, opa_url, signing_key_path):
    """A wired Gate over the mocks on a freshly seeded database (see tests/gatekit.py)."""
    import gatekit

    return gatekit.Kit(pg, opa_url, signing_key_path, db)
