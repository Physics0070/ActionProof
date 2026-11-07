"""USP G2: no approval can be replayed (invariant 5).

Receipts, idempotency keys and review tokens are single-use (DB UNIQUE / atomic consume), expire, and bind to
the request hash and record version.
"""
from gatekit import rules


def _prep(kit, req, docs):
    r = kit.gate.prepare(req, docs)
    assert r.receipt is not None, r.reasons
    return r.receipt


def test_replayed_receipt_denied(kit):
    """USP G2: the same receipt committed twice executes once; the replay is AP-REP-05."""
    req, docs = kit.json_request("INV-6001", "100.00")
    receipt = _prep(kit, req, docs)
    assert kit.gate.commit(receipt, req).outcome == "EXECUTED"
    c = kit.gate.commit(receipt, req)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-REP-05", "G2")]
    assert len(kit.tool.calls) == 1 and kit.executes == 1 and kit.commits() == 1


def test_reused_idempotency_key_new_receipt_denied(kit):
    """USP G2: a second receipt (new nonce) for the same idempotency key is AP-REP-05."""
    req, docs = kit.json_request("INV-6002", "100.00")
    first, second = _prep(kit, req, docs), _prep(kit, req, docs)
    assert first["payload"]["nonce"] != second["payload"]["nonce"]
    assert kit.gate.commit(first, req).outcome == "EXECUTED"
    assert rules(kit.gate.commit(second, req)) == ["AP-REP-05"]
    assert len(kit.tool.calls) == 1


def test_reused_idempotency_key_other_invoice_denied(kit):
    """USP G2: the idempotency key is global, not per invoice."""
    a, da = kit.json_request("INV-6003", "100.00", idem="shared-key")
    b, db = kit.json_request("INV-6004", "100.00", idem="shared-key")
    ra, rb = _prep(kit, a, da), _prep(kit, b, db)
    assert kit.gate.commit(ra, a).outcome == "EXECUTED"
    assert rules(kit.gate.commit(rb, b)) == ["AP-REP-05"]
    assert len(kit.tool.calls) == 1


def test_review_token_bound_to_request_hash(kit):
    """USP G2: a review token minted for request A cannot approve request B (AP-REV-10)."""
    a, da = kit.json_request("INV-6005", "4800.00", "4300.00")
    b, db = kit.json_request("INV-6006", "4800.00", "4300.00")
    ra, rb = _prep(kit, a, da), _prep(kit, b, db)
    assert ra["payload"]["decision"] == rb["payload"]["decision"] == "REVIEW"
    token = kit.mint(a)
    c = kit.gate.commit(rb, b, review_token=token)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-REV-10", "G2")]
    assert kit.tool.calls == []
    assert kit.gate.commit(ra, a, review_token=token).outcome == "EXECUTED"  # still valid for A


def test_review_token_single_use(kit):
    """USP G2: a used review token cannot approve the same request again (AP-REP-05)."""
    req, docs = kit.json_request("INV-6007", "4800.00", "4300.00")
    first, second = _prep(kit, req, docs), _prep(kit, req, docs)
    token = kit.mint(req)
    assert kit.gate.commit(first, req, review_token=token).outcome == "EXECUTED"
    c = kit.gate.commit(second, req, review_token=token)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-REP-05", "G2")]
    assert len(kit.tool.calls) == 1


def test_expired_review_token_denied(kit):
    """USP G2: an expired review token is AP-EXP-06 and stays unused."""
    req, docs = kit.json_request("INV-6008", "4800.00", "4300.00")
    receipt = _prep(kit, req, docs)
    token = kit.mint(req)
    kit.sql("UPDATE review_tokens SET exp = minted_at - 1")
    c = kit.gate.commit(receipt, req, review_token=token)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-EXP-06", "G2")]
    assert kit.tool.calls == []
    assert kit.sql("SELECT used_at FROM review_tokens") == [(None,)]


def test_denied_commit_does_not_burn_token(kit):
    """USP G2: a token is consumed only by a commit that executes (atomic with the write)."""
    req, docs = kit.json_request("INV-6009", "4800.00", "4300.00")
    receipt = _prep(kit, req, docs)
    token = kit.mint(req)
    kit.sql("UPDATE records SET version = version + 1 WHERE record_id = 'invoice:INV-6009'")
    assert rules(kit.gate.commit(receipt, req, review_token=token)) == ["AP-STALE-07"]
    assert kit.sql("SELECT used_at FROM review_tokens") == [(None,)]


def test_receipt_bound_to_record_version(kit):
    """USP G2: after a commit the record version moves, so an older receipt for it can never apply."""
    a, da = kit.json_request("INV-6010", "100.00", idem="k-a")
    b, db = kit.json_request("INV-6010", "100.00", idem="k-b", seed=False)
    ra, rb = _prep(kit, a, da), _prep(kit, b, db)
    assert kit.gate.commit(ra, a).outcome == "EXECUTED"
    assert rules(kit.gate.commit(rb, b)) == ["AP-STALE-07"]
    assert len(kit.tool.calls) == 1
