"""policy.decide against the real OPA binary (no Docker), plus fail-closed stubs."""

import copy
import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from actionproof.policy import Decision, decide

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 0.2  # Settings.opa_timeout_seconds default
OPA_BIN = os.environ.get("OPA_BIN", "C:/Users/Soham/tools/opa/opa.exe")

HERO = {
    "tool": "payments.approve_invoice",
    "actor": "agent-7",
    "on_behalf_of": "user-123",
    "verify": {"ok": True, "reasons": []},
    "args": {"amount": "4800.00", "variance": "500.00", "vendor_id": "V-ACME"},
    "scope": {"max_amount": "5000.00", "vendors": ["V-ACME"]},
    "cumulative": {"committed": "0.00"},
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def opa_url(tmp_path_factory):
    port = _free_port()
    # Logs go to a file, never a PIPE: an unread pipe fills up and blocks OPA mid-request.
    log = tmp_path_factory.mktemp("opa") / "opa.log"
    log_f = log.open("wb")
    proc = subprocess.Popen(
        [OPA_BIN, "run", "--server", "--log-level", "error", "--disable-telemetry",
         "--addr", f"127.0.0.1:{port}", str(ROOT / "policy")],
        stdout=log_f,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if proc.poll() is not None:
                raise RuntimeError(f"OPA exited: {log.read_text(errors='replace')}")
            try:
                if httpx.get(f"{url}/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("OPA did not become healthy")
        # warm up so the first measured decide() is not paying OPA's compile cost
        httpx.post(f"{url}/v1/data/actionproof/decision", json={"input": HERO}, timeout=5)
        yield url
    finally:
        proc.kill()
        proc.wait()
        log_f.close()


@pytest.fixture
def opa(opa_url):
    return opa_url


def patched(**sections) -> dict:
    p = copy.deepcopy(HERO)
    for k, v in sections.items():
        p[k] = {**p[k], **v} if isinstance(v, dict) else v
    return p


def rules(d: Decision) -> set[str]:
    return {r.rule for r in d.reasons}


def test_hero_review_inv04(opa):
    d = decide(HERO, opa, TIMEOUT)
    assert d.outcome == "REVIEW"
    assert [(r.rule, r.guarantee) for r in d.reasons] == [("AP-INV-04", "G1")]


def test_allow_when_variance_within_limit(opa):
    assert decide(patched(args={"variance": "100.00"}), opa, TIMEOUT) == Decision("ALLOW", [])


def test_ver01_verification_failed(opa):
    d = decide(patched(verify={"ok": False}), opa, TIMEOUT)
    assert d.outcome == "DENY" and "AP-VER-01" in rules(d)


def test_ver01_malformed_money(opa):
    d = decide(patched(args={"amount": "4800"}), opa, TIMEOUT)
    assert d.outcome == "DENY" and rules(d) == {"AP-VER-01"}


def test_ver01_empty_input(opa):
    assert decide({}, opa, TIMEOUT).outcome == "DENY"


def test_scope02_amount_over_max(opa):
    d = decide(patched(args={"amount": "5000.01", "variance": "0.00"}), opa, TIMEOUT)
    assert d.outcome == "DENY" and "AP-SCOPE-02" in rules(d)


def test_scope02_vendor_out_of_scope(opa):
    d = decide(patched(args={"vendor_id": "V-EVIL"}), opa, TIMEOUT)
    assert d.outcome == "DENY" and rules(d) == {"AP-SCOPE-02"}


def test_cum03_over_cap(opa):
    d = decide(patched(args={"amount": "4900.00", "variance": "0.00"}, cumulative={"committed": "4900.00"}), opa, TIMEOUT)
    assert d.outcome == "DENY" and rules(d) == {"AP-CUM-03"}
    assert all(r.guarantee == "G1" for r in d.reasons)


def test_float_in_payload_denied_before_opa(opa):
    d = decide(patched(args={"amount": 4800.0}), opa, TIMEOUT)
    assert d == Decision("DENY", [d.reasons[0]]) and rules(d) == {"AP-POL-FAIL"}


def test_missing_opa_url_denied():
    assert rules(decide(HERO, "", TIMEOUT)) == {"AP-POL-FAIL"}


def test_closed_port_denied():
    d = decide(HERO, f"http://127.0.0.1:{_free_port()}", TIMEOUT)
    assert d.outcome == "DENY" and rules(d) == {"AP-POL-FAIL"}


def _stub(handler_body):
    """Start a local HTTP stub; handler_body(handler) writes the response."""

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            handler_body(self)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _reply(status: int, body: bytes):
    def write(h):
        h.send_response(status)
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)

    return write


def test_slow_server_denied():
    ok = json.dumps({"result": {"outcome": "ALLOW", "reasons": []}}).encode()

    def slow(h):
        time.sleep(1)
        _reply(200, ok)(h)

    srv, url = _stub(slow)
    try:
        t0 = time.monotonic()
        d = decide(HERO, url, TIMEOUT)
        assert d.outcome == "DENY" and rules(d) == {"AP-POL-FAIL"}
        assert time.monotonic() - t0 < 0.9
    finally:
        srv.shutdown()


def test_trickling_server_denied():
    def trickle(h):
        h.send_response(200)
        h.send_header("Content-Length", "100")
        h.end_headers()
        for _ in range(100):
            h.wfile.write(b" ")
            h.wfile.flush()
            time.sleep(0.05)

    srv, url = _stub(trickle)
    try:
        t0 = time.monotonic()
        assert rules(decide(HERO, url, TIMEOUT)) == {"AP-POL-FAIL"}
        assert time.monotonic() - t0 < 0.9
    finally:
        srv.shutdown()


@pytest.mark.parametrize(
    "status,body",
    [
        (500, b'{"result": {"outcome": "ALLOW", "reasons": []}}'),
        (200, b"not json"),
        (200, b"{}"),
        (200, b'{"result": {}}'),
        (200, b'{"result": {"outcome": "MAYBE", "reasons": []}}'),
        (200, b'{"result": {"outcome": "ALLOW"}}'),
        (200, b'{"result": {"outcome": "REVIEW", "reasons": []}}'),
        (200, b'{"result": {"outcome": "DENY", "reasons": [{"rule": "X", "guarantee": "G9", "msg": "m"}]}}'),
        (200, b'{"result": {"outcome": "REVIEW", "reasons": ["AP-INV-04"]}}'),
    ],
)
def test_malformed_opa_response_denied(status, body):
    srv, url = _stub(_reply(status, body))
    try:
        d = decide(HERO, url, TIMEOUT)
        assert d.outcome == "DENY" and rules(d) == {"AP-POL-FAIL"}
    finally:
        srv.shutdown()
