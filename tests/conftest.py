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
