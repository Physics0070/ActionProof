"""Apply the schema (idempotent): python scripts/apply_schema.py. DATABASE_URL from the environment (invariant 7)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import psycopg  # noqa: E402

from actionproof import db  # noqa: E402

if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set")
    with psycopg.connect(url, connect_timeout=10) as conn:
        db.apply_schema(conn)
    print("schema applied")
