"""Audited administration of the people directory (ADR-027): person mappings, agent -> operator mappings, reviewer/admin
roles and disabled identities. Called only from the console's admin endpoints (authenticated admin session + CSRF).

Lock order is audit -> people, the same as Gate.commit and Gate.mint_review_token, so a directory edit waits for an
in-flight mint/commit (which hold FOR SHARE on the rows they read) and can never deadlock with them. A change therefore
lands strictly before or strictly after any approval's separation-of-duties check, and a token minted earlier is
re-checked against the CURRENT directory at commit (AP-SEP-12 semantics unchanged). An admin never gains 'reviewer'
implicitly, and cannot grant it to themselves.
"""
import re

from actionproof import audit
from actionproof.contracts import IDENT

ROLES = ("reviewer", "admin", "team", "submitter", "agent")


class DirectoryRefused(Exception):
    pass


def _row(r):
    return None if r is None else {"person_id": r[0], "roles": sorted(r[1]), "disabled": r[2]}


def list_people(conn) -> list[dict]:
    return [{"login": r[0], **_row(r[1:])} for r in conn.execute(
        "SELECT login, person_id, roles, disabled FROM people ORDER BY login").fetchall()]


def change(conn, admin_login: str, login: str, person_id: str, roles, disabled: bool = False) -> dict:
    """Upsert one directory row as `admin_login`. Returns {before, after}. Raises DirectoryRefused (nothing written)."""
    roles = sorted(set(roles))
    if not (isinstance(login, str) and re.match(IDENT, login) and isinstance(person_id, str)
            and re.match(IDENT, person_id)) or not set(roles) <= set(ROLES) or not isinstance(disabled, bool):
        raise DirectoryRefused("invalid login, person_id, roles or disabled flag")
    audit.lock(conn)  # lock order: audit -> people (module docstring)
    rows = {r[0]: r[1:] for r in conn.execute(
        "SELECT login, person_id, roles, disabled FROM people WHERE login = ANY(%s) ORDER BY login FOR UPDATE",
        ([admin_login, login],)).fetchall()}
    admin = rows.get(admin_login)
    if admin is None or "admin" not in admin[1] or admin[2]:
        conn.rollback()
        raise DirectoryRefused("the admin role is required")
    before = _row(rows.get(login))
    if login == admin_login and "reviewer" in roles and (before is None or "reviewer" not in before["roles"]):
        conn.rollback()
        raise DirectoryRefused("an admin cannot grant themselves the reviewer role")
    conn.execute("INSERT INTO people (login, person_id, roles, disabled) VALUES (%s, %s, %s, %s) "
                 "ON CONFLICT (login) DO UPDATE SET person_id = EXCLUDED.person_id, roles = EXCLUDED.roles, "
                 "disabled = EXCLUDED.disabled", (login, person_id, roles, disabled))
    after = {"person_id": person_id, "roles": roles, "disabled": disabled}
    audit.append(conn, "directory_change", detail={"changed_by": admin_login, "login": login, "before": before,
                                                  "after": after})
    conn.commit()
    return {"before": before, "after": after}
