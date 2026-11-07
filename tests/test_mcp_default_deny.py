"""MCP front door (deck S3.2 "an MCP proxy sits in front of every tool. Default deny"; S7.1; ADR-004/012).

In-process: the SDK Client against the real lowlevel Server built by actionproof.server, over a kit gate
(real Postgres + OPA + extraction). The stdio subprocess path is tests/e2e/test_slide1_mcp_stdio.py.
"""
import importlib.util
import json
import re
from pathlib import Path

import pytest
from gatekit import AGENT, HERO_DOCS
from mcpkit import app_for, body, call, listing

import hero
from actionproof import review
from actionproof.gate import Principal

ROOT = Path(__file__).resolve().parents[1]
SLIDE_1 = """ACTION INTERCEPTED
action: approve_invoice
amount: 4800.00 [DIRECT ok]
variance: 500.00 [DERIVED ok]
rule: AP-INV-04 (> 100)
decision: REVIEW"""
APPROVE, REFUND = "payments_approve_invoice", "payments_refund_payment"
RULE = re.compile(r"AP-[A-Z]+-\d{2}")


@pytest.fixture
def app(kit):
    return app_for(kit)


def _refuses(kit) -> int:
    return kit.sql("SELECT count(*) FROM audit_log WHERE kind = 'refuse'")[0][0]


def _rules(s: dict) -> list[str]:
    return [r["rule"] for r in s["reasons"]]


def _assert_decision_shape(texts, s):
    """Every DENY/REVIEW names a rule id and its guarantee (CLAUDE.md), and carries the card text."""
    assert s["card"] in texts[0] and texts[0].startswith(s["card"])
    if s["decision"] in ("DENY", "REVIEW"):
        assert s["reasons"] and all(RULE.fullmatch(r["rule"]) and r["guarantee"] in ("G1", "G2") for r in s["reasons"])
        assert RULE.search(texts[0])


def test_lists_only_registry_tools(app):
    names, tools, resources, prompts = listing(app)
    assert sorted(names) == sorted([APPROVE, REFUND, "extract_fields", "review_status"])
    assert resources == [] and prompts == []
    ro = {t.name: t.annotations.read_only_hint for t in tools}
    assert ro["extract_fields"] and ro["review_status"] and not ro[APPROVE] and not ro[REFUND]


def test_slide1_hero_is_pending_review(kit, app):
    texts, s, err = call(app, APPROVE, body(kit.hero()[0]))
    assert not err
    assert texts[0] == SLIDE_1  # S1.1, byte-identical card
    assert s["status"] == "pending" and s["decision"] == "REVIEW" and _rules(s) == ["AP-INV-04"]
    _assert_decision_shape(texts, s)
    assert "receipt" not in s and '"sig"' not in "".join(texts) and "nonce" not in "".join(texts)
    row = kit.sql("SELECT status, actor, on_behalf_of, receipt IS NOT NULL FROM pending_reviews "
                  "WHERE request_hash = %s", (s["request_hash"],))
    assert row == [("pending", "agent-7", "user-123", True)]
    assert kit.executes == 0
    _, st, _ = call(app, "review_status", {"request_hash": s["request_hash"]})
    assert st["status"] == "pending" and _rules(st) == ["AP-INV-04"]


def test_amount_claim_not_in_span_denied_g1(kit, app):
    d = body(kit.hero()[0])
    d["args"]["amount"]["value"] = "4900.00"
    texts, s, _ = call(app, APPROVE, d)
    assert s["decision"] == "DENY" and set(_rules(s)) == {"AP-VER-01"}
    assert all(r["guarantee"] == "G1" for r in s["reasons"])
    assert "amount: 4900.00 [DIRECT FAILED]" in texts[0] and "rule: AP-VER-01 [G1]" in texts[0]
    _assert_decision_shape(texts, s)
    assert kit.executes == 0 and kit.commits() == 0 and kit.tool.calls == []


