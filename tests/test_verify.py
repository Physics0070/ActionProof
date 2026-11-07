import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fixtures"))

from hero import hero_request, hero_sor, json_claim, load_docs, pdf_claim  # noqa: E402

from actionproof import extract  # noqa: E402
from actionproof.contracts import ActionRequest  # noqa: E402
from actionproof.verify import Reason, verify_request  # noqa: E402

DOCS = load_docs()


def req(args: dict, tool: str = "payments.approve_invoice") -> ActionRequest:
    return ActionRequest.model_validate({"tool": tool, "on_behalf_of": "user-123", "actor": "agent-7", "idempotency_key": "k", "args": args})


def hero_args(**over) -> dict:
    a = hero_request().model_dump(mode="json")["args"]
    a.update(over)
    return {k: v for k, v in a.items() if v is not None}


def variance(value="500.00", inputs=("invoice.total", "po.total"), fn="sub"):
    return {"value": value, "claim": "DERIVED", "fn": fn, "inputs": list(inputs)}


def assert_g1(r):
    assert r.ok is False
    assert r.reasons and all(x.rule == "AP-VER-01" and x.guarantee == "G1" for x in r.reasons)


def test_hero_verifies():
    r = verify_request(hero_request(), DOCS, hero_sor())
    assert r.ok, r.reasons
    assert r.reasons == []
    assert r.claims["amount"].ok and r.claims["amount"].claim == "DIRECT" and r.claims["amount"].method == "dual"
    assert r.claims["variance"].ok and r.claims["variance"].claim == "DERIVED" and r.claims["variance"].method == "derived:sub"
    assert r.claims["variance"].value == "500.00"
    assert r.claims["po.total"].method == "json_pointer"
    assert r.claims["note"].ok and r.claims["note"].method == "asserted"


def test_wrong_value_fails():
    r = verify_request(req(hero_args(amount=pdf_claim("invoice.pdf", "total", "4900.00"))), DOCS, hero_sor())
    assert_g1(r)
    assert not r.claims["amount"].ok and "amount" in r.claims["amount"].reason.msg


@pytest.mark.parametrize("text", ["4800", "$4,800.0", "4800.000", "abc"])
def test_extracted_text_needs_two_dp(monkeypatch, text):
    monkeypatch.setattr(extract, "extract_src", lambda doc, src: extract.Extracted(text, "dual"))
    r = verify_request(hero_request(), DOCS, hero_sor())
    assert not r.claims["amount"].ok


def test_direct_money_field_needs_money_format():
    r = verify_request(req(hero_args(amount=pdf_claim("invoice.pdf", "total", "4800"))), DOCS, hero_sor())
    assert_g1(r)
    assert not r.claims["amount"].ok


def test_wrong_box_fails():
    c = pdf_claim("invoice.pdf", "total")
    c["src"]["bbox"] = pdf_claim("invoice.pdf", "invoice_id")["src"]["bbox"]
    r = verify_request(req(hero_args(amount=c)), DOCS, hero_sor())
    assert_g1(r)
    assert not r.claims["amount"].ok


def test_wrong_hash_fails():
    c = pdf_claim("invoice.pdf", "total")
    c["doc_sha256"] = "0" * 64
    r = verify_request(req(hero_args(amount=c)), DOCS, hero_sor())
    assert_g1(r)
    assert "hash" in r.claims["amount"].reason.msg


def test_missing_doc_fails():
    r = verify_request(hero_request(), {}, hero_sor())
    assert_g1(r)


def test_image_only_total_ocr():
    a = {
        "amount": pdf_claim("imageonly.pdf", "total"),
        "invoice.total": pdf_claim("imageonly.pdf", "total"),
        "variance": variance("0.00"),
    }
    r = verify_request(req(a), DOCS, {"po.total": "2450.00"})
    assert r.ok, r.reasons
    assert r.claims["amount"].method == "ocr_image"


def test_hidden_text_box_disagrees():
    c = pdf_claim("injected.pdf", "hidden_text")
    r = verify_request(req(hero_args(note=c)), DOCS, hero_sor())
    assert_g1(r)
    assert not r.claims["note"].ok


