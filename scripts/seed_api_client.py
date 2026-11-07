"""Seed one HTTP API client (ADR-012): python scripts/seed_api_client.py --actor agent-7 --on-behalf-of user-123

Generates a random bearer token, stores ONLY sha256(token) in api_clients with the Principal it maps to, and prints
the token once (it cannot be recovered later). DATABASE_URL comes from the environment (invariant 7).
"""
import argparse
import os
import re
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from actionproof import db  # noqa: E402
from actionproof.contracts import IDENT  # noqa: E402
from actionproof.server import token_hash  # noqa: E402


def seed(conn, actor: str, on_behalf_of: str) -> str:
    """Insert a new client and return its token. The caller shows it once and never stores it."""
    for v in (actor, on_behalf_of):
        if not re.match(IDENT, v):
            raise ValueError("actor and on_behalf_of must be canonical identifiers")
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO api_clients (token_hash, actor, on_behalf_of, created_at) VALUES (%s, %s, %s, %s)",
                 (token_hash(token), actor, on_behalf_of, int(time.time())))
    conn.commit()
    return token


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--actor", default="agent-7")
    ap.add_argument("--on-behalf-of", default="user-123")
    args = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    with db.connect(url=url) as conn:
        db.apply_schema(conn)
        token = seed(conn, args.actor, args.on_behalf_of)
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
