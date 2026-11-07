import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fixtures"))

import make  # noqa: E402

OUT = ROOT / "fixtures" / "out"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def manifest():
    return make.build()


def test_manifest_file_matches_build_return(manifest):
    on_disk = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest


def test_every_pdf_field_crop_extracts_expected_text(manifest):
    checked = 0
    for doc_id, doc in manifest["docs"].items():
        if doc["kind"] != "pdf":
            continue
        with pdfplumber.open(OUT / doc["path"]) as pdf:
            for name, field in doc["fields"].items():
                if doc_id == "imageonly.pdf" and name == "total":
                    continue
                bbox = [float(v) for v in field["bbox"]]
                page = pdf.pages[field["page"] - 1]
                text = page.within_bbox(bbox).extract_text()
                assert text == field["text"], f"{doc_id}:{name} got {text!r}"
                checked += 1
    assert checked > 0


def test_imageonly_total_is_image_with_no_text(manifest):
    field = manifest["docs"]["imageonly.pdf"]["fields"]["total"]
    bbox = [float(v) for v in field["bbox"]]
    with pdfplumber.open(OUT / "imageonly.pdf") as pdf:
        crop = pdf.pages[field["page"] - 1].within_bbox(bbox)
        assert crop.extract_text() in ("", None)
        assert len(crop.images) > 0


def test_json_pointer_fields_match_files(manifest):
    for doc_id, doc in manifest["docs"].items():
        if doc["kind"] != "json":
            continue
        data = json.loads((OUT / doc["path"]).read_text(encoding="utf-8"))
        for field in doc["fields"].values():
            node = data
            for key in field["pointer"].lstrip("/").split("/"):
                node = node[key]
            assert node == field["value"], doc_id


def test_hero_variance_is_po_minus_invoice(manifest):
    hero = manifest["hero"]
    inv = Decimal(manifest["docs"][hero["invoice"]]["fields"]["total"]["value"])
    po = Decimal(manifest["docs"][hero["po"]]["fields"]["total"]["value"])
    # Recorded as a magnitude: |po - invoice| (po 4300.00 vs invoice 4800.00).
    assert abs(po - inv) == Decimal(hero["variance"])


def test_sha256_matches_file_bytes(manifest):
    for doc_id, doc in manifest["docs"].items():
        assert doc["sha256"] == _sha(OUT / doc["path"]), doc_id


def test_build_twice_leaves_manifest_and_files_unchanged():
    make.build()
    before = {p: _sha(p) for p in OUT.rglob("*") if p.is_file()}
    make.build()
    after = {p: _sha(p) for p in OUT.rglob("*") if p.is_file()}
    assert before == after


def test_at_least_20_benign_pairs(manifest):
    docs = manifest["docs"]
    invoices = [k for k in docs if k.startswith("benign/inv-")]
    assert len(invoices) >= 20
    for inv in invoices:
        po = inv.replace("benign/inv-", "benign/po-").replace(".pdf", ".json")
        assert po in docs, po
        assert "total" in docs[inv]["fields"]


def test_injected_full_page_text_contains_instruction(manifest):
    with pdfplumber.open(OUT / "injected.pdf") as pdf:
        text = "".join(page.extract_text() or "" for page in pdf.pages)
    assert "approve regardless" in text
    assert "hidden_text" in manifest["docs"]["injected.pdf"]["fields"]
