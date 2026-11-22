"""USP G1 (ADR-026): agent credentials expire, can be revoked/rotated, and are scoped to registry tools.

Scope is checked before the Gate sees the call; identity is the credential's, never a request field. Real Postgres.
"""
import pytest
from mcpkit import app_for, body, call

from actionproof import credentials, db, server
from actionproof.gate import REFUND_TOOL, TOOL

OLD_TABLE = """
    DROP TABLE api_clients;
    CREATE TABLE api_clients (token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'), actor text NOT NULL,
        on_behalf_of text NOT NULL, created_at bigint NOT NULL CHECK (created_at >= 0));
"""


def _principal(kit, token, now=None):
    return server.bearer_principal(kit.factory, f"Bearer {token}", now)


def _issue(kit, scopes=(TOOL, REFUND_TOOL), ttl=30, **kw):
    return credentials.issue(kit.db, "agent-7", "user-123", scopes, label="t", issuer="admin-ops", ttl_days=ttl, **kw)


def test_issue_stores_digest_only_and_listing_has_no_secret(kit):
    cid, token = _issue(kit)
    assert kit.sql("SELECT count(*) FROM api_clients WHERE token_hash = %s", (token,)) == [(0,)]
    rows = credentials.list_credentials(kit.db)
    assert [r["cred_id"] for r in rows] == [cid] and token not in repr(rows) and "token_hash" not in rows[0]
    assert _principal(kit, token).scopes == frozenset({TOOL, REFUND_TOOL})
    assert kit.sql("SELECT kind FROM audit_log WHERE kind = 'credential_issued'") == [("credential_issued",)]
    assert token not in repr(kit.sql("SELECT * FROM audit_log"))


def test_expired_and_revoked_credentials_are_rejected(kit):
    cid, token = _issue(kit, ttl=1)
    assert _principal(kit, token) is not None
    assert _principal(kit, token, now=10**11) is None  # past expiry
    assert credentials.revoke(kit.db, cid, "admin-ops") and _principal(kit, token) is None
    assert not credentials.revoke(kit.db, cid, "admin-ops")  # idempotent
    assert kit.sql("SELECT kind, detail->>'revoked_by' FROM audit_log WHERE kind = 'credential_revoked'") == \
        [("credential_revoked", "admin-ops")]


def test_rotation_revokes_the_old_credential_and_keeps_scopes(kit):
    cid, old = _issue(kit, scopes=(REFUND_TOOL,))
    new_id, new = credentials.rotate(kit.db, cid, "admin-ops")
    assert new_id != cid and _principal(kit, old) is None
    assert _principal(kit, new).scopes == frozenset({REFUND_TOOL})
    with pytest.raises(ValueError):
        credentials.rotate(kit.db, cid, "admin-ops")  # already revoked


def test_scope_blocks_the_other_tool_before_the_gate(kit):
    _, token = _issue(kit, scopes=(REFUND_TOOL,))
    p = _principal(kit, token)
    req, _ = kit.json_request("INV-8001", "100.00")
    _, s, _ = call(app_for(kit), "payments_approve_invoice", body(req), p)
    assert s["status"] == "refused" and s["reasons"][0]["rule"] == "AP-SCOPE-02" and s["reasons"][0]["guarantee"] == "G1"
    assert kit.tool.calls == [] and kit.sql("SELECT count(*) FROM audit_log WHERE kind IN ('prepare','commit')") == [(0,)]
    _, ok, _ = call(app_for(kit), "extract_fields", {"doc_id": "nope"}, p)  # read-only tools need only a valid credential
    assert ok["status"] != "refused" or ok["reasons"][0]["rule"] != "AP-SCOPE-02"


@pytest.mark.parametrize("scopes,ttl", [(("*",), 30), ((), 30), (("payments.nope",), 30), ((TOOL,), 0), ((TOOL,), 9999)])
def test_issue_rejects_wildcards_empty_unknown_scopes_and_bad_ttl(kit, scopes, ttl):
    with pytest.raises(ValueError):
        _issue(kit, scopes=scopes, ttl=ttl)
    assert kit.sql("SELECT count(*) FROM api_clients") == [(0,)]


def test_legacy_credentials_migrate_with_scopes_and_an_expiry(kit):
    kit.db.execute(OLD_TABLE)
    kit.db.commit()
    kit.sql("INSERT INTO api_clients VALUES (%s, 'agent-7', 'user-123', 1)", (server.token_hash("legacy-token-123456"),))
    db.apply_schema(kit.db)
    kit.db.commit()
    p = _principal(kit, "legacy-token-123456")
    assert p.scopes == frozenset({TOOL, REFUND_TOOL}) and p.cred_id.startswith("legacy-")
    exp = kit.sql("SELECT expires_at - extract(epoch FROM now())::bigint FROM api_clients")[0][0]
    assert 0 < exp <= 2592000 + 5  # never permanently valid
    assert _principal(kit, "legacy-token-123456", now=10**11) is None
