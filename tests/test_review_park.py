"""review.park is the one REVIEW store for every front door: the LangChain adapter with `review_db` parks its
REVIEW in pending_reviews (receipt server-side only), and the console's complete_review executes it exactly once."""
from gatekit import AGENT, HERO_DOCS, INVOICE_TOOL, REFUND_TOOL

from actionproof import review
from actionproof.adapters.langchain import gate_tool
from actionproof.contracts import request_hash
from actionproof.gate import Gate


def test_langchain_review_parks_in_pending_reviews(kit):
    g = Gate(kit.settings, kit.signer, kit.factory, {INVOICE_TOOL: kit.tool, REFUND_TOOL: kit.refunds},
             docs_provider=lambda req: HERO_DOCS)
    pending: dict = {}
    t = gate_tool(g, AGENT, "approve_invoice", "Approve a vendor invoice.", pending=pending, review_db=kit.factory)
    out = t.invoke({"request": kit.hero()[0].model_dump(mode="json")})
    h = request_hash(kit.hero()[0])
    assert "PENDING_REVIEW" in out and pending == {}
    row = kit.sql("SELECT receipt->>'sig' FROM pending_reviews WHERE request_hash = %s", (h,))
    assert row and row[0][0] not in out
    assert "PENDING_REVIEW" in t.invoke({"request": kit.hero()[0].model_dump(mode="json")})  # idempotent park
    assert kit.sql("SELECT count(*) FROM pending_reviews") == [(1,)]
    o = review.complete_review(g, kit.factory, h, "rev-alice", True, "PO amendment on file")
    assert o.status == "executed" and kit.executes == 1
    assert "decision: DENY" in t.invoke({"request": kit.hero()[0].model_dump(mode="json")})  # record not open
