"""USP G1: extraction fails closed -- every failure mode raises an ExtractionError subclass.

No bad box, bad page, bad document, hidden text, extractor disagreement, missing OCR binary or bad
JSON pointer can make extraction silently yield a value (deck S4.5, ADR-002).
"""

import json
from pathlib import Path

import pytest

from actionproof import extract
from actionproof.contracts import Src
from actionproof.extract import ExtractionError, extract_pdf, extract_src, json_pointer

OUT = Path(__file__).resolve().parents[2] / "fixtures" / "out"
DOCS = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))["docs"]
INV = (OUT / "invoice.pdf").read_bytes()
PO = (OUT / "po.json").read_bytes()
TOTAL = DOCS["invoice.pdf"]["fields"]["total"]
HIDDEN = DOCS["injected.pdf"]["fields"]["hidden_text"]
P, B = TOTAL["page"], TOTAL["bbox"]


def _ocr(value):
    return lambda mp: mp.setattr(extract, "pdf_ocr", lambda *a: value)


def _env(value):
    return lambda mp: mp.setenv("TESSERACT_CMD", value)


def _none(mp):
    pass


CASES = {
    "hidden_white_text": (_none, lambda: extract_pdf((OUT / "injected.pdf").read_bytes(), HIDDEN["page"], HIDDEN["bbox"])),
    "ocr_different_number": (_ocr("$4,300.00"), lambda: extract_pdf(INV, P, B)),
    "ocr_empty": (_ocr(""), lambda: extract_pdf(INV, P, B)),
    "tesseract_missing": (_env(""), lambda: extract_pdf(INV, P, B)),
    "empty_box": (_none, lambda: extract_pdf(INV, P, ["400", "700", "410", "710"])),
    "bbox_nan": (_none, lambda: extract_pdf(INV, P, ["NaN", "1", "2", "3"])),
    "bbox_inverted": (_none, lambda: extract_pdf(INV, P, [B[2], B[1], B[0], B[3]])),
    "bbox_outside_page": (_none, lambda: extract_pdf(INV, P, ["10", "10", "9000", "9000"])),
    "bbox_not_list": (_none, lambda: extract_pdf(INV, P, "189,406,252,426")),
    "page_out_of_range": (_none, lambda: extract_pdf(INV, 99, B)),
    "page_zero": (_none, lambda: extract_pdf(INV, 0, B)),
    "not_a_pdf": (_none, lambda: extract_pdf(b"hello", P, B)),
    "empty_bytes": (_none, lambda: extract_pdf(b"", P, B)),
    "pointer_missing": (_none, lambda: json_pointer(PO, "/nope")),
    "pointer_object": (_none, lambda: json_pointer(b'{"a": {"b": "1"}}', "/a")),
    "pointer_null": (_none, lambda: json_pointer(b'{"a": null}', "/a")),
    "pointer_bool": (_none, lambda: json_pointer(b'{"a": false}', "/a")),
    "pointer_bad_syntax": (_none, lambda: json_pointer(PO, "total")),
    "pointer_bad_escape": (_none, lambda: json_pointer(PO, "/to~2tal")),
    "json_invalid": (_none, lambda: json_pointer(b"{", "/a")),
    "json_infinity": (_none, lambda: json_pointer(b'{"a": Infinity}', "/a")),
    "json_duplicate_key": (_none, lambda: json_pointer(b'{"total": "1.00", "total": "9.00"}', "/total")),
    "src_pointer_on_pdf": (_none, lambda: extract_src(INV, Src(doc="invoice.pdf", pointer="/total"))),
    "src_box_on_json": (_none, lambda: extract_src(PO, Src(doc="po.json", page=P, bbox=B))),
}


@pytest.mark.parametrize("case", list(CASES))
def test_failure_raises_extraction_error(case, monkeypatch):
    setup, call = CASES[case]
    setup(monkeypatch)
    with pytest.raises(ExtractionError):
        call()
