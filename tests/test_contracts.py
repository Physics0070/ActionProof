import copy
import hashlib
import json

import pytest
import rfc8785

from actionproof.contracts import (
    ActionRequest,
    Claim,
    ClaimType,
    ContractError,
    canonical_bytes,
    parse_request,
    request_hash,
)

SHA = "ab" * 32


def slide4() -> dict:
    """Slide-4 simplified ActionRequest (DECK_TRACE S4.4)."""
    return {
        "tool": "payments.approve_invoice",
        "on_behalf_of": "user-123",
        "actor": "agent-7",
        "idempotency_key": "idem-0001",
        "args": {
            "amount": {
                "value": "4800.00",
                "claim": "DIRECT",
                "src": {"doc": "invoice.pdf", "page": 1, "bbox": ["72", "410", "190", "428"], "pointer": None},
                "doc_sha256": SHA,
            },
            "variance": {
                "value": "500.00",
                "claim": "DERIVED",
                "fn": "sub",
                "inputs": ["invoice.total", "po.total"],
            },
            "note": {"value": "vendor says urgent", "claim": "ASSERTED", "taint": "doc"},
        },
    }


def rejects(raw):
    with pytest.raises(ContractError):
        parse_request(raw)


def test_slide4_round_trips():
    req = parse_request(slide4())
    assert req.args["amount"].claim is ClaimType.DIRECT
    assert req.args["variance"].fn == "sub"
    assert req.args["note"].taint == "doc"
    again = parse_request(canonical_bytes(req))
    assert again == req
    assert request_hash(again) == request_hash(req)


def test_parse_accepts_bytes_str_dict():
    d = slide4()
    s = json.dumps(d)
    assert parse_request(d) == parse_request(s) == parse_request(s.encode())


def test_hash_stable_across_key_order_and_whitespace():
    d = slide4()
    compact = json.dumps(d, separators=(",", ":"))
    reordered = json.dumps(dict(reversed(list(d.items()))), indent=4, sort_keys=True)
    assert request_hash(parse_request(compact)) == request_hash(parse_request(reordered))


def test_hash_is_sha256_of_canonical():
    req = parse_request(slide4())
    assert request_hash(req) == hashlib.sha256(canonical_bytes(req)).hexdigest()


def test_changing_amount_changes_hash():
    d = slide4()
    h1 = request_hash(parse_request(d))
    d["args"]["amount"]["value"] = "4800.01"
    assert request_hash(parse_request(d)) != h1


def test_canonical_bytes_is_rfc8785():
    req = parse_request(slide4())
    assert canonical_bytes(req) == rfc8785.dumps(req.model_dump(mode="json", exclude_none=False))


def test_float_amount_rejected():
    d = slide4()
    d["args"]["amount"]["value"] = 4800.0
    rejects(d)
    rejects(json.dumps(d))
    d["args"]["amount"] = 4800.0  # bare number in place of a claim
    rejects(d)


def test_non_two_dp_money_rejected():
    for bad in ["4800.0", "4800.000", "4.8e3", "4800.00e0", "NaN", "Infinity", "+4800.00", " 4800.00"]:
        d = slide4()
        d["args"]["amount"]["value"] = bad
        rejects(d)


def test_unknown_field_rejected():
    for path in [(), ("args", "amount"), ("args", "amount", "src")]:
        d = slide4()
        node = d
        for p in path:
            node = node[p]
        node["extra"] = "x"
        rejects(d)


def test_direct_without_doc_sha_rejected():
    d = slide4()
    del d["args"]["amount"]["doc_sha256"]
    rejects(d)


def test_direct_without_src_rejected():
    d = slide4()
    del d["args"]["amount"]["src"]
    rejects(d)


def test_bad_doc_sha_rejected():
    for bad in ["AB" * 32, "ab" * 31, "zz" * 32]:
        d = slide4()
        d["args"]["amount"]["doc_sha256"] = bad
        rejects(d)


def test_derived_with_src_rejected():
    d = slide4()
    d["args"]["variance"]["src"] = d["args"]["amount"]["src"]
    rejects(d)


