"""Red team (Phase 5), G2: reviewer separation of duties by directory person (ADR-008, AP-SEP-12).

A REVIEW is a human approval; if the approver is the same person who asked, the request approves itself.
Every assertion encodes the SAFE behavior. A failing test here is a finding.
"""
import copy
import logging

import pytest
from gatekit import AGENT, rules

from actionproof.gate import Principal, ReviewRefused

SEP = ("AP-SEP-12", "G2")


def _review(kit, inv, principal=AGENT, **kw):
    req, docs = kit.json_request(inv, "1000.00", "500.00", idem=f"sep-{inv}", **kw)
    p = kit.gate.prepare(req, docs, principal=principal)
    assert p.decision == "REVIEW", p.reasons
    return req, p.receipt


def _person(kit, login, person, roles):
    kit.sql("INSERT INTO people (login, person_id, roles) VALUES (%s, %s, %s)", (login, person, list(roles)))


def _refused(kit, receipt, req, login) -> tuple[str, str]:
    with pytest.raises(ReviewRefused) as e:
        kit.gate.mint_review_token(receipt, req, reviewer_login=login)
    assert kit.sql("SELECT count(*) FROM review_tokens") == [(0,)], "a refused mint stored a token"
    return e.value.reason.rule, e.value.reason.guarantee


def _forged_token(kit, receipt, login, person) -> str:
    """A token that reached the table without the console's mint check (another path, or an old row)."""
    kit.sql("INSERT INTO review_tokens (token, request_hash, submitter, minted_by, minted_by_person, minted_at, exp) "
            "VALUES ('forged', %s, 'agent-7', %s, %s, 1, %s)",
            (receipt["payload"]["request_hash"], login, person, receipt["payload"]["exp"]))
    return "forged"


def _denied_at_commit(kit, receipt, req, token, principal=AGENT):
    c = kit.gate.commit(receipt, req, review_token=token, principal=principal)
    assert c.outcome == "DENY" and [(r.rule, r.guarantee) for r in c.reasons] == [SEP], c.reasons
    assert kit.tool.calls == [] and kit.executes == 0 and kit.commits() == 0
    assert kit.sql("SELECT used_at FROM review_tokens") == [(None,)], "a denied commit consumed the token"


def test_second_login_of_submitter_cannot_mint(kit, caplog):
    """rev-user123 is a reviewer login of the same human (p-user123) who runs agent-7 for user-123."""
    _person(kit, "rev-user123", "p-user123", ["reviewer"])
    req, receipt = _review(kit, "INV-SEP1")
    with caplog.at_level(logging.WARNING, logger="actionproof.audit"):
        assert _refused(kit, receipt, req, "rev-user123") == SEP
    assert any("AP-SEP-12" in r.getMessage() and "rev-user123" in r.getMessage() for r in caplog.records)


def test_second_login_token_denied_at_commit(kit):
    _person(kit, "rev-user123", "p-user123", ["reviewer"])
    req, receipt = _review(kit, "INV-SEP2")
    _denied_at_commit(kit, receipt, req, _forged_token(kit, receipt, "rev-user123", "p-user123"))


def test_unmapped_reviewer_login_refused(kit):
    req, receipt = _review(kit, "INV-SEP3")
    assert _refused(kit, receipt, req, "rev-mallory") == SEP
    _denied_at_commit(kit, receipt, req, _forged_token(kit, receipt, "rev-mallory", "p-mallory"))


def test_unmapped_submitter_refused(kit):
    """A missing directory row for the agent fails closed; it never means 'nobody, so anyone may approve'."""
    req, receipt = _review(kit, "INV-SEP4")
    kit.sql("DELETE FROM people WHERE login = 'agent-7'")
    assert _refused(kit, receipt, req, "rev-alice") == SEP


def test_admin_cannot_mint(kit):
    req, receipt = _review(kit, "INV-SEP5")
    assert _refused(kit, receipt, req, "admin-ops") == SEP
    _denied_at_commit(kit, receipt, req, _forged_token(kit, receipt, "admin-ops", "p-ops"))


def test_directory_edit_after_mint_denied_at_commit(kit):
    """Token minted legitimately by rev-alice; the directory then maps rev-alice to the submitter's person."""
    req, receipt = _review(kit, "INV-SEP6")
    token = kit.gate.mint_review_token(receipt, req, reviewer_login="rev-alice")
    kit.sql("UPDATE people SET person_id = 'p-user123' WHERE login = 'rev-alice'")
    _denied_at_commit(kit, receipt, req, token)
    kit.sql("UPDATE people SET person_id = 'p-alice' WHERE login = 'rev-alice'")
    assert kit.gate.commit(receipt, req, review_token=token).outcome == "EXECUTED"  # the DENY rolled back


def test_reviewer_role_revoked_after_mint_denied_at_commit(kit):
    req, receipt = _review(kit, "INV-SEP7")
    token = kit.gate.mint_review_token(receipt, req, reviewer_login="rev-bob")
    kit.sql("UPDATE people SET roles = '{}' WHERE login = 'rev-bob'")
    _denied_at_commit(kit, receipt, req, token)


def test_team_on_behalf_of_denied(kit):
    """A team is not a single person, so 'reviewer is a different person' cannot be stated: DENY."""
    _person(kit, "team-ap", "team-ap", ["team"])
    kit.sql("INSERT INTO delegations (on_behalf_of, max_amount, vendors) VALUES ('team-ap', 5000.00, '{V-ACME}')")
    team = Principal("agent-7", "team-ap")
    req, receipt = _review(kit, "INV-SEP8", principal=team, on_behalf_of="team-ap")
    assert _refused(kit, receipt, req, "rev-alice") == SEP
    _denied_at_commit(kit, receipt, req, _forged_token(kit, receipt, "rev-alice", "p-alice"), principal=team)


def test_different_person_mints_and_commits(kit):
    req, receipt = _review(kit, "INV-SEP9")
    token = kit.gate.mint_review_token(receipt, req, reviewer_login="rev-alice")
    assert kit.sql("SELECT minted_by, minted_by_person, submitter FROM review_tokens") == \
        [("rev-alice", "p-alice", "agent-7")]
    assert kit.gate.commit(receipt, req, review_token=token).outcome == "EXECUTED"


def test_mint_checks_the_receipt(kit):
    """The submitter is read from a receipt the gate signed for exactly this request, and only a REVIEW mints."""
    req, receipt = _review(kit, "INV-SEPA")
    forged = copy.deepcopy(receipt)
    forged["payload"]["actor"] = "agent-8"
    assert _refused(kit, forged, req, "rev-alice") == ("AP-SIG-09", "G2")
    other, _ = kit.json_request("INV-SEPB", "1000.00", "500.00", idem="sep-other")
    assert _refused(kit, receipt, other, "rev-alice") == ("AP-HASH-08", "G2")
    areq, adocs = kit.json_request("INV-SEPC", "100.00", idem="sep-allow")
    allow = kit.gate.prepare(areq, adocs).receipt
    assert allow["payload"]["decision"] == "ALLOW"
    assert _refused(kit, allow, areq, "rev-alice") == ("AP-REV-10", "G2")
    assert rules(kit.gate.commit(allow, areq)) == []  # untouched: the ALLOW still commits
