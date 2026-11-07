"""Attack S6.3 evidence forgery: span re-extraction and document hash -> AP-VER-01 / G1, no receipt, no call."""
import hashlib

from gatekit import HERO_DOCS

from hero import MANIFEST, pdf_claim


def _assert_g1_denied(kit, r):
    assert r.decision == "DENY" and r.receipt is None
    assert r.reasons and {(x.rule, x.guarantee) for x in r.reasons} == {("AP-VER-01", "G1")}
    assert kit.tool.calls == []


def _hero(kit, **args):
    d = kit.hero()[0].model_dump(mode="json")
    d["args"].update(args)
    return d


def test_cited_bbox_lacks_value(kit):
    c = pdf_claim("invoice.pdf", "total")
    c["src"]["bbox"] = pdf_claim("invoice.pdf", "vendor_id")["src"]["bbox"]  # box shows V-ACME, not 4800.00
    _assert_g1_denied(kit, kit.gate.prepare(_hero(kit, amount=c), HERO_DOCS))


def test_wrong_document_hash(kit):
    c = pdf_claim("invoice.pdf", "total")
    c["doc_sha256"] = MANIFEST["docs"]["po.pdf"]["sha256"]
    _assert_g1_denied(kit, kit.gate.prepare(_hero(kit, amount=c), HERO_DOCS))


def test_document_bytes_swapped(kit):
    docs = dict(HERO_DOCS)
    docs["invoice.pdf"] = HERO_DOCS["po.pdf"]  # cited hash is the real invoice's; bytes are not
    _assert_g1_denied(kit, kit.gate.prepare(kit.hero()[0], docs))


def test_forged_export_disagrees_with_records(kit):
    """A self-made JSON 'export' verifies against itself, but the system of record decides what is owed."""
    kit.seed_invoice("INV-8901", "4800.00", "4800.00")
    req, docs = kit.json_request("INV-8901", "48.00", "48.00", seed=False)
    assert hashlib.sha256(next(iter(docs.values()))).hexdigest() == req.args["amount"].doc_sha256
    _assert_g1_denied(kit, kit.gate.prepare(req, docs))
