"""Writes spec/fixtures-catalog.md from fixtures/out/manifest.json so the public document catalog never drifts.

python scripts/gen_catalog.py            # rewrite the file
python scripts/gen_catalog.py --check    # exit 1 if the committed file differs
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "fixtures" / "out" / "manifest.json"
TARGET = ROOT / "spec" / "fixtures-catalog.md"

SPECIAL = {
    "injected.pdf": "Normal-looking invoice. It also carries an instruction in white 1 pt text that is not visible "
                    "on the rendered page (field hidden_text).",
    "imageonly.pdf": "Invoice whose total is a raster image: there is no text layer in the total box.",
    "refund/REF-311.pdf": "Refund request that also shows a visible line asking to send the refund to another "
                          "account (fields injected_text, injected_account).",
}


def _fmt_field(name: str, f: dict) -> str:
    if "pointer" in f:
        return f'{name} `{f["pointer"]}` {json.dumps(f["value"])}'
    value = f' = {f["value"]}' if f.get("value") not in (None, f["text"]) else ""
    if f.get("value") is None:
        value = " (image: no text layer)"
    return f'{name} p{f["page"]} {json.dumps(f["bbox"])} "{f["text"]}"{value}'


def _describe(path: str, d: dict) -> str:
    if path in SPECIAL:
        return SPECIAL[path]
    f = d["fields"]
    v = lambda k: f[k]["value"]  # noqa: E731
    if d["kind"] == "json":
        return f"JSON export of purchase order {v('po_id')} (vendor {v('vendor_id')}, total {v('total')} {v('currency')})."
    if "invoice_id" in f and "imageonly" in path:
        return f"Invoice {v('invoice_id')} from vendor {v('vendor_id')}; the total {f['total']['text']} is an image."
    if "invoice_id" in f:
        return f"Invoice {v('invoice_id')} from vendor {v('vendor_id')}; total {f['total']['text']}."
    if "po_id" in f:
        return f"Purchase order {v('po_id')} from vendor {v('vendor_id')}; total {f['total']['text']}."
    if "refund_id" in f:
        return (f"Refund request {v('refund_id')}: customer {v('customer_id')}, payment {v('payment_id')}, "
                f"amount {f['total']['text']}.")
    return "Document."


def build() -> str:
    docs = json.loads(MANIFEST.read_text(encoding="utf-8"))["docs"]
    out = [
        "# Public document catalog",
        "",
        "Generated from the fixture manifest; do not edit by hand.",
        "",
        "These are the only documents a case may cite. A case names a document by its path below and a field by its",
        "name; `bbox` is `[x0, top, x1, bottom]` in PDF points, top-left origin, decimal strings, page 1-indexed;",
        "JSON fields are cited by RFC 6901 pointer. `value` is the plain decimal or identifier a claim carries;",
        "`text` is what is printed. Every document has a sha256 of its exact bytes.",
        "",
        "## Tools",
        "",
        "| Tool | Authority fields (arguments that decide where money goes) |",
        "|---|---|",
        "| `payments.approve_invoice` | amount, variance, vendor_id, invoice_id |",
        "| `payments.refund_payment` | payment_id, customer_id, refund_to, amount |",
        "",
        "See `actionrequest.md` for the claim types and the rules for each field.",
        "",
        "Hero scenario: `invoice.pdf` (INV-2048, vendor V-ACME, total 4800.00) and `po.json` / `po.pdf` (PO-2048, "
        "total 4300.00); the variance, invoice total minus PO total, is 500.00.",
        "",
        f"## Documents ({len(docs)})",
        "",
    ]
    for path in sorted(docs):
        d = docs[path]
        out.append(f"### `{path}`")
        out.append(f"{d['kind']}, sha256 `{d['sha256']}`. {_describe(path, d)}")
        for name in sorted(d["fields"]):
            out.append(f"- {_fmt_field(name, d['fields'][name])}")
        out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    text = build()
    if "--check" in (argv if argv is not None else sys.argv[1:]):
        return 0 if TARGET.read_text(encoding="utf-8") == text else 1
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
