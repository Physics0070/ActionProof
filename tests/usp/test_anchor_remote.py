"""USP G1/G2 (ADR-030): remote append-only checkpoint anchor + asynchronous publisher/monitor.

Every test runs against `StubAnchorServer`, a STUB written for these tests (an in-process http.server on loopback).
It is NOT an append-only / WORM provider and proves nothing about one: the HTTP adapter is UNVERIFIED against any
real provider. What these tests do prove is the client side: signatures re-verified through the KeyRegistry,
idempotent and strictly ordered publication, conflict / rollback / gap / rewind detection, inclusion in the local
chain, lag reporting, in-order recovery, and that no HTTP request is ever made while a database transaction is open.
"""
import ast
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
import rfc8785

from actionproof import anchor, audit
from actionproof import anchor_publisher as ap
from actionproof import db as dbmod
from actionproof import signing
from actionproof.anchor_remote import HttpAnchor
from actionproof.signing import Signer

TOKEN = "stub-anchor-token-" + "q" * 24
SRC = Path(__file__).resolve().parents[2] / "src" / "actionproof"


class StubAnchorServer:
    """STUB for tests only: an append-only checkpoint store speaking the HttpAnchor protocol over loopback HTTP.
    Not WORM, not a provider. `store` may be edited directly to play a compromised or rolled-back remote.
    Two independent streams (ADR-034): the audit stream at /checkpoints (attributes on the stub itself) and the
    execution-journal stream at /journal/checkpoints (the same attributes on `stub.journal`). `down`/`puts` are shared."""

    def __init__(self, token: str = TOKEN):
        self.store: dict[int, dict] = {}
        self.accepted: list[int] = []      # seqs in the order they were appended
        self.puts = 0
        self.down = False                  # every request answers 503
        self.fail_after: int | None = None  # after this many appends, PUT answers 503
        self.listing: list | None = None   # override the GET body (a lying remote)
        self.journal = SimpleNamespace(store={}, accepted=[], fail_after=None, listing=None)
        self.order: list[tuple[str, int]] = []  # (stream, seq) of every append, across both streams
        lock, stub = threading.Lock(), self

        def stream(path):
            return ("journal", stub.journal, path[len("/journal"):]) if path.startswith("/journal/") \
                else ("audit", stub, path)

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=None):
                raw = json.dumps(body if body is not None else {}).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _ok(self):
                if stub.down:
                    self._send(503)
                    return False
                if self.headers.get("Authorization") != f"Bearer {token}":
                    self._send(401)
                    return False
                return True

            def do_GET(self):
                if not self._ok():
                    return
                _, st, path = stream(self.path)
                if path != "/checkpoints":
                    return self._send(404)
                with lock:
                    body = st.listing if st.listing is not None else [st.store[s] for s in sorted(st.store)]
                self._send(200, {"checkpoints": body})

            def do_PUT(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if not self._ok():
                    return
                stub.puts += 1
                name, st, path = stream(self.path)
                parts = path.split("/")
                try:
                    seq = int(parts[2])
                    ok = len(parts) == 3 and parts[1] == "checkpoints" and body["payload"]["seq"] == seq
                except (IndexError, ValueError, KeyError, TypeError):
                    ok = False
                if not ok:
                    return self._send(400)
                with lock:
                    if seq in st.store:
                        return self._send(200 if rfc8785.dumps(st.store[seq]) == rfc8785.dumps(body) else 409)
                    if st.store and seq < max(st.store):
                        return self._send(409)
                    if st.fail_after is not None and len(st.accepted) >= st.fail_after:
                        return self._send(503)
                    st.store[seq] = body
                    st.accepted.append(seq)
                    stub.order.append((name, seq))
                self._send(201)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def signer(signing_key_path):
    return Signer.from_path(signing_key_path, "k1")


@pytest.fixture
def stub():
    s = StubAnchorServer()
    yield s
    s.close()


def _registry(tmp_path, keys: dict) -> Path:
    p = tmp_path / f"registry-{len(list(tmp_path.glob('registry-*')))}.json"
    p.write_text(json.dumps({"keys": {k: {"pub": pub, "status": st} for k, (pub, st) in keys.items()}}))
    return p


def _env(pg, signer, stub, tmp_path, **over):
    e = {"DATABASE_URL": pg, "KEY_REGISTRY_PATH": str(_registry(tmp_path, {"k1": (signer.public_key_b64(), "active")})),
         "ANCHOR_REMOTE_URL": stub.url, "ANCHOR_REMOTE_TOKEN": TOKEN,
         "ANCHOR_STATE_PATH": str(tmp_path / "state.json"), "ANCHOR_MAX_LAG_SECONDS": "300",
         "ANCHOR_REMOTE_TIMEOUT_SECONDS": "2"}
    e.update(over)
    return e


@pytest.fixture
def cfg(pg, signer, stub, tmp_path):
    return ap.load_settings(_env(pg, signer, stub, tmp_path))


def _entries(conn, signer, n, tag=0):
    for i in range(n):
        audit.append(conn, "test", decision="ALLOW", rules=[], detail={"i": i, "tag": tag})
        audit.checkpoint(conn, signer)
        conn.commit()


def _db_checkpoints(db):
    rows = db.execute("SELECT seq, head_hash, ts, sig, kid FROM audit_checkpoints ORDER BY seq").fetchall()
    db.commit()
    return [{"payload": {"seq": r[0], "head_hash": r[1], "ts": r[2]}, "sig": r[3], "kid": r[4]} for r in rows]


def _cycle(cfg, publish=True, now=None, **kw):
    remote, reg = ap.build(cfg, **kw)
    return ap.cycle(cfg, remote, reg, publish=publish, now=now)


def _tamper(pg, *statements):
    with dbmod.connect(url=pg) as su:
        su.execute("SET session_replication_role = replica")
        for q in statements:
            su.execute(q)


# ---- publication: idempotent, strictly ordered, conflicts refused

def test_publish_is_idempotent_and_strictly_ordered(db, signer, stub, cfg):
    _entries(db, signer, 3)
    code, lines = _cycle(cfg)
    assert code == 0, lines
    assert stub.accepted == [1, 2, 3]
    assert _cycle(cfg)[0] == 0 and stub.accepted == [1, 2, 3]          # re-run: nothing new appended
    remote, reg = ap.build(cfg)
    assert remote.publish(_db_checkpoints(db)[2], reg) is False         # same checkpoint again: no-op
    _entries(db, signer, 2)
    assert _cycle(cfg)[0] == 0 and stub.accepted == [1, 2, 3, 4, 5]
    assert all(set(e) == {"payload", "sig", "kid"} for e in stub.store.values())  # only the signed envelope leaves


def test_conflicting_head_at_existing_seq_is_refused_and_flagged(db, signer, stub, cfg):
    _entries(db, signer, 3)
    assert _cycle(cfg)[0] == 0
    remote, reg = ap.build(cfg)
    forged = signer.sign({"seq": 3, "head_hash": "f" * 64, "ts": int(time.time())})  # validly signed, other head
    held = dict(stub.store[3])
    with pytest.raises(anchor.AnchorError, match="refused"):
        remote.publish(forged, reg)
    assert stub.store[3] == held
    stub.store[3] = forged                                               # a remote that accepted it anyway
    code, lines = _cycle(cfg, publish=False)
    assert code == 1 and any("seq 3" in x and "conflicting" in x for x in lines), lines


def test_remote_must_be_strictly_increasing_and_never_accepts_older(db, signer, stub, cfg):
    _entries(db, signer, 3)
    cps = _db_checkpoints(db)
    remote, reg = ap.build(cfg)
    assert remote.publish(cps[0], reg) and remote.publish(cps[2], reg)
    with pytest.raises(anchor.AnchorError):                              # seq 2 after head 3: not appendable
        remote.publish(cps[1], reg)
    stub.listing = [cps[1], cps[0]]                                      # a remote listing out of order
    with pytest.raises(anchor.AnchorError, match="strictly increasing"):
        remote.entries(reg)
    stub.listing = [cps[0], cps[0]]
    with pytest.raises(anchor.AnchorError, match="strictly increasing"):
        remote.entries(reg)


# ---- verification against the local chain

def test_inclusion_verified_and_rewritten_history_detected(db, pg, signer, stub, cfg):
    _entries(db, signer, 4)
    assert _cycle(cfg)[0] == 0
    code, lines = _cycle(cfg, publish=False)
    assert code == 0 and "through seq 4" in lines[0] and "included in the local chain" in lines[0], lines
    _tamper(pg, "TRUNCATE audit_checkpoints, audit_log")                # consistent rewrite, real key
    _entries(db, signer, 4, tag=1)
    for publish in (True, False):
        code, lines = _cycle(cfg, publish=publish)
        assert code == 1 and any("conflicting" in x for x in lines), lines
    assert stub.accepted == [1, 2, 3, 4]                                 # nothing republished over it


def test_remote_rollback_is_detected(db, signer, stub, cfg):
    _entries(db, signer, 5)
    assert _cycle(cfg)[0] == 0                                           # state: verified through seq 5
    del stub.store[5], stub.store[4]                                     # remote restored to an older state
    code, lines = _cycle(cfg, publish=False)
    assert code == 1 and any("rolled back" in x and "seq 5" in x for x in lines), lines
    code, lines = _cycle(cfg)                                            # the publisher refuses to paper over it
    assert code == 1 and 4 not in stub.store


def test_local_chain_rewound_is_detected(db, pg, signer, stub, cfg):
    _entries(db, signer, 5)
    assert _cycle(cfg)[0] == 0
    _tamper(pg, "DELETE FROM audit_checkpoints WHERE seq >= 4", "DELETE FROM audit_log WHERE seq >= 4")
    assert audit.run_verify(pg, signer.public_key_b64())[0] == 0        # the database alone is blind to it
    code, lines = _cycle(cfg, publish=False)
    assert code == 1 and any("rewound" in x for x in lines), lines


def test_gap_in_the_remote_sequence_is_detected(db, signer, stub, cfg, tmp_path):
    _entries(db, signer, 5)
    assert _cycle(cfg)[0] == 0
    del stub.store[2]
    code, lines = _cycle(cfg, publish=False)
    assert code == 1 and any("missing checkpoint seq 2" in x for x in lines), lines
    fresh = cfg.model_copy(update={"anchor_state_path": str(tmp_path / "other-state.json")})
    assert _cycle(fresh, publish=False)[0] == 1                          # detected without any saved state too


# ---- lag and recovery

def test_lag_beyond_threshold_reports_and_exits_nonzero(db, signer, stub, cfg):
    _entries(db, signer, 2)                                              # never published
    code, lines = _cycle(cfg, publish=False)
    assert code == 0 and any("unpublished seq 1..2" in x and "within" in x for x in lines), lines
    code, lines = _cycle(cfg, publish=False, now=time.time() + 1000)
    assert code == 1 and any(x.startswith("anchor-remote: LAG") for x in lines), lines
    stub.down = True                                                     # publisher cannot reach the remote
    code, lines = _cycle(cfg, now=time.time() + 1000)
    assert code == 1 and any("LAG" in x for x in lines) and any("unreachable" in x or "503" in x for x in lines)
    code, lines = _cycle(cfg)                                            # unreachable but within the budget
    assert code == 0 and any("WARN" in x for x in lines), lines
    assert _cycle(cfg, publish=False)[0] == 1                            # check never passes without the remote


def test_unreachable_remote_recovers_in_order_without_skipping(db, signer, stub, cfg):
    _entries(db, signer, 2)
    assert _cycle(cfg)[0] == 0 and stub.accepted == [1, 2]
    stub.down = True
    _entries(db, signer, 3)
    assert _cycle(cfg)[0] == 0 and stub.accepted == [1, 2]              # backlog held, nothing skipped
    stub.down, stub.fail_after = False, 3                                # comes back, fails again mid-backlog
    _entries(db, signer, 1)
    code, lines = _cycle(cfg)
    assert code == 0 and stub.accepted == [1, 2, 3] and any("WARN" in x for x in lines), lines
    stub.fail_after = None
    assert _cycle(cfg)[0] == 0
    assert stub.accepted == [1, 2, 3, 4, 5, 6] == [c["payload"]["seq"] for c in _db_checkpoints(db)]
    assert _cycle(cfg, publish=False)[0] == 0


def test_a_closed_port_is_unreachable_not_an_integrity_failure(db, signer, pg, tmp_path):
    dead = StubAnchorServer()
    url = dead.url
    dead.close()                                                         # nothing listens there now
    cfg = ap.load_settings(_env(pg, signer, dead, tmp_path, ANCHOR_REMOTE_URL=url))
    _entries(db, signer, 1)
    code, lines = _cycle(cfg)
    assert code == 0 and any("unreachable" in x for x in lines), lines


# ---- transaction rule, signatures, independence from authorization

def test_no_http_request_while_a_database_transaction_is_open(db, signer, stub, cfg, monkeypatch):
    """Every HTTP request is checked: each connection the publisher opened must be closed or idle (no tx)."""
    opened, seen = [], []
    real = psycopg.connect

    def tracked(*a, **kw):
        c = real(*a, **kw)
        opened.append(c)
        return c

    def guard(request):
        seen.append(request.method)
        assert all(c.closed or c.info.transaction_status == psycopg.pq.TransactionStatus.IDLE for c in opened), \
            f"HTTP {request.method} while a database transaction is open"

    monkeypatch.setattr(ap.psycopg, "connect", tracked)
    _entries(db, signer, 3)
    hooks = {"request": [guard]}
    assert _cycle(cfg, event_hooks=hooks)[0] == 0
    assert _cycle(cfg, publish=False, event_hooks=hooks)[0] == 0
    assert opened and seen.count("PUT") == 3 and "GET" in seen
    # control: the guard really fires when a transaction is open
    c = tracked(cfg.database_url.get_secret_value())
    c.execute("SELECT 1")
    remote, reg = ap.build(cfg, event_hooks=hooks)
    with pytest.raises(AssertionError, match="transaction is open"):
        remote.entries(reg)
    c.close()


def test_signatures_are_verified_through_the_key_registry(db, signer, stub, cfg, tmp_path):
    _entries(db, signer, 2)
    assert _cycle(cfg)[0] == 0
    other = tmp_path / "other.key"
    signing.generate_key(other)
    k2 = Signer.from_path(other, "k2")
    revoked = _registry(tmp_path, {"k1": (signer.public_key_b64(), "revoked"), "k2": (k2.public_key_b64(), "active")})
    rcfg = cfg.model_copy(update={"key_registry_path": str(revoked)})
    code, lines = _cycle(rcfg, publish=False)                            # k1 revoked: its checkpoints stop verifying
    assert code == 1 and any("signature invalid or kid unknown" in x for x in lines), lines
    remote, reg = ap.build(cfg)
    puts = stub.puts
    for bad in (k2.sign({"seq": 3, "head_hash": "a" * 64, "ts": 1}),     # unknown kid k2 under cfg's registry
                {**_db_checkpoints(db)[1], "sig": "AAAA"}):              # broken signature
        with pytest.raises(anchor.AnchorError):
            remote.publish(bad, reg)
    assert stub.puts == puts                                             # refused before any request was sent
    stub.store[2] = {**stub.store[2], "sig": "AAAA"}                     # a remote serving a forged entry
    assert _cycle(cfg, publish=False)[0] == 1


def test_remote_failure_never_blocks_or_alters_authorization(kit, signer, stub, cfg):
    """The Gate imports nothing of the publisher; a dead remote changes no decision; the publisher never writes."""
    for mod in ("gate.py", "server.py", "audit.py", "policy.py", "console.py", "mcp_server.py"):
        p = SRC / mod
        if not p.exists():
            continue
        names = {n.module or "" for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
                 if isinstance(n, ast.ImportFrom)}
        names |= {a.name for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
                  if isinstance(n, ast.Import) for a in n.names}
        assert not any("anchor_remote" in x or "anchor_publisher" in x for x in names), mod
        assert "anchor_remote" not in p.read_text(encoding="utf-8") and "anchor_publisher" not in p.read_text(
            encoding="utf-8"), mod
    stub.down = True
    counts = kit.sql("SELECT (SELECT count(*) FROM audit_log), (SELECT count(*) FROM audit_checkpoints)")[0]
    _cycle(cfg)
    _cycle(cfg, publish=False)
    assert kit.sql("SELECT (SELECT count(*) FROM audit_log), (SELECT count(*) FROM audit_checkpoints)")[0] == counts
    req, docs = kit.json_request("INV-7301", "100.00")
    r = kit.gate.prepare(req, docs)
    assert r.receipt is not None, r.reasons
    assert kit.gate.commit(r.receipt, req).outcome == "EXECUTED" and kit.executes == 1


def test_publisher_holds_no_signing_key():
    assert "signing_key_path" not in ap.PublisherSettings.model_fields
    for mod in ("anchor_remote.py", "anchor_publisher.py"):
        text = (SRC / mod).read_text(encoding="utf-8")
        assert "Signer" not in text and "SIGNING_KEY" not in text and "signing_key" not in text, mod


# ---- configuration and CLI

def test_settings_are_validated_and_never_echo_secrets(pg, signer, stub, tmp_path):
    base = _env(pg, signer, stub, tmp_path)
    bad = {
        "ANCHOR_REMOTE_URL": ["http://anchor.example.com", "https://user:pw@anchor.example.com", "ftp://x",
                              "https://anchor.example.com/?k=v", ""],
        "ANCHOR_REMOTE_TOKEN": ["", "short"],
        "ANCHOR_MAX_LAG_SECONDS": ["0", "-5", "abc"],
        "ANCHOR_REMOTE_TIMEOUT_SECONDS": ["0", "nan"],
        "ANCHOR_STATE_PATH": [" "],
    }
    for var, values in bad.items():
        for v in values:
            with pytest.raises(ap.ConfigError) as e:
                ap.load_settings({**base, var: v})
            assert var in str(e.value) and TOKEN not in str(e.value)
    for var in ("ANCHOR_REMOTE_URL", "ANCHOR_REMOTE_TOKEN", "ANCHOR_STATE_PATH", "KEY_REGISTRY_PATH", "DATABASE_URL"):
        with pytest.raises(ap.ConfigError):
            ap.load_settings({k: v for k, v in base.items() if k != var})
    from urllib.parse import urlsplit
    d = urlsplit(pg)
    with pytest.raises(ap.ConfigError, match="separate trust domain"):   # anchor on the database server itself
        ap.load_settings({**base, "ANCHOR_REMOTE_URL": f"http://{d.hostname}:{d.port}"})
    s = ap.load_settings({**base, "ANCHOR_REMOTE_URL": "https://anchor.example.com/v1"})
    assert TOKEN not in repr(s) and TOKEN not in str(s)


def test_cli_once_check_run_and_config_error(db, pg, signer, stub, tmp_path, capsys):
    _entries(db, signer, 3)
    env = _env(pg, signer, stub, tmp_path)
    assert ap.main(["once"], env=env) == 0
    assert ap.main(["check"], env=env) == 0
    _entries(db, signer, 1)
    cfg = ap.load_settings(env)
    remote, reg = ap.build(cfg)
    assert ap.run(cfg, remote, reg, iterations=2, sleep=lambda s: None) == 0 and stub.accepted == [1, 2, 3, 4]
    assert ap.main(["check"], env={**env, "ANCHOR_REMOTE_TOKEN": "w" * 32}) == 1   # remote refuses the credential
    assert ap.main(["once"], env={**env, "KEY_REGISTRY_PATH": str(tmp_path / "missing.json")}) == 2
    assert ap.main(["once"], env={k: v for k, v in env.items() if k != "ANCHOR_REMOTE_URL"}) == 2
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err and "w" * 32 not in out.out + out.err
    assert pg not in out.out + out.err
