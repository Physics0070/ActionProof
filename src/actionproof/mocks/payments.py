"""Mock tool adapter for payments.approve_invoice (design.md "Tool adapter"). Plain class, in-process.

Well-behaved by default; each hostile switch is a plain attribute toggled by the tests.
The write runs on the caller's connection (the gate's transaction), never on its own.
"""

import hashlib
import json
import time

from psycopg.types.json import Jsonb

from actionproof import evidence
from actionproof.journal import DefiniteFailure


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
        # ADR-035 evidence: the signer is a test key (tests/fixtures); None = this adapter can prove nothing, so
        # its declines are UNKNOWN and its lookups are no evidence. decline_reason: reject with no effect.
        self.evidence_signer = None
        self.decline_reason: str | None = None
        self.window_seconds = 0                    # after this long the provider will never apply a seen key
        self.seen: dict[str, dict] = {}            # provider-side: requests received {key: {ts, record_id, amount}}
        self.effects: set[str] = set()             # provider-side: keys whose effect was applied

    def read_record(self, record_id: str) -> tuple[dict, int]:
        return self._erp.read_record(record_id)

    def sor_for(self, invoice_id: str) -> dict:
        return self._erp.sor_for(invoice_id)

    def dry_run(self, req) -> dict:
        return {"record_id": _record_id(req), "status": "open->approved", "amount": _amount(req)}

    def execute(self, req, expected_version: int, idempotency_key: str, conn) -> dict:
        if idempotency_key in self._results and not self.ignore_idempotency:
            return self._results[idempotency_key]
        self._saw(req, idempotency_key)
        if self.decline_reason is not None:
            env = self._sign("execute", idempotency_key, "NOT_APPLIED", reason=self.decline_reason)
            raise DefiniteFailure("declined; nothing applied", evidence=env)
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
            self.effects.add(idempotency_key)
        if self.fail_after_effect:
            raise ToolError("tool failed after effect")
        version = conn.execute("SELECT version FROM records WHERE record_id = %s", (record_id,)).fetchone()[0]
        result = {"record_id": record_id, "status": "approved", "amount": amount, "version": version}
        self._results[idempotency_key] = result
        return result

    def lookup(self, idempotency_key: str):
        """Read-only status by idempotency key (ADR-035): a signed APPLIED / NOT_APPLIED statement, or None when the
        provider never saw the key or cannot sign. Never applies anything."""
        if idempotency_key not in self.seen or self.evidence_signer is None:
            return None
        if idempotency_key in self.effects:
            return self._sign("lookup", idempotency_key, "APPLIED",
                              provider_ref="mock-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:12])
        return self._sign("lookup", idempotency_key, "NOT_APPLIED", reason="NOT_FOUND",
                          window_closes_at=self.seen[idempotency_key]["ts"] + self.window_seconds)

    def _saw(self, req, idempotency_key: str) -> None:
        self.seen.setdefault(idempotency_key, {"ts": int(time.time()), "record_id": _record_id(req),
                                               "amount": _amount(req)})

    def _sign(self, op: str, idempotency_key: str, status: str, **kw):
        if self.evidence_signer is None:
            return None
        s = self.seen[idempotency_key]
        vendor = str(self._erp.read_record(s["record_id"])[0].get("vendor_id"))
        response = json.dumps({"key": idempotency_key, "status": status, **kw}, sort_keys=True).encode()
        return self.evidence_signer.sign(evidence.statement(op, idempotency_key, status, s["amount"], vendor,
                                                            response, **kw))


def _record_id(req) -> str:
    return f"invoice:{_claim(req, 'invoice_id')}"


def _amount(req) -> str:
    return _claim(req, "amount")


def _claim(req, name: str) -> str:
    claim = req.args.get(name)
    if claim is None:
        raise ValueError(f"missing {name}")
    return claim.value
