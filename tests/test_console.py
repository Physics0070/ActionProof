"""Review-console backend (src/actionproof/console.py; deck slide 3 step 4, S9.2, S9.6, S7.8 backend half).

Sessions are server-side (sha256 of a random id), CSRF is double-submit, the reviewer identity is ONLY the session
login (ADR-008), every error is structured JSON, and nothing returned carries receipt or signature material.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from mcpkit import app_for, body, call

import hero
from actionproof import console as con
from actionproof import review
from actionproof import server as srv

ROOT = Path(__file__).resolve().parents[1]
PW = {login: f"pw-{login}-correct-horse" for login in ("rev-alice", "rev-bob", "sub-user123", "admin-ops")}
ORIGIN = "http://localhost:5173"
INVOICE_DOC = hero.MANIFEST["hero"]["invoice"]
SLIDE_1 = """ACTION INTERCEPTED
action: approve_invoice
amount: 4800.00 [DIRECT ok]
variance: 500.00 [DERIVED ok]
rule: AP-INV-04 (> 100)
decision: REVIEW"""


def _settings(**over) -> con.ConsoleSettings:
    return con.ConsoleSettings(**{"web_origin": ORIGIN, **over})


@pytest.fixture
def make_app(kit):
    with kit.factory() as conn:
        for login, pw in PW.items():
            con.set_password(conn, login, pw)

    def make(**over):
        return con.create_app(kit.gate, srv.DocStore(hero.OUT), kit.factory, _settings(**over))

    return make


@pytest.fixture
def app(make_app):
    return make_app()


def client(app, base_url="http://testserver") -> TestClient:
    return TestClient(app, base_url=base_url)


def login(app, who: str) -> tuple[TestClient, str]:
    c = client(app)
    r = c.post("/api/auth/login", json={"login": who, "password": PW[who]})
    assert r.status_code == 200, r.text
    return c, r.json()["csrf_token"]


def decide(c, csrf, h, decision="approve", reason="PO amendment on file", **extra):
    return c.post(f"/api/requests/{h}/decision", json={"decision": decision, "reason": reason, **extra},
                  headers={"X-CSRF-Token": csrf})


def park_hero(kit) -> str:
    """A REVIEW created through the real MCP surface (in-process SDK client)."""
    _, s, _ = call(app_for(kit), "payments_approve_invoice", body(kit.hero()[0]))
    assert s["status"] == "pending"
    return s["request_hash"]


def park_json(kit, invoice_id: str, actor: str = "agent-7") -> str:
    """A cheap REVIEW (variance 200 -> AP-INV-04) parked through review.park, as the MCP server does."""
    req, docs = kit.json_request(invoice_id, "300.00", "100.00")
    res = kit.gate.prepare(req, docs)
    assert res.decision == "REVIEW"
    review.park(kit.factory, req, res.receipt, res.reasons, res=res)
    return res.receipt["payload"]["request_hash"]


def is_error(r, status: int, code: str | None = None):
    assert r.status_code == status, r.text
    e = r.json()["error"]
    assert set(e) == {"code", "message"} and (code is None or e["code"] == code)
    assert "Traceback" not in r.text


# ------------------------------------------------------------------------------------------------ auth

def test_login_ok_and_bad_credentials_are_identical(app):
    c, csrf = login(app, "rev-alice")
    me = c.get("/api/auth/me").json()
    assert me == {"login": "rev-alice", "roles": ["reviewer"]}
    wrong_pw = client(app).post("/api/auth/login", json={"login": "rev-alice", "password": "nope-nope-nope"})
    no_user = client(app).post("/api/auth/login", json={"login": "ghost-user", "password": "nope-nope-nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()  # no user enumeration
    assert "set-cookie" not in wrong_pw.headers


def test_lockout_per_login_and_ip(app):
    c = client(app)
    for _ in range(con.LOGIN_MAX_FAILURES):
        assert c.post("/api/auth/login", json={"login": "rev-bob", "password": "wrong-password"}).status_code == 401
    locked = c.post("/api/auth/login", json={"login": "rev-bob", "password": PW["rev-bob"]})
    is_error(locked, 429, "rate_limited")
    ghost = [c.post("/api/auth/login", json={"login": "ghost", "password": "x" * 9}).status_code
             for _ in range(con.LOGIN_MAX_FAILURES + 1)]
    assert ghost[-1] == 429  # unknown logins lock the same way (no enumeration by lockout)
    login(app, "rev-alice")  # another login is unaffected


def test_session_cookie_flags_and_only_hash_stored(app, make_app, kit):
    r = client(app).post("/api/auth/login", json={"login": "rev-alice", "password": PW["rev-alice"]})
    cookies = r.headers.get_list("set-cookie")
    sess = next(x for x in cookies if x.startswith(f"{con.SESSION_COOKIE}="))
    assert "HttpOnly" in sess and "samesite=strict" in sess.lower() and "Secure" not in sess  # plain http, auto
    csrf_cookie = next(x for x in cookies if x.startswith(f"{con.CSRF_COOKIE}="))
    assert "HttpOnly" not in csrf_cookie and "samesite=strict" in csrf_cookie.lower()
    sid = sess.split(";")[0].split("=", 1)[1]
    assert kit.sql("SELECT sid_hash FROM console_sessions") == [(hashlib.sha256(sid.encode()).hexdigest(),)]
    assert "password" not in r.text and sid not in r.text

    https = client(app, "https://testserver").post("/api/auth/login", json={"login": "rev-bob",
                                                                            "password": PW["rev-bob"]})
    assert all("Secure" in x for x in https.headers.get_list("set-cookie"))
    forced = client(make_app(console_cookie_secure="true")).post(
        "/api/auth/login", json={"login": "rev-bob", "password": PW["rev-bob"]})
    assert all("Secure" in x for x in forced.headers.get_list("set-cookie"))


def test_login_rotates_session_against_fixation(app, kit):
    c, _ = login(app, "rev-alice")
    old = c.cookies.get(con.SESSION_COOKIE)
    r = c.post("/api/auth/login", json={"login": "rev-alice", "password": PW["rev-alice"]})
    assert r.status_code == 200 and c.cookies.get(con.SESSION_COOKIE) != old
    assert kit.sql("SELECT count(*) FROM console_sessions") == [(1,)]  # the presented session was dropped


def test_csrf_required_on_state_changes(app, kit):
    h = park_json(kit, "INV-8001")
    c, csrf = login(app, "rev-alice")
    is_error(c.post("/api/auth/logout"), 403, "csrf")
    is_error(c.post("/api/auth/logout", headers={"X-CSRF-Token": "x" * 43}), 403, "csrf")
    is_error(decide(c, "wrong", h), 403, "csrf")
    assert kit.executes == 0 and c.get("/api/auth/me").status_code == 200


def test_logout_invalidates_and_expired_session_refused(app, kit):
    c, csrf = login(app, "rev-alice")
    stolen = c.cookies.get(con.SESSION_COOKIE)
    assert c.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    is_error(c.get("/api/auth/me"), 401, "unauthenticated")
    replay = client(app)
    replay.cookies.set(con.SESSION_COOKIE, stolen)
    is_error(replay.get("/api/auth/me"), 401, "unauthenticated")

    c2, _ = login(app, "rev-bob")
    kit.sql("UPDATE console_sessions SET expires_at = 0")
    is_error(c2.get("/api/queue"), 401, "unauthenticated")
    kit.sql("DELETE FROM console_sessions")
    c3, _ = login(app, "rev-bob")
    kit.sql("UPDATE console_users SET disabled = true WHERE login = 'rev-bob'")
    is_error(c3.get("/api/auth/me"), 401, "unauthenticated")


def test_role_enforcement(app, kit):
    h = park_json(kit, "INV-8002")
    is_error(client(app).get("/api/queue"), 401, "unauthenticated")
    sub, sub_csrf = login(app, "sub-user123")
    is_error(sub.get("/api/queue"), 403, "forbidden")
    is_error(decide(sub, sub_csrf, h), 403, "forbidden")
    adm, adm_csrf = login(app, "admin-ops")
    assert adm.get("/api/queue").status_code == 200 and adm.get("/api/audit/verify").json()["ok"] is True
    is_error(decide(adm, adm_csrf, h), 403, "forbidden")  # admin cannot decide (ADR-008)
    assert kit.executes == 0 and kit.sql("SELECT status FROM pending_reviews") == [("pending",)]


# ------------------------------------------------------------------------------------------------ the flow

def test_mcp_review_to_console_approve_executes_once(app, kit):
    h = park_hero(kit)
    c, csrf = login(app, "rev-alice")

    q = c.get("/api/queue?status=pending").json()
    assert [i["request_hash"] for i in q["items"]] == [h]
    assert q["items"][0]["top_rule"] == "AP-INV-04" and q["items"][0]["amount"] == "4800.00"

    d = c.get(f"/api/requests/{h}").json()
    assert d["card"] == SLIDE_1
    assert d["label"] == "requested by agent-7 for user-123"
    claims = {x["name"]: x for x in d["claims"]}
    assert claims["amount"]["claim"] == "DIRECT" and claims["amount"]["verification"]["ok"] is True
    assert claims["amount"]["source"] == {"doc": INVOICE_DOC, "page": 1,
                                          "bbox": hero.MANIFEST["docs"][INVOICE_DOC]["fields"]["total"]["bbox"]}
    assert claims["amount"]["verification"]["method"]
    assert claims["variance"]["claim"] == "DERIVED" and claims["variance"]["verification"]["ok"] is True
    assert claims["variance"]["derivation"] == {"fn": "sub", "inputs": ["invoice.total", "po.total"]}
    assert claims["note"]["claim"] == "ASSERTED" and claims["note"]["evidence"] is False
    assert claims["note"]["taint"] == "doc" and claims["amount"]["evidence"] is True
    assert {"rule": "AP-INV-04", "guarantee": "G1"}.items() <= d["policy_reasons"][0].items()
    assert d["diff"] == {"record_id": "invoice:INV-2048", "status": "open->approved", "amount": "4800.00"}
    assert d["before"]["data"]["status"] == "open" and d["before"]["version"] == 1
    text = json.dumps(d)
    for word in ('"receipt"', '"sig"', '"nonce"', '"payload"', "review_token"):
        assert word not in text

    r = decide(c, csrf, h)
    assert r.status_code == 200 and r.json() == {"outcome": "EXECUTED", "status": "executed", "reasons": []}
    assert kit.executes == 1 and len(kit.tool.calls) == 1
    assert kit.sql("SELECT status, reviewer FROM pending_reviews") == [("executed", "rev-alice")]

    again = decide(c, csrf, h).json()  # a replayed decision cannot execute twice (G2)
    assert again["outcome"] == "DENY" and again["reasons"][0]["rule"] == "AP-REP-05"
    assert kit.executes == 1

    v = c.get("/api/audit/verify").json()
    assert v["ok"] is True and v["entries"] > 0 and v["checkpoints"] > 0 and v["error"] is None
    entries = c.get("/api/audit?limit=5").json()["items"]
    assert len(entries) == 5 and entries[0]["seq"] > entries[-1]["seq"]
    assert '"nonce"' not in json.dumps(entries) and "idempotency_key" not in json.dumps(entries)

    pub = client(app).get("/api/public/replay/inv-2048").json()  # no auth; the REAL stored decision
    assert pub["card"] == SLIDE_1 and pub["status"] == "executed" and pub["reviewer"] == "rev-alice"
    assert [x["rule"] for x in pub["reasons"]] == ["AP-INV-04"]
    lo, hi = kit.sql("SELECT min(seq), max(seq) FROM audit_log WHERE request_hash = %s", (h,))[0]
    assert pub["audit"] == {"first_seq": lo, "last_seq": hi}
    assert {x["name"] for x in pub["claims"]} >= {"amount", "variance", "note"}
    for word in ('"sig"', '"nonce"', '"receipt"'):
        assert word not in json.dumps(pub)


def test_separation_reject_and_body_identity(app, kit):
    h = park_json(kit, "INV-8003")
    kit.sql("INSERT INTO people (login, person_id, roles) VALUES ('rev-user123', 'p-user123', '{reviewer}')")
    with kit.factory() as conn:
        con.set_password(conn, "rev-user123", "pw-rev-user123-correct-horse")
    same = client(app)
    csrf = same.post("/api/auth/login", json={"login": "rev-user123",
                                              "password": "pw-rev-user123-correct-horse"}).json()["csrf_token"]
    r = decide(same, csrf, h).json()
    assert r["outcome"] == "DENY" and r["reasons"][0]["rule"] == "AP-SEP-12" and r["status"] == "pending"

    bob, bob_csrf = login(app, "rev-bob")
    # The reviewer is the session login only: a body field naming someone else is refused, not honoured.
    is_error(decide(bob, bob_csrf, h, reviewer_login="rev-alice"), 422, "validation_error")
    is_error(decide(bob, bob_csrf, h, reason="short"), 422, "validation_error")
    rej = decide(bob, bob_csrf, h, decision="reject", reason="vendor bank details unverified").json()
    assert rej["outcome"] == "REJECTED" and rej["reasons"][0]["rule"] == "AP-REV-10"
    status, reviewer, reasons = kit.sql("SELECT status, reviewer, reasons FROM pending_reviews")[0]
    assert (status, reviewer) == ("rejected", "rev-bob") and "vendor bank details unverified" in reasons[0]["msg"]
    assert kit.executes == 0
    is_error(client(app).post(f"/api/requests/{'0' * 64}/decision", json={}), 401, "unauthenticated")
    is_error(decide(bob, bob_csrf, "0" * 64), 404, "not_found")


def test_stale_status_is_reconciled(app, kit):
    """An EXECUTED commit whose pending_reviews update was lost still reads as executed and cannot run again."""
    h = park_json(kit, "INV-8004")
    c, csrf = login(app, "rev-alice")
    assert decide(c, csrf, h).json()["outcome"] == "EXECUTED"
    kit.sql("UPDATE pending_reviews SET status = 'pending', reviewer = NULL, decided_at = NULL")  # the lost update
    item = c.get("/api/queue").json()["items"][0]
    assert item["status"] == "executed" and item["reviewer"] == "rev-alice"
    assert decide(c, csrf, h).json()["reasons"][0]["rule"] == "AP-REP-05"
    assert kit.executes == 1


def test_queue_filters_and_cursor(app, kit):
    hs = [park_json(kit, f"INV-81{i:02d}") for i in range(3)]
    c, csrf = login(app, "rev-alice")
    decide(c, csrf, hs[0], decision="reject", reason="duplicate of an earlier invoice")
    assert {i["request_hash"] for i in c.get("/api/queue?status=pending").json()["items"]} == set(hs[1:])
    assert [i["request_hash"] for i in c.get("/api/queue?status=rejected").json()["items"]] == [hs[0]]
    assert c.get("/api/queue?tool=payments.refund_payment").json()["items"] == []
    assert c.get("/api/queue?actor=agent-9").json()["items"] == []
    assert len(c.get("/api/queue?actor=agent-7&tool=payments.approve_invoice").json()["items"]) == 3
    seen, cursor = [], None
    while True:
        page = c.get("/api/queue", params={"limit": 1, **({"cursor": cursor} if cursor else {})}).json()
        seen += [i["request_hash"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert sorted(seen) == sorted(hs) and len(seen) == 3
    for bad in ("status=bogus", "limit=0", "limit=1000", "actor=Agent%207", "cursor=%27%20OR%201%3D1", "tool=x"):
        is_error(c.get(f"/api/queue?{bad}"), 422)


# ------------------------------------------------------------------------------------------------ page render

def test_page_png_draws_the_cited_box_and_refuses_traversal(app, kit):
    h = park_hero(kit)
    c, _ = login(app, "rev-alice")
    r = c.get(f"/api/requests/{h}/page/1.png", params={"doc": INVOICE_DOC})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    boxed = pymupdf.Pixmap(r.content)
    plain_doc = pymupdf.open(stream=(hero.OUT / hero.MANIFEST["docs"][INVOICE_DOC]["path"]).read_bytes(), filetype="pdf")
    plain = plain_doc[0].get_pixmap(matrix=pymupdf.Matrix(con.PAGE_ZOOM, con.PAGE_ZOOM))
    assert (boxed.width, boxed.height) == (plain.width, plain.height)
    x0, top, x1, bottom = (float(v) for v in hero.MANIFEST["docs"][INVOICE_DOC]["fields"]["total"]["bbox"])
    y = int((top + bottom) / 2 * con.PAGE_ZOOM)
    border = [(int(x0 * con.PAGE_ZOOM) + dx, y) for dx in (-1, 0, 1)]
    assert any(boxed.pixel(*p) != plain.pixel(*p) for p in border)

    for params, page in (({"doc": "../../keys/dev-signing.key"}, 1), ({"doc": "C:/Windows/win.ini"}, 1),
                         ({"doc": hero.MANIFEST["hero"]["po"]}, 1), ({"doc": INVOICE_DOC}, 9),
                         ({"doc": "benign/inv-01.pdf"}, 1), ({}, 1)):
        rr = c.get(f"/api/requests/{h}/page/{page}.png", params=params)
        assert rr.status_code in (404, 422) and rr.headers["content-type"].startswith("application/json"), params
    is_error(client(app).get(f"/api/requests/{h}/page/1.png", params={"doc": INVOICE_DOC}), 401)


# ------------------------------------------------------------------------------------------------ public + misc

def test_public_endpoints(app, make_app, kit, monkeypatch, tmp_path):
    c = client(app)
    is_error(c.get("/api/public/replay/inv-2048"), 404, "not_found")
    monkeypatch.setattr(con, "EVAL_RESULTS", tmp_path / "missing.json")
    assert c.get("/api/public/eval").json() == {"available": False}
    (tmp_path / "results.json").write_text('{"arms": []}', encoding="utf-8")
    monkeypatch.setattr(con, "EVAL_RESULTS", tmp_path / "results.json")
    assert c.get("/api/public/eval").json() == {"available": True, "results": {"arms": []}}
    assert c.get("/api/health").json() == {"ok": True}

    limited = client(make_app(rate_limit_per_minute=2))
    codes = [limited.get("/api/public/eval").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_errors_are_structured_with_security_headers(app, kit, monkeypatch):
    c, _ = login(app, "rev-alice")
    for r in (c.get("/api/nope"), c.get("/api/requests/not-a-hash"), c.post("/api/auth/login", content=b"{bad")):
        assert r.status_code in (404, 422), r.text
        is_error(r, r.status_code)
    monkeypatch.setattr(review, "reconcile", lambda conn: (_ for _ in ()).throw(RuntimeError("secret detail")))
    boom = c.get("/api/queue")
    is_error(boom, 500, "internal")
    assert "secret detail" not in boom.text
    for r in (boom, c.get("/api/health"), c.get("/api/nope")):
        h = r.headers
        assert "default-src 'none'" in h["content-security-policy"] and "frame-ancestors 'none'" in h[
            "content-security-policy"]
        assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer"


def test_cors_only_the_web_origin(app):
    c = client(app)
    pre = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-csrf-token"}
    ok = c.options("/api/auth/login", headers={"Origin": ORIGIN, **pre})
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    assert ok.headers["access-control-allow-credentials"] == "true"
    evil = c.options("/api/auth/login", headers={"Origin": "https://evil.example", **pre})
    assert "access-control-allow-origin" not in evil.headers
    assert "access-control-allow-origin" not in c.get("/api/health", headers={"Origin": "https://evil.example"}).headers


def test_seed_console_env_or_generated_once(kit, make_app):
    sys.path.insert(0, str(ROOT / "scripts"))
    import seed_console

    with kit.factory() as conn:
        generated = seed_console.seed(conn, env={"CONSOLE_PASSWORD_REV_ALICE": "alice-from-env-123"})
    assert set(generated) == {"rev-bob", "sub-user123", "admin-ops"}
    hashes = [h for (h,) in kit.sql("SELECT password_hash FROM console_users")]
    assert all(h.startswith("$argon2id$") for h in hashes) and not any(p in "".join(hashes)
                                                                      for p in generated.values())
    app = make_app()
    assert client(app).post("/api/auth/login", json={"login": "rev-alice",
                                                     "password": "alice-from-env-123"}).status_code == 200
    assert client(app).post("/api/auth/login", json={"login": "rev-bob",
                                                     "password": generated["rev-bob"]}).status_code == 200


def test_openapi_generated_and_current():
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_openapi.py"), "--check"], cwd=str(ROOT),
                       capture_output=True, timeout=120)
    assert p.returncode == 0, p.stderr
    spec = json.loads((ROOT / "web" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["openapi"].startswith("3.")
    for path in ("/api/auth/login", "/api/queue", "/api/requests/{request_hash}",
                 "/api/requests/{request_hash}/decision", "/api/audit/verify", "/api/public/replay/inv-2048"):
        assert path in spec["paths"], path
    decision = spec["components"]["schemas"]["DecisionBody"]
    assert set(decision["properties"]) == {"decision", "reason"} and decision.get("additionalProperties") is False


def test_console_bind_host_setting():
    """CONSOLE_BIND_HOST: validated, loopback by default; main() hands it to uvicorn (no hard-coded host)."""
    from actionproof.config import ConfigError

    env = {"WEB_ORIGIN": ORIGIN}
    assert con.load_console_settings(env).console_bind_host == "127.0.0.1"
    assert con.load_console_settings({**env, "CONSOLE_BIND_HOST": "0.0.0.0"}).console_bind_host == "0.0.0.0"
    for bad in ("", "not a host!", "1.2.3.4:80", "0.0.0.0/0"):
        with pytest.raises(ConfigError, match="CONSOLE_BIND_HOST"):
            con.load_console_settings({**env, "CONSOLE_BIND_HOST": bad})
    assert "host=\"127.0.0.1\"" not in Path(con.__file__).read_text(encoding="utf-8")


def test_public_replay_exposes_recorded_replay_attempts(app, kit):
    """The G2 bounce is read from the audit log: an executed hero, then its spent receipt replayed at the gate."""
    from actionproof.gate import Principal

    h = park_hero(kit)
    c, csrf = login(app, "rev-alice")
    pub0 = client(app).get("/api/public/replay/inv-2048").json()
    assert pub0["replay_attempts"] == []  # honest empty state before any replay
    assert decide(c, csrf, h).json()["outcome"] == "EXECUTED"
    assert client(app).get("/api/public/replay/inv-2048").json()["replay_attempts"] == []  # the approval is no bounce
    req_json, receipt = kit.sql("SELECT request, receipt FROM pending_reviews WHERE request_hash = %s", (h,))[0]
    req = hero.hero_request("idem-1")
    token = kit.gate.mint_review_token(receipt, req, reviewer_login="rev-alice")
    r = kit.gate.commit(receipt, req, token, principal=Principal("agent-7", "user-123"))
    assert r.outcome == "DENY"
    pub = client(app).get("/api/public/replay/inv-2048").json()
    seq, kind = kit.sql("SELECT max(seq), 'commit' FROM audit_log WHERE request_hash = %s AND kind = 'commit' "
                        "AND decision = 'DENY'", (h,))[0]
    att = pub["replay_attempts"]
    assert len(att) == 1 and att[0]["seq"] == seq and att[0]["kind"] == "commit" and att[0]["decision"] == "DENY"
    assert [(x["rule"], x["guarantee"]) for x in att[0]["reasons"]] == [("AP-REP-05", "G2")]
    assert isinstance(att[0]["ts"], int)
    for word in ('"sig"', '"nonce"', '"receipt"', "review_token"):
        assert word not in json.dumps(att)
