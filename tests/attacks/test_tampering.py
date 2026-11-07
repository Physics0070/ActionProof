"""Attack S6.2 argument tampering: the request is hash-bound to the receipt -> AP-HASH-08 / G2; an edited receipt
fails its signature -> AP-SIG-09 / G2."""
import copy

from gatekit import rules


def _ready(kit):
    req, docs = kit.json_request("INV-8801", "100.00")
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW"
    return req, r.receipt


def test_amount_edited_after_prepare(kit):
    req, receipt = _ready(kit)
    d = req.model_dump(mode="json")
    d["args"]["amount"]["value"] = "99.00"
    c = kit.gate.commit(receipt, d)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-HASH-08", "G2")]
    assert kit.tool.calls == []


def test_target_swapped_after_prepare(kit):
    req, receipt = _ready(kit)
    d = req.model_dump(mode="json")
    d["args"]["invoice_id"]["value"] = "INV-2048"
    assert rules(kit.gate.commit(receipt, d)) == ["AP-HASH-08"] and kit.tool.calls == []


def test_argument_added_after_prepare(kit):
    req, receipt = _ready(kit)
    d = req.model_dump(mode="json")
    d["args"]["note"] = {"value": "pay twice", "claim": "ASSERTED", "taint": "doc"}
    assert rules(kit.gate.commit(receipt, d)) == ["AP-HASH-08"] and kit.tool.calls == []


def test_receipt_payload_edited(kit):
    req, receipt = _ready(kit)
    bad = copy.deepcopy(receipt)
    bad["payload"]["request_hash"] = "0" * 64
    assert [(x.rule, x.guarantee) for x in kit.gate.commit(bad, req).reasons] == [("AP-SIG-09", "G2")]
    assert kit.tool.calls == []


def test_receipt_with_extra_field(kit):
    req, receipt = _ready(kit)
    bad = copy.deepcopy(receipt)
    bad["payload"]["approved_by"] = "ceo"
    assert rules(kit.gate.commit(bad, req)) == ["AP-SIG-09"] and kit.tool.calls == []