def test_allow_executes_once_in_the_same_call(kit, app):
    req, _ = kit.hero_allow()
    texts, s, _ = call(app, APPROVE, body(req))
    assert s["status"] == "executed" and s["decision"] == "ALLOW", s
    assert "rule: none" in texts[0] and "decision: ALLOW" in texts[0]
    assert kit.executes == 1 and len(kit.tool.calls) == 1
    texts, s, _ = call(app, APPROVE, body(req))  # same request again: the record is no longer open
    assert s["decision"] == "DENY" and kit.executes == 1
    _assert_decision_shape(texts, s)


@pytest.mark.parametrize("name", ["payments_delete_vendor", "payments.approve_invoice", "complete_review",
                                  "mint_review_token", "", "x" * 300])
def test_unknown_tool_refused_and_audited(kit, app, name):
    before = _refuses(kit)
    texts, s, err = call(app, name, body(kit.hero()[0]))
    assert err and s["status"] == "refused" and s["error"]["code"] == "unknown_tool"
    assert _rules(s) == ["AP-VER-01"] and s["reasons"][0]["guarantee"] == "G1"
    assert "decision: DENY" in texts[0]
    assert _refuses(kit) == before + 1
    assert kit.executes == 0 and kit.sql("SELECT count(*) FROM audit_log WHERE kind = 'prepare'") == [(0,)]


def _malformed(kit):
    good = body(kit.hero()[0])
    extra = json.loads(json.dumps(good))
    extra["sneaky"] = True
    floaty = json.loads(json.dumps(good))
    floaty["args"]["amount"]["value"] = 4800.0
    wrong_tool = json.loads(json.dumps(good))
    wrong_tool["tool"] = "payments.refund_payment"
    no_args = {k: v for k, v in good.items() if k != "args"}
    return [{}, {"args": "x"}, extra, floaty, wrong_tool, no_args, {"request": good}]


def test_malformed_args_refused_never_prepared(kit, app):
    for i, args in enumerate(_malformed(kit)):
        before = _refuses(kit)
        texts, s, err = call(app, APPROVE, args)
        assert err and s["status"] == "refused" and s["error"]["code"] == "malformed", (i, s)
        assert _rules(s) == ["AP-VER-01"] and "decision: DENY" in texts[0]
        assert _refuses(kit) == before + 1
    assert kit.sql("SELECT count(*) FROM audit_log WHERE kind = 'prepare'") == [(0,)] and kit.executes == 0


def test_principal_mismatch_denied(kit, app):
    texts, s, _ = call(app, APPROVE, body(kit.hero()[0]), principal=Principal("agent-9", "user-123"))
    assert s["decision"] == "DENY" and _rules(s) == ["AP-SCOPE-02"]
    _assert_decision_shape(texts, s)
    d = body(kit.hero()[0])
    d["on_behalf_of"] = "user-999"  # the body names someone else; the session is agent-7 / user-123
    texts, s, _ = call(app, APPROVE, d)
    assert s["decision"] == "DENY" and _rules(s) == ["AP-SCOPE-02"]
    assert kit.executes == 0 and kit.sql("SELECT count(*) FROM pending_reviews") == [(0,)]


