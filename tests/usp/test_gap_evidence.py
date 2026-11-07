"""USP G1: a tool argument with no source behind it cannot pass (deck S2.2, evidence gap).

A request whose cited span does not hold the claimed value is NOT ok, with a G1 / AP-VER-01 reason.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fixtures"))

from hero import hero_request, hero_sor, load_docs, pdf_claim  # noqa: E402

from actionproof.contracts import parse_request  # noqa: E402
from actionproof.verify import verify_request  # noqa: E402


def test_cited_span_lacks_value():
    d = hero_request().model_dump(mode="json")
    c = pdf_claim("invoice.pdf", "total")
    c["src"]["bbox"] = pdf_claim("invoice.pdf", "vendor_id")["src"]["bbox"]  # span holds V-ACME, not 4800.00
    d["args"]["amount"] = c
    result = verify_request(parse_request(d), load_docs(), hero_sor())
    assert result.ok is False
    reason = result.reasons[0]
    assert reason.guarantee == "G1" and reason.rule == "AP-VER-01"
    assert result.claims["amount"].reason.guarantee == "G1"


def test_missing_required_arg_is_a_gap():
    d = hero_request().model_dump(mode="json")
    del d["args"]["amount"]
    result = verify_request(parse_request(d), load_docs(), hero_sor())
    assert result.ok is False and result.reasons[0].guarantee == "G1" and result.reasons[0].rule == "AP-VER-01"
