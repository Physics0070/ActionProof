"""Agent credential lifecycle (ADR-026): issue, list, revoke, rotate. Only sha256(token) is stored; the raw token is
returned once. Every issue/revoke is an audit entry in the same transaction (never with the token).

    python -m actionproof.credentials issue --actor agent-7 --on-behalf-of user-123 --scope payments.refund_payment \
        --label ci --issuer admin-ops [--ttl-days 30]
    python -m actionproof.credentials list | revoke CRED_ID --by ADMIN | rotate CRED_ID --by ADMIN

Identity comes from the authenticated transport (this row), never from an ActionRequest field. Scopes are registry tool
names; a call outside them is refused (AP-SCOPE-02) before the Gate sees it. Extension point for OIDC: replace
`server.bearer_principal` with a verifier that returns the same Principal; nothing else changes.
"""
import argparse
import hashlib
import os
import re
import secrets
import sys
import time

from actionproof import audit, db
from actionproof.contracts import IDENT
from actionproof.gate import REFUND_TOOL, TOOL

KNOWN_SCOPES = (TOOL, REFUND_TOOL)  # explicit names only: no wildcard can be issued
MAX_TTL_DAYS = 365


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(conn, actor: str, on_behalf_of: str, scopes, *, label: str = "", issuer: str, ttl_days: int = 30,
          now: int | None = None) -> tuple[str, str]:
    """Insert a credential and return (cred_id, raw token). Raises ValueError on any bad input (fail closed)."""
    for v in (actor, on_behalf_of, issuer):
        if not isinstance(v, str) or not re.match(IDENT, v):
            raise ValueError("actor, on_behalf_of and issuer must be canonical identifiers")
    scopes = sorted(set(scopes))
    if not scopes or not set(scopes) <= set(KNOWN_SCOPES):
        raise ValueError(f"scopes must be a non-empty subset of {list(KNOWN_SCOPES)}")
    if not isinstance(ttl_days, int) or not 0 < ttl_days <= MAX_TTL_DAYS:
        raise ValueError(f"ttl_days must be 1..{MAX_TTL_DAYS}")
    now = int(time.time()) if now is None else now
    token, cred_id = secrets.token_urlsafe(32), "cred-" + secrets.token_hex(6)
    conn.execute("INSERT INTO api_clients (token_hash, actor, on_behalf_of, created_at, cred_id, label, issuer, scopes, "
                 "expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                 (digest(token), actor, on_behalf_of, now, cred_id, label[:80], issuer, scopes, now + ttl_days * 86400))
    audit.append(conn, "credential_issued", actor=actor, on_behalf_of=on_behalf_of,
                 detail={"cred_id": cred_id, "issuer": issuer, "scopes": scopes, "expires_at": now + ttl_days * 86400})
    conn.commit()
    return cred_id, token


def list_credentials(conn) -> list[dict]:
    """Everything except the secret (the digest is not returned either)."""
    cols = ("cred_id", "label", "actor", "on_behalf_of", "scopes", "issuer", "created_at", "expires_at", "revoked_at",
            "last_used_at")
    return [dict(zip(cols, r)) for r in conn.execute(f"SELECT {', '.join(cols)} FROM api_clients ORDER BY created_at, "
                                                     "cred_id").fetchall()]


def revoke(conn, cred_id: str, by: str, now: int | None = None) -> bool:
    """Revoke (idempotent: False if unknown or already revoked). Takes effect on the next call."""
    now = int(time.time()) if now is None else now
    row = conn.execute("UPDATE api_clients SET revoked_at = %s WHERE cred_id = %s AND revoked_at IS NULL "
                       "RETURNING actor, on_behalf_of", (now, cred_id)).fetchone()
    if row:
        audit.append(conn, "credential_revoked", actor=row[0], on_behalf_of=row[1],
                     detail={"cred_id": cred_id, "revoked_by": by})
    conn.commit()
    return row is not None


def rotate(conn, cred_id: str, by: str, ttl_days: int = 30) -> tuple[str, str]:
    """New credential with the same identity and scopes; the old one is revoked. Returns (new cred_id, new token)."""
    old = conn.execute("SELECT actor, on_behalf_of, scopes, label FROM api_clients WHERE cred_id = %s "
                       "AND revoked_at IS NULL", (cred_id,)).fetchone()
    if old is None:
        raise ValueError("unknown or already revoked credential")
    new = issue(conn, old[0], old[1], old[2], label=old[3] or "", issuer=by, ttl_days=ttl_days)
    revoke(conn, cred_id, by)
    return new


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("issue")
    i.add_argument("--actor", required=True)
    i.add_argument("--on-behalf-of", required=True)
    i.add_argument("--scope", action="append", required=True)
    i.add_argument("--label", default="")
    i.add_argument("--issuer", required=True)
    i.add_argument("--ttl-days", type=int, default=30)
    sub.add_parser("list")
    for name in ("revoke", "rotate"):
        p = sub.add_parser(name)
        p.add_argument("cred_id")
        p.add_argument("--by", required=True)
    a = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    with db.connect(url=url) as conn:
        db.apply_schema(conn)
        if a.cmd == "issue":
            cid, tok = issue(conn, a.actor, a.on_behalf_of, a.scope, label=a.label, issuer=a.issuer, ttl_days=a.ttl_days)
            print(f"cred_id={cid}\ntoken={tok}  # shown once")
        elif a.cmd == "list":
            for c in list_credentials(conn):
                print(c)
        elif a.cmd == "revoke":
            print("revoked" if revoke(conn, a.cred_id, a.by) else "not found or already revoked")
        else:
            cid, tok = rotate(conn, a.cred_id, a.by)
            print(f"cred_id={cid}\ntoken={tok}  # shown once; the old credential is revoked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
