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
    """DSN of a reachable Postgres with the schema applied; starts the dev cluster if needed."""
    import psycopg

    from actionproof import db

    url = _dev_database_url()
    try:
        psycopg.connect(url, connect_timeout=3).close()
    except psycopg.OperationalError:
        subprocess.run([sys.executable, str(_ROOT / "scripts" / "dev_pg.py"), "start"], check=True)
    with db.connect(url=url) as conn:
        db.apply_schema(conn)
    return url


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
    """A running OPA server loaded with policy/. Logs go to a file, never an unread pipe (it blocks OPA)."""
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
        httpx.post(f"{url}/v1/data/actionproof/decision", json={"input": {}}, timeout=5)  # warm up
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
