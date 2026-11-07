"""Mock ERP: system-of-record reader over the `records` table. Reads use a fresh connection; writes live in the tools."""


class MockERP:
    def __init__(self, conn_factory):
        self._conn_factory = conn_factory
        self.stale_read = False  # read_record returns version-1 and a pre-approval status
        # callable(conn, record_id): runs inside the caller's transaction right before the tool applies.
        self.mutate_before_execute = None

    def _fetch(self, record_id: str) -> tuple[dict, int]:
        with self._conn_factory() as conn:
            row = conn.execute("SELECT data, version FROM records WHERE record_id = %s", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return row[0], row[1]

    def read_record(self, record_id: str) -> tuple[dict, int]:
        data, version = self._fetch(record_id)
        if self.stale_read:
            # No history is kept, so "old data" is approximated as the pre-approval state.
            if "status" in data:
                data = {**data, "status": "open"}
            return data, version - 1
        return data, version

    def sor_for(self, invoice_id: str) -> dict:
        """Authoritative values for verification: never taken from the agent (design.md)."""
        invoice, _ = self._fetch(f"invoice:{invoice_id}")
        po_id = invoice.get("po_id", _DEFAULT_PO.get(invoice_id))
        if po_id is None:
            raise KeyError(f"no po for invoice:{invoice_id}")
        po, _ = self._fetch(f"po:{po_id}")
        return {"po.total": po["total"], "vendor_id": invoice["vendor_id"]}

    def payment_sor(self, payment_id: str) -> dict:
        """The original payment a refund is checked against (ADR-009). KeyError if it does not exist."""
        p, _ = self._fetch(f"payment:{payment_id}")
        return {"customer_id": p["customer_id"], "refund_to": p["method_id"], "payment.amount": p["amount"]}


_DEFAULT_PO = {"INV-2048": "PO-2048"}