def test_monkeypatched_ocr_disagreement(monkeypatch):
    monkeypatch.setattr(extract, "pdf_ocr", lambda *a: "$4,900.00")
    r = verify_request(hero_request(), DOCS, hero_sor())
    assert_g1(r)
    assert not r.claims["amount"].ok and not r.claims["invoice.total"].ok
    assert not r.claims["variance"].ok  # its input did not verify


def test_json_pointer_ok_and_wrong_value():
    assert verify_request(req(hero_args(**{"po.total": json_claim("po.json", "total")})), DOCS, hero_sor()).ok
    r = verify_request(req(hero_args(**{"po.total": json_claim("po.json", "total", "4200.00")})), DOCS, hero_sor())
    assert_g1(r)
    assert not r.claims["po.total"].ok


def test_variance_500_passes_501_fails():
    assert verify_request(req(hero_args(variance=variance("500.00"))), DOCS, hero_sor()).ok
    r = verify_request(req(hero_args(variance=variance("501.00"))), DOCS, hero_sor())
    assert_g1(r)
    assert not r.claims["variance"].ok and r.claims["amount"].ok


def test_derived_from_sor_when_no_arg():
    a = hero_args(**{"po.total": None})
    assert verify_request(req(a), DOCS, hero_sor()).ok
    assert_g1(verify_request(req(a), DOCS, {}))  # unresolvable input


def test_derived_arity_and_cycles():
    assert_g1(verify_request(req(hero_args(variance=variance(inputs=["invoice.total"]))), DOCS, hero_sor()))
    assert_g1(verify_request(req(hero_args(variance=variance(inputs=["variance", "po.total"]))), DOCS, hero_sor()))
    a = hero_args(variance=variance(inputs=["x", "po.total"]), x=variance("500.00", inputs=["variance", "po.total"]))
    assert_g1(verify_request(req(a), DOCS, hero_sor()))
    # ADR-013: variance is pinned to sub(invoice.total, po.total); a self-consistent sum no longer verifies.
    a = hero_args(variance=variance("9100.00", fn="sum", inputs=["invoice.total", "po.total"]))
    assert_g1(verify_request(req(a), DOCS, hero_sor()))


def test_variance_pinned_and_asserted_never_an_input():
    """ADR-013: other inputs, a DIRECT variance, or an ASSERTED input all fail, even when the arithmetic holds."""
    for inputs in (["invoice.total", "invoice.total"], ["amount", "invoice.total"], ["po.total", "po.total"],
                   ["po.total", "invoice.total"]):
        assert_g1(verify_request(req(hero_args(variance=variance("0.00", inputs=inputs))), DOCS, hero_sor()))
    a = hero_args(note={"value": "4800.00", "claim": "ASSERTED"},
                  variance=variance("0.00", inputs=["invoice.total", "note"]))
    assert_g1(verify_request(req(a), DOCS, hero_sor()))
    a = hero_args(**{"po.total": {"value": "4300.00", "claim": "ASSERTED"}})
    r = verify_request(req(a), DOCS, hero_sor())
    assert_g1(r)
    assert "ASSERTED" in r.claims["variance"].reason.msg
    a = hero_args(variance=json_claim("po.json", "total"))  # a DIRECT variance (any cited doc)
    assert_g1(verify_request(req(a), DOCS, hero_sor()))


def test_unknown_tool_fails():
    assert_g1(verify_request(req(hero_args(), tool="payments.wire_money"), DOCS, hero_sor()))


def test_missing_required_fails():
    r = verify_request(req(hero_args(variance=None)), DOCS, hero_sor())
    assert_g1(r)
    assert any("variance" in x.msg for x in r.reasons)


def test_never_raises_when_extract_raises(monkeypatch):
    def boom(*a):
        raise RuntimeError("boom")

    monkeypatch.setattr(extract, "extract_src", boom)
    r = verify_request(hero_request(), DOCS, hero_sor())
    assert_g1(r)
    assert isinstance(r.reasons[0], Reason)
