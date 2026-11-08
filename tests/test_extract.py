import json
from pathlib import Path

import pytest

from actionproof import extract
from actionproof.contracts import Src
from actionproof.extract import Disagreement, ExtractionError, agree, extract_pdf, extract_src, json_pointer

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "out"
MANIFEST = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))["docs"]


def doc(name: str) -> bytes:
    return (OUT / name).read_bytes()


def field(name: str, f: str) -> tuple[int, list[str]]:
    x = MANIFEST[name]["fields"][f]
    return x["page"], x["bbox"]


def test_hero_invoice_total_dual():
    r = extract_pdf(doc("invoice.pdf"), *field("invoice.pdf", "total"))
    assert r == extract.Extracted("$4,800.00", "dual")


def test_po_pdf_total_dual():
    r = extract_pdf(doc("po.pdf"), *field("po.pdf", "total"))
    assert r == extract.Extracted("$4,300.00", "dual")


def test_wrong_box_reads_a_different_value():
    r = extract_pdf(doc("invoice.pdf"), *field("invoice.pdf", "invoice_id"))
    assert r.value != "$4,800.00"


def test_image_only_total_uses_ocr():
    r = extract_pdf(doc("imageonly.pdf"), *field("imageonly.pdf", "total"))
    assert r.method == "ocr_image"
    assert "2,450.00" in r.value


def test_hidden_text_is_a_disagreement():
    with pytest.raises(Disagreement):
        extract_pdf(doc("injected.pdf"), *field("injected.pdf", "hidden_text"))


def test_ocr_different_number_is_a_disagreement(monkeypatch):
    monkeypatch.setattr(extract, "pdf_ocr", lambda *a: "$4,300.00")
    with pytest.raises(Disagreement):
        extract_pdf(doc("invoice.pdf"), *field("invoice.pdf", "total"))


def _ocr_by_config(monkeypatch, default: str, money: str) -> list:
    calls = []

    def fake(pdf, page, bbox, money_cfg=False):
        calls.append(money_cfg)
        return money if money_cfg else default

    monkeypatch.setattr(extract, "pdf_ocr", fake)
    return calls


def test_money_retry_accepts_only_an_exact_text_layer_match(monkeypatch):
    """ADR-017: first OCR misreads a money box; ONE money-config re-read equal to the text layer is accepted."""
    calls = _ocr_by_config(monkeypatch, "$4,8O0.00", "$4,800.00")
    r = extract_pdf(doc("invoice.pdf"), *field("invoice.pdf", "total"))
    assert r == extract.Extracted("$4,800.00", "dual") and calls == [False, True]


def test_money_retry_still_disagreeing_is_a_disagreement(monkeypatch):
    calls = _ocr_by_config(monkeypatch, "$4,300.00", "$4,300.00")
    with pytest.raises(Disagreement):
        extract_pdf(doc("invoice.pdf"), *field("invoice.pdf", "total"))
    assert calls == [False, True]  # exactly one retry, never a loop


def test_no_money_retry_for_a_non_money_text_layer(monkeypatch):
    calls = _ocr_by_config(monkeypatch, "INV-2O48", "INV-2048")
    with pytest.raises(Disagreement):
        extract_pdf(doc("invoice.pdf"), *field("invoice.pdf", "invoice_id"))
    assert calls == [False]


def test_ocr_empty_with_text_is_a_disagreement(monkeypatch):
    monkeypatch.setattr(extract, "pdf_ocr", lambda *a: "")
    with pytest.raises(Disagreement):
        extract_pdf(doc("invoice.pdf"), *field("invoice.pdf", "total"))


def test_missing_tesseract_is_extraction_error(monkeypatch):
    monkeypatch.setenv("TESSERACT_CMD", str(OUT / "no-such-tesseract.exe"))
    with pytest.raises(ExtractionError):
        extract_pdf(doc("invoice.pdf"), *field("invoice.pdf", "total"))


