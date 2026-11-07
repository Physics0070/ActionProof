"""USP G1: invariant 4 -- amounts are Decimal strings; no float can enter or leave the contract.

A valid ActionRequest dumps with zero floats anywhere, and every path where a float could be
smuggled in (amount value, bbox coordinate, page, any str field) is rejected with ContractError.
"""

import json

import pytest

from actionproof.contracts import ContractError, parse_request

SHA = "ab" * 32


def valid() -> dict:
    return {
        "tool": "payments.approve_invoice",
        "on_behalf_of": "user-123",
        "actor": "agent-7",
        "idempotency_key": "idem-0001",
        "args": {
            "amount": {
                "value": "4800.00",
                "claim": "DIRECT",
                "src": {"doc": "invoice.pdf", "page": 1, "bbox": ["72", "410.5", "190", "428"]},
                "doc_sha256": SHA,
            },
            "variance": {"value": "500.00", "claim": "DERIVED", "fn": "sub", "inputs": ["invoice.total", "po.total"]},
            "note": {"value": "vendor says urgent", "claim": "ASSERTED", "taint": "doc"},
        },
    }


def floats_in(obj, path="$"):
    if isinstance(obj, float):
        yield path
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from floats_in(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from floats_in(v, f"{path}[{i}]")


def test_no_float_in_model_dump():
    req = parse_request(valid())
    assert list(floats_in(req.model_dump(mode="python"))) == []
    assert list(floats_in(req.model_dump(mode="json"))) == []


def _set(d, path, value):
    node = d
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value


FLOAT_PATHS = [
    ("tool",),
    ("on_behalf_of",),
    ("actor",),
    ("idempotency_key",),
    ("args", "amount"),
    ("args", "amount", "value"),
    ("args", "amount", "src", "page"),
    ("args", "amount", "src", "bbox", 0),
    ("args", "amount", "src", "bbox", 3),
    ("args", "amount", "src", "doc"),
    ("args", "amount", "doc_sha256"),
    ("args", "variance", "value"),
    ("args", "variance", "inputs", 0),
    ("args", "note", "value"),
]


@pytest.mark.parametrize("path", FLOAT_PATHS, ids=lambda p: ".".join(map(str, p)))
def test_every_float_input_rejected(path):
    d = valid()
    _set(d, path, 4800.0)
    with pytest.raises(ContractError):
        parse_request(d)
    with pytest.raises(ContractError):
        parse_request(json.dumps(d))


def test_json_number_with_fraction_rejected():
    raw = json.dumps(valid()).replace('"4800.00"', "4800.00")
    assert "4800.00," in raw or "4800.00}" in raw
    with pytest.raises(ContractError):
        parse_request(raw)
