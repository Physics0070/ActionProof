"""Phase 1 gate: the dev infrastructure is reachable."""
import os

import httpx
import psycopg
import pytest

pytestmark = pytest.mark.infra
DB = os.environ.get("DATABASE_URL", "postgresql://actionproof:actionproof-dev@localhost:5433/actionproof")
OPA = os.environ.get("OPA_URL", "http://localhost:8181")


def test_postgres_reachable():
    with psycopg.connect(DB, connect_timeout=5) as c:
        assert c.execute("select 1").fetchone() == (1,)


def test_opa_reachable_and_default_denies():
    assert httpx.get(f"{OPA}/health", timeout=5).status_code == 200
    r = httpx.post(f"{OPA}/v1/data/actionproof/decision", json={"input": {}}, timeout=5)
    assert r.json()["result"]["outcome"] == "DENY"
