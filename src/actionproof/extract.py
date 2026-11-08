"""Deterministic value extraction (deck S4.5, ADR-002). No LLM on this path.

A PDF value is read twice: pdfplumber's text layer and an independent PyMuPDF raster + Tesseract
OCR pass. They must agree, or the box must be image-only (vision pass). Anything else raises;
extraction never returns a guess. JSON values come from an RFC 6901 pointer with literal-text numbers.
"""

import contextlib
import contextvars
import hashlib
import io
import json
import os
import re
import atexit
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from decimal import Decimal

from actionproof.contracts import COORD, Src


class ExtractionError(Exception):
    """Any failure to read a value. Caller DENYs."""


class Disagreement(ExtractionError):
    """The text layer and the OCR pass disagree (incl. one empty, the other not)."""


@dataclass(frozen=True)
class Extracted:
    value: str
    method: str  # "dual" | "ocr_image" | "json_pointer"


MONEYISH = re.compile(r"^-?[\d,]+(\.\d+)?$")
# ADR-017: the one money-oriented re-read (digits and money punctuation only, single line, finer raster).
MONEY_OCR = {"dpi": 400, "config": "--psm 7 -c tessedit_char_whitelist=0123456789$,.-"}
DEFAULT_OCR = {"dpi": 300, "config": "--psm 7"}
INDEX = re.compile(r"^(0|[1-9]\d*)$")


def _collapse(s: str) -> str:
    return " ".join(s.split())


def _box(bbox) -> tuple[float, float, float, float]:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or not all(isinstance(c, str) and COORD.match(c) for c in bbox):
        raise ExtractionError("bbox must be 4 decimal strings")
    x0, top, x1, bottom = (Decimal(c) for c in bbox)
    if not (Decimal(0) <= x0 < x1 and Decimal(0) <= top < bottom):
        raise ExtractionError("bbox needs 0 <= x0 < x1 and 0 <= top < bottom")
    return float(x0), float(top), float(x1), float(bottom)


def _check_page(page) -> None:
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ExtractionError("page must be an int >= 1")


# ADR-018: per-request read cache. Inside `request_scope()` a span read once is not read again: the key is
# (kind, sha256 of the document BYTES, page, box), so a different document, page, box or OCR config is a different
# key, and the scope ends with the request (a ContextVar; nothing is shared across requests or threads).
_scope: contextvars.ContextVar = contextvars.ContextVar("extract_scope", default=None)


@contextlib.contextmanager
def request_scope():
    """Reentrant: a scope already open in this context (the gate's, around verification) is reused, not replaced."""
    if _scope.get() is not None:
        yield
        return
    token = _scope.set({})
    try:
        yield
    finally:
        _scope.reset(token)


def _key(kind: str, pdf, page, bbox, *extra):
    if not (_scope.get() is not None and isinstance(pdf, bytes) and type(page) is int
            and isinstance(bbox, (list, tuple)) and all(isinstance(c, str) for c in bbox)):
        return None
    return (kind, hashlib.sha256(pdf).hexdigest(), page, tuple(bbox), *extra)


def _memo(key, compute):
    cache = _scope.get()
    if key is not None and key in cache:
        hit = cache[key]
    else:
        try:
            hit = (True, compute())
        except ExtractionError as e:  # failures are remembered too: a failed read stays failed within the request
            hit = (False, e)
        if key is not None:
            cache[key] = hit
    if hit[0]:
        return hit[1]
    raise hit[1]


def _plumber_crop(pdf: bytes, page: int, bbox):
    return _memo(_key("text", pdf, page, bbox), lambda: _plumber_crop_raw(pdf, page, bbox))         if _scope.get() is not None else _plumber_crop_raw(pdf, page, bbox)


def _plumber_crop_raw(pdf: bytes, page: int, bbox):
    """Yields (text, n_images) for the box; all pdfplumber errors become ExtractionError."""
    _check_page(page)
    box = _box(bbox)
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            if page > len(doc.pages):
                raise ExtractionError("page out of range")
            p = doc.pages[page - 1]
            px0, ptop, px1, pbottom = (float(v) for v in p.bbox)
            if box[0] < px0 or box[1] < ptop or box[2] > px1 or box[3] > pbottom:
                raise ExtractionError("bbox outside page")
            crop = p.within_bbox(box)
            return _collapse(crop.extract_text() or ""), len(crop.images)
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"pdf text read failed: {type(e).__name__}") from None


def pdf_text(pdf: bytes, page: int, bbox: list[str]) -> str:
    return _plumber_crop(pdf, page, bbox)[0]


