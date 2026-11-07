"""USP G1: verify_request fails closed -- it returns not-ok and never raises (invariant 1).

Garbage documents, bad bytes, wrong types and unexpected exceptions all become a G1 / AP-VER-01 DENY.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fixtures"))

from hero import hero_request, hero_sor, load_docs  # noqa: E402

from actionproof import extract  # noqa: E402
from actionproof.verify import verify_request  # noqa: E402

DOCS = load_docs()


def assert_denied(r):
    assert r.ok is False
    assert r.reasons and all(x.guarantee == "G1" and x.rule == "AP-VER-01" for x in r.reasons)


@pytest.mark.parametrize("blob", [b"", b"garbage", b"%PDF-1.7 broken", "not bytes", None, 42])
def test_garbage_docs(blob):
    assert_denied(verify_request(hero_request(), {"invoice.pdf": blob, "po.json": blob}, hero_sor()))


@pytest.mark.parametrize("docs", [None, 42, "x", []])
def test_bad_docs_container(docs):
    assert_denied(verify_request(hero_request(), docs, hero_sor()))


@pytest.mark.parametrize("sor", [None, 42, {"po.total": 4300.0}, {"po.total": "NaN"}])
def test_bad_sor(sor):
    d = hero_request().model_dump(mode="json")
    del d["args"]["po.total"]
    from actionproof.contracts import parse_request

    assert_denied(verify_request(parse_request(d), DOCS, sor))


@pytest.mark.parametrize("req", [None, 42, "x", {"tool": "payments.approve_invoice"}])
def test_garbage_request(req):
    assert_denied(verify_request(req, DOCS, hero_sor()))


@pytest.mark.parametrize("exc", [RuntimeError, ValueError, MemoryError, KeyError])
def test_extract_raises(monkeypatch, exc):
    def boom(*a):
        raise exc("boom")

    monkeypatch.setattr(extract, "extract_src", boom)
    assert_denied(verify_request(hero_request(), DOCS, hero_sor()))