@pytest.mark.parametrize(
    "t,o,same",
    [
        ("$4,800.00", "$4,800.00", True),
        ("$4,800.00", "S4,800.00", True),
        ("$4,800.00", "s4,800.00", True),
        ("$4,800.00", "4,800.00", True),
        ("$4, 800.00", "$4,800.00", True),
        ("V-ACME", "v-acme", True),
        ("$4,800.00", "$4,300.00", False),
        ("$4,800.00", "$4800.00", False),  # no fuzzy matching: separators must match
        ("Stock", "tock", False),  # prefix strip only when a money number remains
        ("$4,800.00", "SS4,800.00", False),
    ],
)
def test_agree_normalization(t, o, same):
    assert agree(t, o) is same


def test_extract_src_dispatch():
    po = MANIFEST["po.json"]["fields"]["total"]
    assert extract_src(doc("po.json"), Src(doc="po.json", pointer=po["pointer"])) == extract.Extracted("4300.00", "json_pointer")
    page, bbox = field("invoice.pdf", "total")
    assert extract_src(doc("invoice.pdf"), Src(doc="invoice.pdf", page=page, bbox=bbox)).method == "dual"


def test_json_pointer_po_total():
    assert json_pointer(doc("po.json"), "/total") == "4300.00"


SYNTH = b'{"a/b": "slash", "m~n": "tilde", "arr": [{"v": 7}, "x"], "obj": {}, "n": null, "t": true, "f": 4300.10, "e": 1E+2}'


@pytest.mark.parametrize(
    "ptr,want",
    [("/a~1b", "slash"), ("/m~0n", "tilde"), ("/arr/0/v", "7"), ("/arr/1", "x"), ("/f", "4300.10"), ("/e", "1E+2")],
)
def test_json_pointer_scalars(ptr, want):
    got = json_pointer(SYNTH, ptr)
    assert got == want and type(got) is str


BAD_POINTERS = ["/missing", "/obj", "/arr", "/n", "/t", "", "total", "/m~2n", "/arr/2", "/arr/01", "/arr/-", "/f/x"]


@pytest.mark.parametrize("ptr", BAD_POINTERS)
def test_json_pointer_rejects(ptr):
    with pytest.raises(ExtractionError):
        json_pointer(SYNTH, ptr)


@pytest.mark.parametrize("raw", [b"not json", b'{"a": NaN}', b'{"a": "1", "a": "2"}', b"\xff\xfe"])
def test_json_pointer_bad_documents(raw):
    with pytest.raises(ExtractionError):
        json_pointer(raw, "/a")


PAGE, BOX = field("invoice.pdf", "total")
BAD_PDF_INPUTS = [
    ("bbox_nan", PAGE, ["NaN", "1", "2", "3"]),
    ("bbox_inverted", PAGE, [BOX[2], BOX[1], BOX[0], BOX[3]]),
    ("bbox_short", PAGE, BOX[:3]),
    ("bbox_float", PAGE, [189.99, 406.94, 252.28, 426.20]),
    ("bbox_exponent", PAGE, ["1e2", "1", "200", "30"]),
    ("bbox_outside_page", PAGE, ["10", "10", "9000", "9000"]),
    ("bbox_negative", PAGE, ["-5", "1", "20", "30"]),
    ("page_zero", 0, BOX),
    ("page_out_of_range", 2, BOX),
    ("page_bool", True, BOX),
]


@pytest.mark.parametrize("name,page,bbox", BAD_PDF_INPUTS, ids=[b[0] for b in BAD_PDF_INPUTS])
def test_bad_pdf_inputs(name, page, bbox):
    with pytest.raises(ExtractionError):
        extract_pdf(doc("invoice.pdf"), page, bbox)


def test_non_pdf_bytes():
    with pytest.raises(ExtractionError):
        extract_pdf(b"%PDF-1.7 garbage", PAGE, BOX)
    with pytest.raises(ExtractionError):
        extract_pdf(doc("po.json"), PAGE, BOX)


def test_ocr_agreement_rate_on_benign_totals(capsys):
    names = [n for n, d in MANIFEST.items() if d["kind"] == "pdf" and "imageonly" not in n]
    misses = []
    for n in names:
        try:
            r = extract_pdf(doc(n), *field(n, "total"))
            if r.method != "dual" or r.value != MANIFEST[n]["fields"]["total"]["text"]:
                misses.append(n)
        except ExtractionError:
            misses.append(n)
    with capsys.disabled():
        print(f"\nOCR agreement on fixture totals: {len(names) - len(misses)}/{len(names)} misses={misses}")
    assert misses == []
