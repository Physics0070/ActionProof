"""ADR-018: per-request read cache + one-process OCR batch. Behaviour must be unchanged: same values, same failures,
nothing shared across requests or documents."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fixtures"))
sys.path.insert(0, str(ROOT))

from hero import hero_request, hero_sor, load_docs, pdf_claim  # noqa: E402

from actionproof import extract  # noqa: E402
from actionproof.contracts import ActionRequest  # noqa: E402


@pytest.fixture(autouse=True)
def _pool_off_unless_the_test_enables_it(monkeypatch):
    """The warm OCR pool is a process-wide env switch that eval.executor turns on at import (as deployed); these
    tests state their own precondition: off, except the pool tests below which set OCR_POOL_SIZE themselves."""
    monkeypatch.setenv("OCR_POOL_SIZE", "0")
from actionproof.verify import verify_request  # noqa: E402

OUT = ROOT / "fixtures" / "out"
MANIFEST = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))["docs"]
DOCS = load_docs()


def spans(name: str):
    e = MANIFEST[name]
    pdf = (OUT / e["path"]).read_bytes()
    return [(pdf, f["page"], f["bbox"]) for f in e["fields"].values() if "bbox" in f]


def test_batch_ocr_equals_single_reads_on_fixture_spans():
    items = [s for n in ("invoice.pdf", "po.pdf", "imageonly.pdf", "injected.pdf") for s in spans(n)]
    single = [extract.pdf_ocr(*s) for s in items]  # no scope: the plain one-process-per-read path
    with extract.request_scope():
        extract.prefetch(items)
        assert all(extract._key("ocr", *s, False) in extract._scope.get() for s in items), "batch did not run"
        batched = [extract.pdf_ocr(*s) for s in items]
    assert batched == single


def test_prefetch_uses_one_tesseract_process_and_no_single_reads(monkeypatch):
    runs = []
    real = subprocess.run
    monkeypatch.setattr(extract.subprocess, "run", lambda *a, **k: (runs.append(a), real(*a, **k))[1])
    monkeypatch.setattr(extract, "_pdf_ocr_raw", lambda *a: pytest.fail("a single read ran"))
    items = spans("invoice.pdf")
    with extract.request_scope():
        extract.prefetch(items)
        for s in items:
            extract.pdf_ocr(*s)
    assert len(runs) == 1


def test_a_span_is_read_once_per_request(monkeypatch):
    n = {"ocr": 0, "text": 0}
    ocr, text = extract._pdf_ocr_raw, extract._plumber_crop_raw
    monkeypatch.setattr(extract, "_pdf_ocr_raw", lambda *a: (n.__setitem__("ocr", n["ocr"] + 1), ocr(*a))[1])
    monkeypatch.setattr(extract, "_plumber_crop_raw", lambda *a: (n.__setitem__("text", n["text"] + 1), text(*a))[1])
    pdf, page, bbox = spans("invoice.pdf")[0]
    with extract.request_scope():
        for _ in range(3):
            extract.extract_pdf(pdf, page, bbox)
    assert n == {"ocr": 1, "text": 1}
    with extract.request_scope():  # a new request starts empty
        extract.extract_pdf(pdf, page, bbox)
    assert n == {"ocr": 2, "text": 2}


def test_cache_is_keyed_by_document_content_not_by_name_or_box():
    base = (OUT / MANIFEST["invoice.pdf"]["path"]).read_bytes()
    f = MANIFEST["invoice.pdf"]["fields"]["total"]
    from eval.cases import Edit, build_derived

    edited = build_derived(base, MANIFEST["invoice.pdf"]["fields"], [Edit(op="replace_text", field="total", text="$48.00")])
    assert hashlib.sha256(edited).hexdigest() != hashlib.sha256(base).hexdigest()
    with extract.request_scope():
        a = extract.extract_pdf(base, f["page"], f["bbox"])
        b = extract.extract_pdf(edited, f["page"], f["bbox"])
    assert a.value == "$4,800.00" and b.value == "$48.00"


def test_failures_are_cached_as_failures_and_still_raise(monkeypatch):
    pdf, page, _ = spans("invoice.pdf")[0]
    outside = ["0.00", "0.00", "9999.00", "9999.00"]
    with extract.request_scope():
        for _ in range(2):
            with pytest.raises(extract.ExtractionError):
                extract.extract_pdf(pdf, page, outside)


def test_scope_ends_with_the_request():
    assert extract._scope.get() is None
    with extract.request_scope():
        assert extract._scope.get() == {}
    assert extract._scope.get() is None


def test_misbehaving_batch_caches_nothing_and_reads_fall_back(monkeypatch):
    items = spans("invoice.pdf")
    monkeypatch.setattr(extract, "_tesseract_batch", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    with extract.request_scope():
        extract.prefetch(items)
        assert not any(k[0] == "ocr" for k in extract._scope.get())
        got = [extract.pdf_ocr(*s) for s in items]
    assert got == [extract.pdf_ocr(*s) for s in items]


def test_batch_with_wrong_page_count_is_refused():
    class R:
        returncode, stdout = 0, b"only one page"

    pngs = [b"x", b"y"]
    orig = extract.subprocess.run
    try:
        extract.subprocess.run = lambda *a, **k: R()
        with pytest.raises(extract.ExtractionError):
            extract._tesseract_batch(pngs, extract.DEFAULT_OCR)
    finally:
        extract.subprocess.run = orig


def test_verify_hero_unchanged_and_hash_mismatch_still_denied_after_a_warm_request():
    ok = verify_request(hero_request(), DOCS, hero_sor())
    assert ok.ok, ok.reasons
    forged = dict(DOCS)
    forged["invoice.pdf"] = DOCS["invoice.pdf"] + b"\n%tampered"  # the claim still carries the honest hash
    bad = verify_request(hero_request(), forged, hero_sor())
    assert not bad.ok
    assert any("document hash mismatch" in r.msg for r in bad.reasons)


def test_verify_wrong_value_still_fails_when_the_same_span_backs_two_claims():
    a = hero_request().model_dump(mode="json")["args"]
    a["amount"] = pdf_claim("invoice.pdf", "total", "4900.00")
    a["invoice.total"] = pdf_claim("invoice.pdf", "total", "4800.00")
    r = verify_request(ActionRequest.model_validate({"tool": "payments.approve_invoice", "on_behalf_of": "user-123",
                                                     "actor": "agent-7", "idempotency_key": "k", "args": a}),
                       DOCS, hero_sor())
    assert not r.ok and not r.claims["amount"].ok and r.claims["invoice.total"].ok


# ------------------------------------------------------------------ warm process pool (OCR_POOL_SIZE)
@pytest.fixture
def pool(monkeypatch):
    monkeypatch.setenv("OCR_POOL_SIZE", "4")
    extract.drain_pool()
    yield
    extract.drain_pool()


def test_pool_is_off_by_default_and_junk_values_mean_off(monkeypatch):
    monkeypatch.delenv("OCR_POOL_SIZE", raising=False)
    assert extract._pool_size() == 0
    for junk in ("x", "-3", ""):
        monkeypatch.setenv("OCR_POOL_SIZE", junk)
        assert extract._pool_size() == 0
    monkeypatch.setenv("OCR_POOL_SIZE", "999")
    assert extract._pool_size() == 16


def test_pooled_reads_equal_plain_reads_on_fixture_spans(monkeypatch):
    items = [s for n in ("invoice.pdf", "po.pdf", "imageonly.pdf", "injected.pdf") for s in spans(n)]
    monkeypatch.setenv("OCR_POOL_SIZE", "0")
    plain = [extract.pdf_ocr(*s) for s in items]
    plain_money = [extract.pdf_ocr(*s, True) for s in items[:4]]
    monkeypatch.setenv("OCR_POOL_SIZE", "4")
    extract.drain_pool()
    try:
        pooled = [extract.pdf_ocr(*s) for s in items]
        with extract.request_scope():
            extract.prefetch(items)
            batched = [extract.pdf_ocr(*s) for s in items]
        pooled_money = [extract.pdf_ocr(*s, True) for s in items[:4]]
    finally:
        extract.drain_pool()
    assert pooled == plain and batched == plain and pooled_money == plain_money


def test_a_pooled_process_serves_exactly_one_image(pool):
    pdf, page, bbox = spans("invoice.pdf")[0]
    extract.pdf_ocr(pdf, page, bbox)  # starts the refill
    import time

    for _ in range(100):
        with extract._pool_lock:
            warm = list(extract._pool.get(extract.DEFAULT_OCR["config"], []))
        if len(warm) >= 2:
            break
        time.sleep(0.05)
    assert warm and all(p.poll() is None for p in warm)
    extract.pdf_ocr(pdf, page, bbox)
    with extract._pool_lock:
        left = list(extract._pool.get(extract.DEFAULT_OCR["config"], []))
    assert not any(p in left for p in [warm[-1]]), "the process that served a read went back into the pool"


def test_dead_warm_process_is_skipped_and_a_failing_one_fails_closed(pool, monkeypatch):
    pdf, page, bbox = spans("invoice.pdf")[0]
    extract.pdf_ocr(pdf, page, bbox)
    import time

    for _ in range(100):
        with extract._pool_lock:
            warm = list(extract._pool.get(extract.DEFAULT_OCR["config"], []))
        if warm:
            break
        time.sleep(0.05)
    warm[0].kill()
    warm[0].wait()
    assert extract.pdf_ocr(pdf, page, bbox)  # still answers
    monkeypatch.setattr(extract, "_spawn", lambda cfg: subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read(); sys.exit(3)"], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL))
    extract.drain_pool()
    with pytest.raises(extract.ExtractionError):
        extract.pdf_ocr(pdf, page, bbox)
