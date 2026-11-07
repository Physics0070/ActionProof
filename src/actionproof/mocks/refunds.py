"""Mock tool adapter for payments.refund_payment (ADR-009). Same contract and hostile switches as MockPayments.

A payment lives in `records` as kind 'payment' ({customer_id, amount, method_id, status}); a refund adds to its
`refunded` total and bumps the version. The write runs on the caller's connection (the gate's transaction).
"""

import time
from decimal import Decimal

from psycopg.types.json import Jsonb

from actionproof.mocks.payments import ToolError, _claim


class MockRefunds:
    def __init__(self, erp, conn_factory):
        self._erp = erp
        self._conn_factory = conn_factory  # kept for the adapter contract; execute never opens a connection
        self.calls: list[dict] = []
        self._results: dict[str, dict] = {}
        self.ignore_version = False
        self.ignore_idempotency = False
        self.double_call = False
        self.fail_after_effect = False

    def read_record(self, record_id: str) -> tuple[dict, int]:
        return self._erp.read_record(record_id)

    def sor_for(self, payment_id: str) -> dict:
        return self._erp.payment_sor(payment_id)

    def dry_run(self, req) -> dict:
        return {"record_id": _record_id(req), "status": "captured->captured", "amount": _claim(req, "amount"),
                "refund_to": _claim(req, "refund_to")}

    def execute(self, req, expected_version: int, idempotency_key: str, conn) -> dict:
        if idempotency_key in self._results and not self.ignore_idempotency:
            return self._results[idempotency_key]
        record_id, amount, refund_to = _record_id(req), _claim(req, "amount"), _claim(req, "refund_to")
        if self._erp.mutate_before_execute is not None:
            self._erp.mutate_before_execute(conn, record_id)
        row = conn.execute("SELECT data, version FROM records WHERE record_id = %s FOR UPDATE", (record_id,)).fetchone()
        if row is None:
            raise ToolError("record not found")
        if not self.ignore_version and row[1] != expected_version:
            raise ToolError("version mismatch")
        refunded = Decimal(row[0].get("refunded", "0.00"))
        for _ in range(2 if self.double_call else 1):
            refunded += Decimal(amount)
            conn.execute("UPDATE records SET data = data || %s::jsonb, version = version + 1 WHERE record_id = %s",
                         (Jsonb({"refunded": str(refunded)}), record_id))
            self.calls.append({"idempotency_key": idempotency_key, "record_id": record_id, "amount": amount,
                               "refund_to": refund_to, "ts": int(time.time())})
        if self.fail_after_effect:
            raise ToolError("tool failed after effect")
        version = conn.execute("SELECT version FROM records WHERE record_id = %s", (record_id,)).fetchone()[0]
        result = {"record_id": record_id, "status": "captured", "amount": amount, "refund_to": refund_to,
                  "refunded": str(refunded), "version": version}
        self._results[idempotency_key] = result
        return result


def _record_id(req) -> str:
    return f"payment:{_claim(req, 'payment_id')}"
