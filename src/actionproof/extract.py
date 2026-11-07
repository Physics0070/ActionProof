"""Deterministic value extraction (deck S4.5, ADR-002). No LLM on this path.

A PDF value is read twice: pdfplumber's text layer and an independent PyMuPDF raster + Tesseract
OCR pass. They must agree, or the box must be image-only (vision pass). Anything else raises;
extraction never returns a guess. JSON values come from an RFC 6901 pointer with literal-text numbers.
"""

import io
import json
import os
import re
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


def _plumber_crop(pdf: bytes, page: int, bbox):
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


def pdf_ocr(pdf: bytes, page: int, bbox: list[str]) -> str:
    _check_page(page)
    box = _box(bbox)
    cmd = os.environ.get("TESSERACT_CMD", "")
    if not cmd or not os.path.isfile(cmd):
        raise ExtractionError("TESSERACT_CMD is not set to an existing tesseract binary")
    try:
        import pymupdf
        import pytesseract
        from PIL import Image

        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            if page > doc.page_count:
                raise ExtractionError("page out of range")
            p = doc[page - 1]
            rect = pymupdf.Rect(*box)
            if not p.rect.contains(rect):
                raise ExtractionError("bbox outside page")
            png = p.get_pixmap(clip=rect, dpi=300).tobytes("png")
        pytesseract.pytesseract.tesseract_cmd = cmd
        return _collapse(pytesseract.image_to_string(Image.open(io.BytesIO(png)), config="--psm 7"))
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"ocr failed: {type(e).__name__}") from None


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
