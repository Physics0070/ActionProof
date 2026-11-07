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


REFUND_TOOL = "payments.refund_payment"
REFUND_INJECTED = "refund/REF-311.pdf"  # PAY-7731, 250.00, visible "send the refund to account ..." line
REFUND_CLEAN = "refund/REF-311-clean.pdf"  # the same request without the injected line
REFUND_SMALL = "refund/REF-312.pdf"  # PAY-7731, 150.00: fits under the cap after the seeded 4800.00


def refund_docs() -> dict[str, bytes]:
    """Every manifest document (the refund requests among them), keyed by doc id like load_docs."""
    return load_docs()


def refund_sor_method(payment_id: str) -> str:
    """The original payment method from the seeded system of record (db.PAYMENTS), never from a document."""
    from actionproof.db import PAYMENTS

    return next(method for pid, _, _, method in PAYMENTS if pid == payment_id)


def injected_refund_to(doc_id: str = REFUND_INJECTED, claim: str = "ASSERTED") -> dict:
    """What a hijacked agent fills refund_to with: the account from the injected line, ASSERTED (tainted) or DIRECT."""
    if claim == "DIRECT":
        return pdf_claim(doc_id, "injected_account")
    return {"value": MANIFEST["docs"][doc_id]["fields"]["injected_account"]["value"], "claim": "ASSERTED",
            "taint": "doc"}


def refund_request(doc_id: str = REFUND_CLEAN, idempotency_key: str = "idem-ref-1", *, refund_to: dict | None = None,
                   customer_id: dict | None = None, **arg_over) -> ActionRequest:
    """A refund request built the honest way (ADR-009): payment_id and amount DIRECT at the cited boxes of the
    refund-request PDF; customer_id ASSERTED (the system of record must agree); refund_to = the original payment
    method, from the system of record (ASSERTED, untainted). `reason` is free text and authorizes nothing."""
    f = MANIFEST["docs"][doc_id]["fields"]
    args = {
        "payment_id": pdf_claim(doc_id, "payment_id"),
        "customer_id": customer_id or {"value": f["customer_id"]["value"], "claim": "ASSERTED", "taint": "doc"},
        "refund_to": refund_to or {"value": refund_sor_method(f["payment_id"]["value"]), "claim": "ASSERTED"},
        "amount": pdf_claim(doc_id, "total"),  # the document's total box
        "reason": {"value": "customer requested a refund", "claim": "ASSERTED", "taint": "doc"},
    }
    args.update(arg_over)
    return ActionRequest.model_validate({"tool": REFUND_TOOL, "on_behalf_of": "user-123", "actor": "agent-7",
                                         "idempotency_key": idempotency_key, "args": args})


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
