"""USP G1/G2 (ADR-027): audited directory administration; a role change cannot let an old approval bypass AP-SEP-12.

Real Postgres. Admin path: only an authenticated admin changes the directory; admin gains no reviewer rights.
"""
import pytest
from gatekit import rules

from actionproof import directory
from actionproof.gate import ReviewRefused


def _prep(kit, inv="INV-9001"):
    req, docs = kit.json_request(inv, "4800.00", "4300.00")
    return kit.gate.prepare(req, docs).receipt, req


def test_admin_change_is_audited_with_before_and_after(kit):
    out = directory.change(kit.db, "admin-ops", "rev-bob", "p-bob", ["reviewer"], disabled=True)
    assert out["before"]["disabled"] is False and out["after"]["disabled"] is True
    d = kit.sql("SELECT detail FROM audit_log WHERE kind = 'directory_change'")[0][0]
    assert d["changed_by"] == "admin-ops" and d["login"] == "rev-bob" and d["before"] == out["before"]


@pytest.mark.parametrize("who", ["rev-alice", "agent-7", "nobody"])
def test_only_an_admin_may_change_the_directory(kit, who):
    with pytest.raises(directory.DirectoryRefused):
        directory.change(kit.db, who, "rev-bob", "p-bob", ["reviewer", "admin"])
    assert kit.sql("SELECT roles FROM people WHERE login = 'rev-bob'") == [(["reviewer"],)]
    assert kit.sql("SELECT count(*) FROM audit_log WHERE kind = 'directory_change'") == [(0,)]


def test_admin_cannot_grant_self_reviewer_and_has_no_implicit_reviewer(kit):
    with pytest.raises(directory.DirectoryRefused):
        directory.change(kit.db, "admin-ops", "admin-ops", "p-ops", ["admin", "reviewer"])
    receipt, req = _prep(kit)
    with pytest.raises(ReviewRefused) as e:
        kit.mint(receipt, req, reviewer_login="admin-ops")
    assert e.value.reason.rule == "AP-SEP-12"


@pytest.mark.parametrize("roles", [["root"], ["reviewer", "x"], "reviewer"])
def test_invalid_roles_refused(kit, roles):
    with pytest.raises((directory.DirectoryRefused, TypeError)):
        directory.change(kit.db, "admin-ops", "rev-bob", "p-bob", roles)


def test_role_revoked_after_mint_blocks_the_old_token(kit):
    receipt, req = _prep(kit, "INV-9002")
    token = kit.mint(receipt, req)
    directory.change(kit.db, "admin-ops", "rev-alice", "p-alice", [])  # reviewer role revoked after the mint
    c = kit.gate.commit(receipt, req, review_token=token)
    assert rules(c) == ["AP-SEP-12"] and c.outcome != "EXECUTED" and kit.tool.calls == []
    assert kit.sql("SELECT used_at FROM review_tokens") == [(None,)]  # denied commit does not burn the token
    directory.change(kit.db, "admin-ops", "rev-alice", "p-alice", ["reviewer"])  # restored: the same token works once
    assert kit.gate.commit(receipt, req, review_token=token).outcome == "EXECUTED"


def test_disabled_reviewer_cannot_mint_or_approve(kit):
    receipt, req = _prep(kit, "INV-9003")
    token = kit.mint(receipt, req)
    directory.change(kit.db, "admin-ops", "rev-alice", "p-alice", ["reviewer"], disabled=True)
    assert rules(kit.gate.commit(receipt, req, review_token=token)) == ["AP-SEP-12"]
    with pytest.raises(ReviewRefused):
        kit.mint(receipt, req)
    assert kit.tool.calls == []
