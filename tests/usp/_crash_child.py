"""Child process for the genuine-termination test, and the downstream it talks to.

The downstream's side-effect log is a FILE (append + fsync), so it is independent of the database, of the gate and of
the process: it survives the child being killed. Run as a script: reads {receipt, request} JSON, commits through a real
Gate on the real database, and the tool terminates the whole process with os._exit right after its effect is logged
(no Python cleanup, the OS drops the Postgres connection): a hard crash after the money moved.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from actionproof.mocks import MockPayments  # noqa: E402


class FilePSP(MockPayments):
    """Downstream with a durable file log and NO idempotency (the hard case). crash=True kills the process after it."""

    def __init__(self, erp, factory, log_path, crash=False):
        super().__init__(erp, factory)
        self.log_path, self.crash = Path(log_path), crash

    def execute(self, req, expected_version, idempotency_key, conn):
        fd = os.open(self.log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0))
        try:
            os.write(fd, (idempotency_key + "\n").encode())  # the money moves
            os.fsync(fd)
        finally:
            os.close(fd)
        result = super().execute(req, expected_version, idempotency_key, conn)
        if self.crash:
            os._exit(137)
        return result

    def effects(self) -> list[str]:
        return self.log_path.read_text().splitlines() if self.log_path.exists() else []


def main(payload_path: str, log_path: str) -> int:
    from actionproof import db
    from actionproof.config import load_settings
    from actionproof.gate import Gate, Principal
    from actionproof.mocks import MockERP
    from actionproof.signing import Signer

    settings = load_settings()
    signer = Signer.from_path(settings.signing_key_path, settings.signing_kid)

    def factory():
        return db.connect(url=settings.database_url)

    psp = FilePSP(MockERP(factory), factory, log_path, crash=True)
    gate = Gate(settings, signer, factory, {"payments.approve_invoice": psp})
    p = json.loads(Path(payload_path).read_text())
    gate.commit(p["receipt"], p["request"], principal=Principal("agent-7", "user-123"))
    return 0  # only reached if the tool did not crash the process


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