def test_review_lifecycle(kit, app):
    _, s, _ = call(app, APPROVE, body(kit.hero()[0]))
    h = s["request_hash"]
    kit.sql("INSERT INTO people (login, person_id, roles) VALUES ('rev-user123', 'p-user123', '{reviewer}')")
    o = review.complete_review(kit.gate, kit.factory, h, "rev-user123", True, "looks fine")
    assert o.status == "pending" and [r.rule for r in o.reasons] == ["AP-SEP-12"]
    assert o.reasons[0].guarantee == "G2" and kit.executes == 0
    assert call(app, "review_status", {"request_hash": h})[1]["status"] == "pending"

    o = review.complete_review(kit.gate, kit.factory, h, "rev-alice", True, "PO amendment on file")
    assert o.status == "executed" and o.reasons == [] and kit.executes == 1 and len(kit.tool.calls) == 1
    _, st, _ = call(app, "review_status", {"request_hash": h})
    assert st["status"] == "executed"

    o = review.complete_review(kit.gate, kit.factory, h, "rev-alice", True, "again")
    assert o.status == "executed" and [r.rule for r in o.reasons] == ["AP-REP-05"] and kit.executes == 1
    o = review.complete_review(kit.gate, kit.factory, h, "rev-bob", False, "too late")
    assert [r.rule for r in o.reasons] == ["AP-REP-05"]
    kinds = [k for (k,) in kit.sql("SELECT kind FROM audit_log WHERE kind = 'review' ORDER BY seq")]
    assert len(kinds) >= 3


def test_review_rejected_with_typed_reason(kit, app):
    _, s, _ = call(app, APPROVE, body(kit.hero()[0]))
    o = review.complete_review(kit.gate, kit.factory, s["request_hash"], "rev-alice", False, "duplicate invoice")
    assert o.status == "rejected" and o.reasons[0].rule == "AP-REV-10" and "duplicate invoice" in o.reasons[0].msg
    _, st, _ = call(app, "review_status", {"request_hash": s["request_hash"]})
    assert st["status"] == "rejected" and "duplicate invoice" in st["reasons"][0]["msg"]
    with pytest.raises(ValueError):
        review.complete_review(kit.gate, kit.factory, s["request_hash"], "rev-alice", False, "  ")
    assert kit.executes == 0
    assert kit.sql("SELECT decision FROM audit_log WHERE kind = 'review'") == [("REJECTED",)]


def test_review_status_is_scoped_to_the_callers_principal(kit, app):
    _, s, _ = call(app, APPROVE, body(kit.hero()[0]))
    _, st, _ = call(app, "review_status", {"request_hash": s["request_hash"]}, principal=Principal("agent-8", "user-9"))
    assert st["status"] == "not_found"
    _, st, _ = call(app, "review_status", {"request_hash": "0" * 64})
    assert st["status"] == "not_found"
    _, st, err = call(app, "review_status", {"request_hash": "../x"})
    assert err and st["error"]["code"] == "malformed"


def test_injected_pdf_cited_for_amount_denied(kit, app):
    d = body(kit.hero()[0])
    d["args"]["amount"] = hero.pdf_claim("injected.pdf", "hidden_text", value="4800.00")
    texts, s, _ = call(app, APPROVE, d)
    assert s["decision"] == "DENY" and "AP-VER-01" in _rules(s)
    assert all(r["guarantee"] == "G1" for r in s["reasons"] if r["rule"] == "AP-VER-01")
    _assert_decision_shape(texts, s)
    assert kit.executes == 0


_spec = importlib.util.spec_from_file_location("demo_seed", ROOT / "scripts" / "demo_seed.py")
demo_seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo_seed)


def test_refund_beats_via_mcp(kit, app):
    assert demo_seed.main(["--reset"]) == 0
    inj = hero.refund_request(hero.REFUND_INJECTED, "mcp-inj", refund_to=hero.injected_refund_to())
    texts, s, _ = call(app, REFUND, body(inj))
    assert s["decision"] == "DENY" and "AP-VER-01" in _rules(s)
    assert "rule: AP-VER-01 [G1]" in texts[0] and "refund_to: pm_attacker_9999 [ASSERTED]" in texts[0]
    _assert_decision_shape(texts, s)

    texts, s, _ = call(app, REFUND, body(hero.refund_request(hero.REFUND_CLEAN, "mcp-clean")))
    assert s["decision"] == "DENY" and _rules(s) == ["AP-CUM-03"] and "rule: AP-CUM-03 [G1]" in texts[0]

    texts, s, _ = call(app, REFUND, body(hero.refund_request(hero.REFUND_SMALL, "mcp-small")))
    assert s["status"] == "executed", s
    assert kit.refund_executes == 1 and len(kit.refunds.calls) == 1


