"""Hero scenario helpers (deck slide 4) shared by tests, e2e and the demo."""

import json
from pathlib import Path

from actionproof.contracts import ActionRequest

OUT = Path(__file__).resolve().parent / "out"
MANIFEST = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))


def load_docs() -> dict[str, bytes]:
    return {doc_id: (OUT / d["path"]).read_bytes() for doc_id, d in MANIFEST["docs"].items()}


def hero_sor() -> dict:
    return {"po.total": "4300.00", "vendor_id": "V-ACME"}


def pdf_claim(doc_id: str, field: str, value: str | None = None) -> dict:
    d = MANIFEST["docs"][doc_id]
    f = d["fields"][field]
    src = {"doc": doc_id, "page": f["page"], "bbox": f["bbox"]}
    return {"value": value or f["value"], "claim": "DIRECT", "src": src, "doc_sha256": d["sha256"]}


def json_claim(doc_id: str, field: str, value: str | None = None) -> dict:
    d = MANIFEST["docs"][doc_id]
    f = d["fields"][field]
    return {"value": value or f["value"], "claim": "DIRECT", "src": {"doc": doc_id, "pointer": f["pointer"]}, "doc_sha256": d["sha256"]}


def hero_request(idempotency_key: str = "idem-1") -> ActionRequest:
    inv, po = MANIFEST["hero"]["invoice"], MANIFEST["hero"]["po"]
    return ActionRequest.model_validate(
        {
            "tool": "payments.approve_invoice",
            "on_behalf_of": "user-123",
            "actor": "agent-7",
            "idempotency_key": idempotency_key,
            "args": {
                "invoice_id": pdf_claim(inv, "invoice_id"),  # targets invoice:INV-2048 in the system of record
                "amount": pdf_claim(inv, "total"),
                "invoice.total": pdf_claim(inv, "total"),
                "po.total": json_claim(po, "total"),
                "variance": {"value": MANIFEST["hero"]["variance"], "claim": "DERIVED", "fn": "sub", "inputs": ["invoice.total", "po.total"]},
                "note": {"value": "vendor says urgent", "claim": "ASSERTED", "taint": "doc"},
            },
        }
    )
