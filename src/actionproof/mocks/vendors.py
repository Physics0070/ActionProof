"""Mock vendor master: bank details live in `records` (kind 'vendor'). Used by the second connector."""

import time

from psycopg.types.json import Jsonb


class MockVendorMaster:
    def __init__(self, conn_factory):
        self._conn_factory = conn_factory
        self.calls: list[dict] = []  # one entry per change_bank execution

    def bank_last4(self, vendor_id: str) -> str | None:
        with self._conn_factory() as conn:
            row = conn.execute("SELECT data->>'bank_last4' FROM records WHERE record_id = %s",
                               (f"vendor:{vendor_id}",)).fetchone()
        return row[0] if row else None

    def set_bank(self, vendor_id: str, last4: str) -> None:
        """Setup helper: seeds or overwrites bank details without recording a tool call."""
        self._write(vendor_id, last4)

    def change_bank(self, vendor_id: str, last4: str) -> None:
        self._write(vendor_id, last4)
        self.calls.append({"vendor_id": vendor_id, "last4": last4, "ts": int(time.time())})

    def _write(self, vendor_id: str, last4: str) -> None:
        with self._conn_factory() as conn:
            conn.execute(
                "INSERT INTO records (record_id, kind, data, version) VALUES (%s, 'vendor', %s, 1) "
                "ON CONFLICT (record_id) DO UPDATE SET data = EXCLUDED.data, version = records.version + 1",
                (f"vendor:{vendor_id}", Jsonb({"bank_last4": last4})),
            )
