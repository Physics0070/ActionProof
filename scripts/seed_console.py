"""Seed the dev console users: python scripts/seed_console.py

Users: rev-alice, rev-bob (reviewer), sub-user123 (submitter), admin-ops (admin); roles live in `people`
(db.PEOPLE, upserted here). Each password comes from env CONSOLE_PASSWORD_<LOGIN> (dashes as underscores, e.g.
CONSOLE_PASSWORD_REV_ALICE) or is generated; generated ones are printed ONCE to stdout and never stored anywhere
but as an argon2id hash. Never commit a password. DATABASE_URL comes from the environment (invariant 7).
"""
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from actionproof import console, db  # noqa: E402

LOGINS = ("rev-alice", "rev-bob", "sub-user123", "admin-ops")


def env_name(login: str) -> str:
    return "CONSOLE_PASSWORD_" + login.upper().replace("-", "_")


def seed(conn, env=os.environ) -> dict[str, str]:
    """Upsert the directory and the four users. Returns {login: password} for the GENERATED passwords only."""
    for login, person, roles in db.PEOPLE:
        conn.execute("INSERT INTO people (login, person_id, roles) VALUES (%s, %s, %s) "
                     "ON CONFLICT (login) DO UPDATE SET person_id = EXCLUDED.person_id, roles = EXCLUDED.roles",
                     (login, person, list(roles)))
    generated = {}
    for login in LOGINS:
        pw = env.get(env_name(login))
        if not pw:
            pw = generated[login] = secrets.token_urlsafe(18)
        console.set_password(conn, login, pw)
    conn.commit()
    return generated


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    with db.connect(url=url) as conn:
        db.apply_schema(conn)
        generated = seed(conn)
    for login in LOGINS:
        print(f"{login}: {generated[login]}" if login in generated else f"{login}: (from {env_name(login)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
