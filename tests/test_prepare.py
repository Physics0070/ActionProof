"""gate.prepare: verify -> SoR -> policy -> dry-run diff -> signed receipt (ALLOW/REVIEW only)."""
from gatekit import HERO_DOCS, rules

from actionproof import gate as gate_mod
from actionproof import signing
from actionproof.contracts import request_hash

SLIDE_1 = """ACTION INTERCEPTED
action: approve_invoice
amount: 4800.00 [DIRECT ok]
variance: 500.00 [DERIVED ok]
rule: AP-INV-04 (> 100)
decision: REVIEW"""


def test_hero_review_signed_and_card(kit):
    req, docs = kit.hero()
    r = kit.gate.prepare(req, docs)
    assert r.decision == "REVIEW"
    assert [(x.rule, x.guarantee) for x in r.reasons] == [("AP-INV-04", "G1")]
    assert r.verify.ok
    assert signing.verify(r.receipt, kit.signer.public_key_b64())
    p = r.receipt["payload"]
    assert set(p) == gate_mod.PAYLOAD_KEYS
    assert p["decision"] == "REVIEW" and p["request_hash"] == request_hash(req)
    assert p["record_id"] == "invoice:INV-2048" and p["version"] == 1
    assert p["tool"] == "payments.approve_invoice" and p["actor"] == "agent-7" and p["on_behalf_of"] == "user-123"
    assert p["idempotency_key"] == "idem-1"
    assert r.diff == {"record_id": "invoice:INV-2048", "status": "open->approved", "amount": "4800.00"}
    assert r.card() == SLIDE_1  # S1.1
    assert kit.tool.calls == []


def test_variance_50_allows(kit):
    req, docs = kit.hero_allow()
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW" and r.reasons == []
    assert r.receipt["payload"]["decision"] == "ALLOW"
    assert "rule: none" in r.card()


def test_amount_claim_not_in_span_denied(kit):
    d = kit.hero()[0].model_dump(mode="json")
    d["args"]["amount"]["value"] = "4900.00"
    r = kit.gate.prepare(d, HERO_DOCS)
    assert r.decision == "DENY" and r.receipt is None
    assert set(rules(r)) == {"AP-VER-01"} and all(x.guarantee == "G1" for x in r.reasons)
    assert "amount: 4900.00 [DIRECT FAILED]" in r.card()
    assert "rule: AP-VER-01 [G1]" in r.card()


def test_scope_exceeded_denied(kit):
    kit.set_scope("1000.00")
    r = kit.gate.prepare(*kit.hero())
    assert r.decision == "DENY" and r.receipt is None
    assert rules(r) == ["AP-SCOPE-02"]


def test_unknown_tool_denied(kit):
    d = kit.hero()[0].model_dump(mode="json")
    d["tool"] = "payments.wire_transfer"
    r = kit.gate.prepare(d, HERO_DOCS)
    assert r.decision == "DENY" and r.receipt is None and rules(r) == ["AP-VER-01"]


def test_opa_down_denied(kit, monkeypatch):
    with __import__("socket").socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("OPA_URL", f"http://127.0.0.1:{port}")
    r = kit.gate.prepare(*kit.hero())
    assert r.decision == "DENY" and r.receipt is None and rules(r) == ["AP-POL-FAIL"]


def test_deny_has_no_receipt_and_no_diff(kit):
    r = kit.gate.prepare(*kit.json_request("INV-9001", "5200.00"))  # over scope max
    assert r.decision == "DENY" and r.receipt is None and r.diff is None


def test_missing_invoice_id_denied(kit):
    d = kit.hero()[0].model_dump(mode="json")
    del d["args"]["invoice_id"]
    r = kit.gate.prepare(d, HERO_DOCS)
    assert r.decision == "DENY" and rules(r) == ["AP-VER-01"]


def test_unknown_invoice_denied(kit):
    r = kit.gate.prepare(*kit.json_request("INV-404", "100.00", seed=False))
    assert r.decision == "DENY" and rules(r) == ["AP-VER-01"]


def test_self_made_document_must_agree_with_records(kit):
    """A document the agent wrote proves only that it says 4.00; the record says 4800.00 -> G1 DENY."""
    kit.seed_invoice("INV-7001", "4800.00", "4800.00")
    req, docs = kit.json_request("INV-7001", "4.00", "4.00", seed=False)
    r = kit.gate.prepare(req, docs)
    assert r.verify.claims["amount"].ok  # the doc really says 4.00 ...
    assert r.decision == "DENY" and "AP-VER-01" in rules(r)  # ... but the system of record disagrees


def test_already_approved_record_denied(kit):
    kit.sql("UPDATE records SET data = data || '{\"status\": \"approved\"}'::jsonb WHERE record_id = 'invoice:INV-2048'")
    r = kit.gate.prepare(*kit.hero())
    assert r.decision == "DENY" and r.receipt is None and "AP-STALE-07" in rules(r)


def test_no_delegation_is_out_of_scope(kit):
    req, docs = kit.json_request("INV-9002", "100.00", on_behalf_of="user-nobody")
    r = kit.gate.prepare(req, docs)
    assert r.decision == "DENY" and set(rules(r)) == {"AP-SCOPE-02"}  # amount AND vendor out of the empty scope


def test_cumulative_advisory_at_prepare(kit):
    kit.sql("INSERT INTO commits (nonce, idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount, record_id,"
            " created_at) VALUES ('n0', 'k0', 'h', 'agent-7', 'user-123', 'V-ACME', 4900.00, 'invoice:X', 0)")
    r = kit.gate.prepare(*kit.json_request("INV-9003", "200.00"))
    assert r.decision == "DENY" and rules(r) == ["AP-CUM-03"]


def test_docs_provider_used_when_docs_omitted(kit):
    from actionproof.gate import Gate

    req, docs = kit.json_request("INV-9004", "100.00")
    seen = []
    g = Gate(kit.settings, kit.signer, kit.factory, kit.tool, docs_provider=lambda r: seen.append(r) or docs)
    assert g.prepare(req).decision == "ALLOW" and seen == [req]
    assert kit.gate.prepare(req).decision == "DENY"  # no provider, no docs: DIRECT claims cannot verify


def test_garbage_request_and_exceptions_fail_closed(kit, monkeypatch):
    assert kit.gate.prepare({"tool": 1}, {}).decision == "DENY"
    assert kit.gate.prepare(None, None).decision == "DENY"

    def boom(_):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(kit.tool, "dry_run", boom)
    r = kit.gate.prepare(*kit.hero_allow())
    assert r.decision == "DENY" and rules(r) == ["AP-ERR-11"] and r.receipt is None
    assert "secret detail" not in r.reasons[0].msg