def test_derived_with_doc_sha_rejected():
    d = slide4()
    d["args"]["variance"]["doc_sha256"] = SHA
    rejects(d)


def test_derived_needs_inputs():
    d = slide4()
    d["args"]["variance"]["inputs"] = []
    rejects(d)
    del d["args"]["variance"]["inputs"]
    rejects(d)


def test_bad_fn_rejected():
    d = slide4()
    d["args"]["variance"]["fn"] = "mul"
    rejects(d)


def test_asserted_with_fn_rejected():
    d = slide4()
    d["args"]["note"]["fn"] = "sub"
    rejects(d)


def test_asserted_with_src_or_inputs_rejected():
    d = slide4()
    d["args"]["note"]["src"] = {"doc": "invoice.pdf", "pointer": "/total"}
    rejects(d)
    d = slide4()
    d["args"]["note"]["inputs"] = ["invoice.total"]
    rejects(d)


def test_unknown_claim_type_rejected():
    d = slide4()
    d["args"]["amount"]["claim"] = "TRUSTED"
    rejects(d)


@pytest.mark.parametrize(
    "bbox",
    [
        ["72", "410", "190"],                 # 3 coords
        ["72", "410", "190", "428", "1"],     # 5 coords
        ["190", "410", "72", "428"],          # x0 >= x1
        ["72", "428", "190", "410"],          # top >= bottom
        ["72", "410", "190", "abc"],          # not decimal
        [72, 410, 190, 428],                  # ints, not strings
        [72.0, 410.0, 190.0, 428.0],          # floats
        ["72", "410", "190", "NaN"],
    ],
)
def test_bad_bbox_rejected(bbox):
    d = slide4()
    d["args"]["amount"]["src"]["bbox"] = bbox
    rejects(d)


def test_src_needs_exactly_one_locator():
    d = slide4()
    d["args"]["amount"]["src"]["pointer"] = "/total"  # both page+bbox and pointer
    rejects(d)
    d = slide4()
    d["args"]["amount"]["src"] = {"doc": "invoice.pdf"}  # neither
    rejects(d)
    d = slide4()
    d["args"]["amount"]["src"] = {"doc": "invoice.pdf", "page": 1}  # page without bbox
    rejects(d)
    d = slide4()
    d["args"]["amount"]["src"] = {"doc": "invoice.pdf", "bbox": ["72", "410", "190", "428"]}
    rejects(d)


def test_pointer_src_ok_and_bad_pointer_rejected():
    d = slide4()
    d["args"]["amount"]["src"] = {"doc": "po.json", "pointer": "/lines/0/total"}
    assert parse_request(d).args["amount"].src.pointer == "/lines/0/total"
    for bad in ["lines/0", "/a~2b"]:
        d["args"]["amount"]["src"]["pointer"] = bad
        rejects(copy.deepcopy(d))


def test_page_must_be_positive_int():
    for bad in [0, -1, 1.0, "1", True]:
        d = slide4()
        d["args"]["amount"]["src"]["page"] = bad
        rejects(d)


def test_direct_non_money_value_allowed():
    d = slide4()
    d["args"]["vendor_id"] = {
        "value": "V-1009",
        "claim": "DIRECT",
        "src": {"doc": "invoice.pdf", "page": 1, "bbox": ["10.5", "20", "30.25", "40"]},
        "doc_sha256": SHA,
    }
    assert parse_request(d).args["vendor_id"].value == "V-1009"


@pytest.mark.parametrize(
    "raw", [b"", b"not json", "{", "[]", "null", 42, None, [], {}, b"\xff\xfe", {"tool": "x"}]
)
def test_garbage_raises_contract_error(raw):
    rejects(raw)


def test_contract_error_is_plain_exception():
    assert issubclass(ContractError, Exception)
    assert not issubclass(ContractError, ValueError)


def test_direct_construction_is_validated():
    with pytest.raises(Exception):
        Claim(value="4800.00", claim=ClaimType.DIRECT)  # no src/doc_sha256
    assert isinstance(parse_request(slide4()), ActionRequest)
