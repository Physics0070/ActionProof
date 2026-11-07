"""Mock tool adapter for payments.approve_invoice (design.md "Tool adapter"). Plain class, in-process.

Well-behaved by default; each hostile switch is a plain attribute toggled by the tests.
The write runs on the caller's connection (the gate's transaction), never on its own.
"""

import time

from psycopg.types.json import Jsonb


class ToolError(Exception):
    """Raised by the mock tool. Messages carry no record data and no keys."""


class MockPayments:
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

    def sor_for(self, invoice_id: str) -> dict:
        return self._erp.sor_for(invoice_id)

    def dry_run(self, req) -> dict:
        return {"record_id": _record_id(req), "status": "open->approved", "amount": _amount(req)}

    def execute(self, req, expected_version: int, idempotency_key: str, conn) -> dict:
        if idempotency_key in self._results and not self.ignore_idempotency:
            return self._results[idempotency_key]
        record_id, amount = _record_id(req), _amount(req)
        if self._erp.mutate_before_execute is not None:
            self._erp.mutate_before_execute(conn, record_id)
        row = conn.execute("SELECT version FROM records WHERE record_id = %s FOR UPDATE", (record_id,)).fetchone()
        if row is None:
            raise ToolError("record not found")
        if not self.ignore_version and row[0] != expected_version:
            raise ToolError("version mismatch")
        for _ in range(2 if self.double_call else 1):
            conn.execute(
                "UPDATE records SET data = data || %s::jsonb, version = version + 1 WHERE record_id = %s",
                (Jsonb({"status": "approved"}), record_id),
            )
            self.calls.append({"idempotency_key": idempotency_key, "record_id": record_id,
                               "amount": amount, "ts": int(time.time())})
        if self.fail_after_effect:
            raise ToolError("tool failed after effect")
        version = conn.execute("SELECT version FROM records WHERE record_id = %s", (record_id,)).fetchone()[0]
        result = {"record_id": record_id, "status": "approved", "amount": amount, "version": version}
        self._results[idempotency_key] = result
        return result


def _record_id(req) -> str:
    return f"invoice:{_claim(req, 'invoice_id')}"


def _amount(req) -> str:
    return _claim(req, "amount")


def _claim(req, name: str) -> str:
    claim = req.args.get(name)
    if claim is None:
        raise ValueError(f"missing {name}")
    return claim.value