def _raster(pdf: bytes, page: int, bbox, cfg) -> bytes:
    """PNG of the box at the config's dpi (validates page and box; every failure is an ExtractionError)."""
    _check_page(page)
    box = _box(bbox)
    if not os.path.isfile(os.environ.get("TESSERACT_CMD", "")):
        raise ExtractionError("TESSERACT_CMD is not set to an existing tesseract binary")
    try:
        import pymupdf

        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            if page > doc.page_count:
                raise ExtractionError("page out of range")
            p = doc[page - 1]
            rect = pymupdf.Rect(*box)
            if not p.rect.contains(rect):
                raise ExtractionError("bbox outside page")
            return p.get_pixmap(clip=rect, dpi=cfg["dpi"]).tobytes("png")
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"ocr failed: {type(e).__name__}") from None


def pdf_ocr(pdf: bytes, page: int, bbox: list[str], money: bool = False) -> str:
    if _scope.get() is not None:
        return _memo(_key("ocr", pdf, page, bbox, money), lambda: _pdf_ocr_raw(pdf, page, bbox, money))
    return _pdf_ocr_raw(pdf, page, bbox, money)


def _pdf_ocr_raw(pdf: bytes, page: int, bbox, money: bool) -> str:
    cfg = MONEY_OCR if money else DEFAULT_OCR
    png = _raster(pdf, page, bbox, cfg)
    if _pool_size() > 0:
        try:
            return _ocr_pooled([png], cfg)[0]
        except ExtractionError:
            raise
        except Exception as e:
            raise ExtractionError(f"ocr failed: {type(e).__name__}") from None
    try:
        import pytesseract
        from PIL import Image

        pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
        return _collapse(pytesseract.image_to_string(Image.open(io.BytesIO(png)), config=cfg["config"]))
    except Exception as e:
        raise ExtractionError(f"ocr failed: {type(e).__name__}") from None


# ADR-018: a pool of WARM tesseract processes. Starting tesseract costs ~150 ms on Windows, more than reading a
# box; `tesseract stdin stdout` loads the engine first and only then waits for the image, so a process spawned ahead
# of time answers in ~10 ms. Each process reads exactly ONE image and exits (never reused: no state or document
# data crosses requests); the pool refills in the background. OCR_POOL_SIZE=0 (default) disables it.
_pool_lock = threading.Lock()
_pool: dict[str, list] = {}
_filling: dict[str, int] = {}


def _pool_size() -> int:
    try:
        return max(0, min(16, int(os.environ.get("OCR_POOL_SIZE", "0"))))
    except ValueError:
        return 0


def _spawn(cfg):
    return subprocess.Popen([os.environ["TESSERACT_CMD"], "stdin", "stdout", *cfg["config"].split()],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env={**os.environ, "OMP_THREAD_LIMIT": "1"})


def _refill(cfg, want: int) -> None:
    def work():
        try:
            while True:
                with _pool_lock:
                    if len(_pool.setdefault(cfg["config"], [])) + _filling.get(cfg["config"], 0) >= want:
                        return
                    _filling[cfg["config"]] = _filling.get(cfg["config"], 0) + 1
                try:
                    p = _spawn(cfg)
                finally:
                    with _pool_lock:
                        _filling[cfg["config"]] -= 1
                with _pool_lock:
                    _pool[cfg["config"]].append(p)
        except Exception:
            pass  # best effort: a read with no warm process starts its own

    threading.Thread(target=work, daemon=True).start()


def _take(cfg):
    with _pool_lock:
        lst = _pool.setdefault(cfg["config"], [])
        p = lst.pop() if lst else None
    if p is not None and p.poll() is not None:
        p = None
    _refill(cfg, _pool_size() if cfg is DEFAULT_OCR else 1)
    return p or _spawn(cfg)


def drain_pool() -> None:
    with _pool_lock:
        procs = [p for lst in _pool.values() for p in lst]
        _pool.clear()
    for p in procs:
        try:
            p.kill()
            p.wait(timeout=5)
        except Exception:
            pass


atexit.register(drain_pool)


def _ocr_pooled(pngs: list[bytes], cfg) -> list[str]:
    """One warm process per image, all fed first and read after, so the reads run in parallel."""
    procs = [_take(cfg) for _ in pngs]
    try:
        for p, png in zip(procs, pngs):
            p.stdin.write(png)
            p.stdin.close()
        outs = [p.stdout.read() for p in procs]
        if any(p.wait(timeout=60) != 0 for p in procs):
            raise ExtractionError("ocr failed: tesseract exit code")
        return [_collapse(o.decode("utf-8")) for o in outs]
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()


