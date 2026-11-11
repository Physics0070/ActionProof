"""Local dev Postgres without Docker: python scripts/dev_pg.py start|stop|status|reset

Binaries from PG_BIN (a folder; empty = use the ones on PATH), data in .pgdata/ (git-ignored),
port PG_PORT (default 5433), user/password/db PG_USER/PG_PASSWORD/PG_DB (defaults match .env.example).
Idempotent: `start` on a running cluster only ensures the database and schema exist.
Docker compose stays the production path.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PG_BIN = os.environ.get("PG_BIN", "")
DATA = ROOT / ".pgdata"
PORT = os.environ.get("PG_PORT", "5433")
USER = os.environ.get("PG_USER", "actionproof")
PASSWORD = os.environ.get("PG_PASSWORD", "actionproof-dev")
DB = os.environ.get("PG_DB", "actionproof")


def _bin(name: str) -> str:
    return str(Path(PG_BIN) / name) if PG_BIN else name


def _running() -> bool:
    if not (DATA / "PG_VERSION").exists():
        return False
    return subprocess.run([_bin("pg_ctl"), "status", "-D", str(DATA)], capture_output=True).returncode == 0


def _initdb() -> None:
    fd, pwfile = tempfile.mkstemp()
    try:
        with os.fdopen(fd, "w") as f:
            f.write(PASSWORD)
        subprocess.run([_bin("initdb"), "-D", str(DATA), "-U", USER, "--auth=scram-sha-256",
                        f"--pwfile={pwfile}", "-E", "UTF8", "--locale=C"], check=True, stdout=subprocess.DEVNULL)
    finally:
        os.unlink(pwfile)


def _ensure_db_and_schema() -> None:
    import psycopg

    from actionproof import db

    base = f"postgresql://{USER}:{PASSWORD}@localhost:{PORT}"
    with psycopg.connect(f"{base}/postgres", autocommit=True, connect_timeout=5) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,)).fetchone():
            c.execute(f'CREATE DATABASE "{DB}"')
    with db.connect(url=f"{base}/{DB}") as c:
        db.apply_schema(c)


def start() -> None:
    if not (DATA / "PG_VERSION").exists():
        _initdb()
    if not _running():
        # Output goes to the log file; never capture pipes (the postmaster would inherit them).
        subprocess.run([_bin("pg_ctl"), "start", "-w", "-D", str(DATA), "-l", str(DATA / "server.log"),
                        "-o", f"-p {PORT} -c listen_addresses=localhost"],
                       check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _ensure_db_and_schema()
    print(f"postgres running on localhost:{PORT}, db {DB}, schema applied")


def stop() -> None:
    if _running():
        subprocess.run([_bin("pg_ctl"), "stop", "-w", "-m", "fast", "-D", str(DATA)], check=True,
                       stdout=subprocess.DEVNULL)
    print("postgres stopped")


def status() -> int:
    up = _running()
    print(f"postgres {'running' if up else 'stopped'} (data {DATA}, port {PORT})")
    return 0 if up else 1


def reset() -> None:
    stop()
    shutil.rmtree(DATA, ignore_errors=True)
    start()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    actions = {"start": start, "stop": stop, "status": status, "reset": reset}
    if cmd not in actions:
        sys.exit(f"usage: python {Path(__file__).name} start|stop|status|reset")
    sys.exit(actions[cmd]() or 0)