def test_extract_fields_pdf_spans_match_manifest(app):
    texts, s, err = call(app, "extract_fields", {"doc_id": "invoice.pdf"})
    assert not err and s["untrusted_document_text"] is True and s["kind"] == "pdf"
    m = hero.MANIFEST["docs"]["invoice.pdf"]
    assert s["doc_sha256"] == m["sha256"]
    total = m["fields"]["total"]
    spans = [w for w in s["words"] if w["text"] == "$4,800.00"]
    assert spans == [{"page": 1, "bbox": total["bbox"], "text": "$4,800.00"}]
    assert any("$4,800.00" in line["text"] for line in s["lines"])
    assert all(isinstance(c, str) for w in s["words"] for c in w["bbox"])
    assert "untrusted" in texts[0].lower()


def test_extract_fields_cited_span_verifies(kit, app):
    """The span extract_fields returns is citable as-is: a DIRECT claim at that box re-checks (G1)."""
    s = call(app, "extract_fields", {"doc_id": "invoice.pdf"})[1]
    w = next(w for w in s["words"] if w["text"] == "$4,800.00")
    d = body(kit.hero()[0])
    d["args"]["amount"] = {"value": "4800.00", "claim": "DIRECT", "src": {"doc": "invoice.pdf", "page": w["page"],
                           "bbox": w["bbox"]}, "doc_sha256": s["doc_sha256"]}
    texts, s2, _ = call(app, APPROVE, d)
    assert texts[0] == SLIDE_1


def test_extract_fields_json_leaves(app):
    _, s, _ = call(app, "extract_fields", {"doc_id": "po.json"})
    assert s["kind"] == "json" and s["untrusted_document_text"] is True
    assert {"pointer": "/total", "value": "4300.00"} in s["leaves"]
    assert s["doc_sha256"] == hero.MANIFEST["docs"]["po.json"]["sha256"]


@pytest.mark.parametrize("doc_id", ["nope.pdf", "../pyproject.toml", "..\\pyproject.toml", "/etc/passwd",
                                    "C:/Windows/win.ini", "fixtures/out/invoice.pdf", "manifest.json", "", "invoice.pdf\x00"])
def test_extract_fields_refuses_unknown_or_traversal(kit, app, doc_id):
    before = _refuses(kit)
    _, s, err = call(app, "extract_fields", {"doc_id": doc_id})
    assert err and s["status"] == "refused" and s["error"]["code"] in ("unknown_doc", "malformed")
    assert _refuses(kit) == before + 1


def test_extract_fields_rejects_extra_args(app):
    _, s, err = call(app, "extract_fields", {"doc_id": "invoice.pdf", "path": "../../x"})
    assert err and s["error"]["code"] == "malformed"


def test_rate_limit_per_principal(kit):
    app = app_for(kit, rate=2)
    for _ in range(2):
        assert call(app, "review_status", {"request_hash": "0" * 64})[1]["status"] == "not_found"
    _, s, err = call(app, "review_status", {"request_hash": "0" * 64})
    assert err and s["status"] == "refused" and s["error"]["code"] == "rate_limited"
    # another principal has its own bucket
    other = Principal("agent-8", "user-9")
    assert call(app, "review_status", {"request_hash": "0" * 64}, principal=other)[1]["status"] == "not_found"


def test_unauthenticated_call_refused(kit, app):
    texts, s, err = call(app, APPROVE, body(kit.hero()[0]), principal=None)
    assert err and s["error"]["code"] == "unauthenticated" and kit.executes == 0


def test_docs_are_served_by_the_server_not_the_agent(kit, app):
    """The agent cannot ship its own bytes: claims are checked against the server's document store."""
    assert set(HERO_DOCS) == set(app.docs.all())