def _tesseract_batch(pngs: list[bytes], cfg) -> list[str]:
    """ONE tesseract process for several images (its start-up, ~150 ms on Windows, dominates a single read; each
    extra image is nearly free). Same engine, same config, same image bytes as a single read, one page per image;
    anything unexpected (exit code, page count) raises so the caller falls back to single reads."""
    with tempfile.TemporaryDirectory(prefix="ap-ocr-") as d:
        names = []
        for i, png in enumerate(pngs):
            names.append(os.path.join(d, f"{i}.png"))
            with open(names[-1], "wb") as f:
                f.write(png)
        listing = os.path.join(d, "list.txt")
        with open(listing, "w", encoding="utf-8") as f:
            f.write(os.linesep.join(names))
        r = subprocess.run([os.environ["TESSERACT_CMD"], listing, "stdout", *cfg["config"].split()],
                           capture_output=True, timeout=60, env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    pages = r.stdout.decode("utf-8").split(chr(12))  # tesseract ends each page with a form feed
    if r.returncode != 0 or len(pages) != len(pngs):
        raise ExtractionError("batch ocr failed")
    return [_collapse(p) for p in pages]


_JOB = ("job",)


def prefetch_start(spans) -> None:
    """Run prefetch(spans) on a worker thread (same scope) so the OCR process overlaps the caller's database reads.
    prefetch_join() must run before the first read that needs the result."""
    cache = _scope.get()
    if cache is None or _JOB in cache:
        return
    ctx = contextvars.copy_context()
    t = threading.Thread(target=lambda: ctx.run(prefetch, spans), daemon=True)
    cache[_JOB] = t
    t.start()


def prefetch_join() -> None:
    cache = _scope.get()
    if cache is not None and _JOB in cache:
        cache[_JOB].join()


def prefetch(spans: list[tuple[bytes, int, list[str]]]) -> None:
    """Best effort, inside request_scope(): read every distinct span's OCR with one tesseract process and cache
    it. A span that cannot be read caches its error; if the batch itself misbehaves nothing is cached and each
    read later runs on its own, exactly as before."""
    if _scope.get() is None:
        return
    todo, pngs, seen = [], [], set()
    for pdf, page, bbox in spans:
        key = _key("ocr", pdf, page, bbox, False)
        if key is None or key in seen or key in _scope.get():
            continue
        seen.add(key)
        try:
            pngs.append(_raster(pdf, page, bbox, DEFAULT_OCR))
            todo.append(key)
        except ExtractionError as e:
            _scope.get()[key] = (False, e)
    if len(todo) < 2 and _pool_size() == 0:  # one read: the normal path is already one process
        return
    if not todo:
        return
    try:
        texts = _ocr_pooled(pngs, DEFAULT_OCR) if _pool_size() > 0 else _tesseract_batch(pngs, DEFAULT_OCR)
    except Exception:
        return
    for key, text in zip(todo, texts):
        _scope.get()[key] = (True, text)


def _norm(x: str, prefixes: str) -> str:
    """Lowercase, drop whitespace; strip one leading currency-ish char only if a money number remains."""
    s = "".join(x.lower().split())
    if s and s[0] in prefixes and MONEYISH.match(s[1:]):
        return s[1:]
    return s


def agree(text: str, ocr: str) -> bool:
    return _norm(text, "$") == _norm(ocr, "$s")  # OCR may read "$" as S/s; lowercased above


def extract_pdf(pdf: bytes, page: int, bbox: list[str]) -> Extracted:
    t, n_images = _plumber_crop(pdf, page, bbox)
    o = pdf_ocr(pdf, page, bbox)
    if t and o:
        if agree(t, o):
            return Extracted(t, "dual")
        # ADR-017: a money-shaped text layer gets ONE re-read of the same box with a money-only OCR config. It is
        # still an independent reader (it never sees the text layer); accepted only if it equals the text layer.
        if MONEYISH.match(_norm(t, "$")) and agree(t, pdf_ocr(pdf, page, bbox, True)):
            return Extracted(t, "dual")
        raise Disagreement("text layer and OCR disagree")
    if not t and o and n_images >= 1:
        return Extracted(o, "ocr_image")
    if t or o:
        raise Disagreement("one extractor saw a value, the other saw nothing")
    raise ExtractionError("no value in box")


class _Num(str):
    """A JSON number kept as its literal text (never a float)."""


def _no_dupes(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ExtractionError("duplicate JSON key")
    return dict(pairs)


def _bad_constant(name):
    raise ExtractionError(f"non-finite JSON number {name}")


def json_pointer(doc: bytes, pointer: str) -> str:
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ExtractionError("pointer must be empty or start with '/'")
    try:
        node = json.loads(doc, parse_float=_Num, parse_int=_Num, parse_constant=_bad_constant, object_pairs_hook=_no_dupes)
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"invalid JSON: {type(e).__name__}") from None
    for raw in pointer.split("/")[1:] if pointer else []:
        if re.search(r"~(?![01])", raw):
            raise ExtractionError("bad pointer escape")
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                raise ExtractionError("pointer target missing")
            node = node[token]
        elif isinstance(node, list):
            if not INDEX.match(token) or int(token) >= len(node):
                raise ExtractionError("bad array index")
            node = node[int(token)]
        else:
            raise ExtractionError("pointer walks into a scalar")
    if not isinstance(node, str):  # str and _Num; dict/list/None/bool rejected
        raise ExtractionError("pointer target is not a string or number")
    return str(node)


def extract_src(doc: bytes, src: Src) -> Extracted:
    if src.pointer is not None:
        return Extracted(json_pointer(doc, src.pointer), "json_pointer")
    return extract_pdf(doc, src.page, src.bbox)


# --- Read-only listing for the MCP extract_fields tool (agents cite instead of guess). Output is DATA, never authority.

MAX_SPANS = 2000


def _span_box(x0: float, top: float, x1: float, bottom: float) -> list[str]:
    """The citation box for a span, built exactly like the fixture manifest (fixtures/make.py _pdf_field): the glyph
    rect padded 0.01 pt, as 2dp decimal strings. pdfplumber's within_bbox is strict at float edges, so the pad is
    what makes a cited box re-extract the whole span."""
    return [f"{v:.2f}" for v in (x0 - 0.01, top - 0.01, x1 + 0.01, bottom + 0.01)]


def pdf_spans(pdf: bytes, max_spans: int = MAX_SPANS) -> tuple[list[dict], list[dict], bool]:
    """(words, lines, truncated). Geometry comes from PyMuPDF's word/line rects (the boxes the manifest uses); the
    TEXT of every span is what pdfplumber reads inside that box, i.e. the same text path verification re-runs, so a
    span cited as-is reproduces its text. Spans whose box pdfplumber reads as empty are dropped. Raises
    ExtractionError on any parse failure."""
    import pdfplumber
    import pymupdf

    words, lines, n = [], [], 0
    try:
        with pymupdf.open(stream=pdf, filetype="pdf") as mdoc, pdfplumber.open(io.BytesIO(pdf)) as pdoc:
            for i, (mp, pp) in enumerate(zip(mdoc, pdoc.pages), start=1):
                rects = [("words", r[:4]) for r in mp.get_text("words")]
                for block in mp.get_text("dict").get("blocks", []):
                    rects += [("lines", ln["bbox"]) for ln in block.get("lines", [])]
                px0, ptop, px1, pbottom = (float(v) for v in pp.bbox)
                for kind, (x0, top, x1, bottom) in rects:
                    if n >= max_spans:
                        return words, lines, True
                    box = _span_box(x0, top, x1, bottom)
                    fb = tuple(float(c) for c in box)
                    if not (px0 <= fb[0] < fb[2] <= px1 and ptop <= fb[1] < fb[3] <= pbottom):
                        continue
                    text = _collapse(pp.within_bbox(fb).extract_text() or "")
                    if text:
                        (words if kind == "words" else lines).append({"page": i, "bbox": box, "text": text})
                        n += 1
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"pdf span listing failed: {type(e).__name__}") from None
    return words, lines, False


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def json_leaves(doc: bytes, max_leaves: int = MAX_SPANS) -> tuple[list[dict], bool]:
    """([{pointer, value}], truncated) for every string or number leaf, numbers as their literal text (the same
    parse json_pointer uses, so each pointer re-extracts its value). Raises ExtractionError on invalid JSON."""
    try:
        root = json.loads(doc, parse_float=_Num, parse_int=_Num, parse_constant=_bad_constant,
                          object_pairs_hook=_no_dupes)
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"invalid JSON: {type(e).__name__}") from None
    out: list[dict] = []
    stack = [("", root)]
    while stack:
        ptr, node = stack.pop()
        if isinstance(node, dict):
            stack += [(f"{ptr}/{_escape(k)}", v) for k, v in reversed(list(node.items()))]
        elif isinstance(node, list):
            stack += [(f"{ptr}/{i}", v) for i, v in reversed(list(enumerate(node)))]
        elif isinstance(node, str):
            if len(out) >= max_leaves:
                return out, True
            out.append({"pointer": ptr, "value": str(node)})
    return out, False
