"""USP G1: DERIVED values come only from allowlisted pure functions; the model's number is never trusted.

The verifier recomputes every DERIVED claim from verified inputs (deck S4.2, invariant 2).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fixtures"))

from hero import hero_request, hero_sor, load_docs  # noqa: E402

from actionproof.contracts import ContractError, parse_request  # noqa: E402
from actionproof.verify import verify_request  # noqa: E402

DOCS = load_docs()


def with_variance(**v) -> dict:
    d = hero_request().model_dump(mode="json")
    d["args"]["variance"] = {"claim": "DERIVED", "fn": "sub", "inputs": ["invoice.total", "po.total"], "value": "500.00"} | v
    return d


@pytest.mark.parametrize("claimed", ["501.00", "499.99", "0.00", "-500.00", "9100.00"])
def test_model_claimed_value_ignored(claimed):
    r = verify_request(parse_request(with_variance(value=claimed)), DOCS, hero_sor())
    assert r.ok is False and r.claims["variance"].ok is False
    assert r.claims["variance"].reason.guarantee == "G1" and r.claims["variance"].reason.rule == "AP-VER-01"


def test_recomputed_value_passes():
    r = verify_request(parse_request(with_variance()), DOCS, hero_sor())
    assert r.ok and r.claims["variance"].value == "500.00" and r.claims["variance"].method == "derived:sub"


@pytest.mark.parametrize("fn", ["mul", "div", "eval", "max"])
def test_non_allowlisted_fn_rejected(fn):
    with pytest.raises(ContractError):
        parse_request(with_variance(fn=fn))


def test_non_allowlisted_fn_rejected_here_too():
    req = parse_request(with_variance())
    bad = req.model_copy(update={"args": req.args | {"variance": req.args["variance"].model_copy(update={"fn": "mul"})}})
    r = verify_request(bad, DOCS, hero_sor())
    assert r.ok is False and r.claims["variance"].ok is False
