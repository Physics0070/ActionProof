"""Seed one HTTP API client (ADR-012): python scripts/seed_api_client.py --actor agent-7 --on-behalf-of user-123

Generates a random bearer token, stores ONLY sha256(token) in api_clients with the Principal it maps to, and prints
the token once (it cannot be recovered later). DATABASE_URL comes from the environment (invariant 7).
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from actionproof import credentials, db  # noqa: E402


def seed(conn, actor: str, on_behalf_of: str, scopes=credentials.KNOWN_SCOPES, ttl_days: int = 30) -> str:
    """Issue a credential (ADR-026: scoped, expiring, audited) and return its token. Shown once, never stored."""
    return credentials.issue(conn, actor, on_behalf_of, scopes, label="seed script", issuer="seed-script",
                             ttl_days=ttl_days)[1]


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
