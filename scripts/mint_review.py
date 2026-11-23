"""Park one fresh REVIEW and print {"request_hash": ...}: python scripts/mint_review.py

For e2e and demos (docker compose exec -T api /app/docker/entrypoint.sh python scripts/mint_review.py). Every call seeds
its OWN invoice, purchase order and vendor (so approving one never spends the cap or the invoice of the next), prepares
the request through the real gate and parks it exactly like the MCP server. The invoice is 300.00 against a 100.00 PO
(variance 200.00 -> AP-INV-04 REVIEW). Needs the demo seed (people, delegation) and the signing key. Not tool-facing.
"""
import hashlib
import json
import secrets
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from psycopg.types.json import Jsonb  # noqa: E402

from actionproof import review, server  # noqa: E402
from actionproof.config import ConfigError, load_settings  # noqa: E402
from actionproof.contracts import parse_request  # noqa: E402
from actionproof.gate import Principal  # noqa: E402

TOTAL, PO_TOTAL = "300.00", "100.00"


def _claim(doc_id: str, blob: bytes, key: str, value: str) -> dict:
    return {"value": value, "claim": "DIRECT", "src": {"doc": doc_id, "pointer": f"/{key}"},
            "doc_sha256": hashlib.sha256(blob).hexdigest()}


if __name__ == "__main__":
    try:
        app = server.build_app(load_settings(), server.load_server_settings(need_principal=False))
    except ConfigError as e:
        sys.exit(f"ConfigError: {e}")
    tag = secrets.token_hex(5).upper()
    inv, po, vendor = f"E2E-{tag}", f"PO-E2E-{tag}", f"V-E2E-{tag}"
    with app._conn_factory() as conn:
        conn.execute("INSERT INTO records (record_id, kind, data, version) VALUES (%s, 'invoice', %s, 1)",
                     (f"invoice:{inv}", Jsonb({"vendor_id": vendor, "total": TOTAL, "status": "open", "po_id": po})))
        conn.execute("INSERT INTO records (record_id, kind, data, version) VALUES (%s, 'po', %s, 1)",
                     (f"po:{po}", Jsonb({"vendor_id": vendor, "total": PO_TOTAL})))
        conn.execute("UPDATE delegations SET vendors = array_append(vendors, %s) "
                     "WHERE on_behalf_of = 'user-123' AND NOT (%s = ANY(vendors))", (vendor, vendor))
        conn.commit()
    doc_id = f"export-{inv}.json"
    blob = json.dumps({"invoice_id": inv, "total": TOTAL}, sort_keys=True).encode()
    variance = str((Decimal(TOTAL) - Decimal(PO_TOTAL)).quantize(Decimal("0.01")))
    req = parse_request({
        "tool": "payments.approve_invoice", "on_behalf_of": "user-123", "actor": "agent-7",
        "idempotency_key": f"e2e-{secrets.token_hex(6)}",
        "args": {
            "invoice_id": _claim(doc_id, blob, "invoice_id", inv),
            "amount": _claim(doc_id, blob, "total", TOTAL),
            "invoice.total": _claim(doc_id, blob, "total", TOTAL),
            "variance": {"value": variance, "claim": "DERIVED", "fn": "sub", "inputs": ["invoice.total", "po.total"]},
        },
    })
    res = app.gate.prepare(req, {doc_id: blob}, principal=Principal("agent-7", "user-123"))
    if res.decision != "REVIEW":
        sys.exit(f"expected REVIEW, got {res.decision}: {[r.rule for r in res.reasons]}; is the demo seeded (DEMO_SEED=1)?")
    review.park(app._conn_factory, req, res.receipt, res.reasons, res=res)
    print(json.dumps({"request_hash": res.receipt["payload"]["request_hash"]}))
