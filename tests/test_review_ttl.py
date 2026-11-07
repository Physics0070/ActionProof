"""REVIEW_RECEIPT_TTL_SECONDS (Task 5.6): a human review can outlast RECEIPT_TTL_SECONDS, so only REVIEW receipts
get the longer `exp`; ALLOW receipts keep the short one. AP-EXP-06 / G2 still applies to both."""
import time

from actionproof import gate as gatemod
from actionproof.config import load_settings

GOOD_ENV = {"DATABASE_URL": "postgresql://u:p@localhost:5433/db", "OPA_URL": "http://localhost:8181",
            "TESSERACT_CMD": "tesseract", "SIGNING_KEY_PATH": "keys/dev-signing.key"}


def test_review_ttl_setting_validated():
    assert load_settings(GOOD_ENV).review_receipt_ttl_seconds == 3600
    assert load_settings({**GOOD_ENV, "REVIEW_RECEIPT_TTL_SECONDS": "7200"}).review_receipt_ttl_seconds == 7200
    for bad in ("0", "-1", "x", "1.5"):
        try:
            load_settings({**GOOD_ENV, "REVIEW_RECEIPT_TTL_SECONDS": bad})
        except Exception as e:
            assert "REVIEW_RECEIPT_TTL_SECONDS" in str(e)
        else:
            raise AssertionError(bad)


def test_review_receipt_uses_review_ttl_allow_keeps_short(kit):
    review_req, docs = kit.json_request("INV-7101", "300.00", "100.00")  # variance 200 -> REVIEW (AP-INV-04)
    allow_req, docs2 = kit.json_request("INV-7102", "100.00")             # variance 0 -> ALLOW
    now = int(time.time())
    r = kit.gate.prepare(review_req, docs)
    a = kit.gate.prepare(allow_req, docs2)
    assert (r.decision, a.decision) == ("REVIEW", "ALLOW")
    s = kit.settings
    assert abs(r.receipt["payload"]["exp"] - (now + s.review_receipt_ttl_seconds)) <= 2
    assert abs(a.receipt["payload"]["exp"] - (now + s.receipt_ttl_seconds)) <= 2
    assert s.review_receipt_ttl_seconds > s.receipt_ttl_seconds


def test_expired_review_receipt_is_ap_exp_06(kit, monkeypatch):
    req, docs = kit.json_request("INV-7103", "300.00", "100.00")
    r = kit.gate.prepare(req, docs)
    later = r.receipt["payload"]["exp"]
    monkeypatch.setattr(gatemod, "_now", lambda: later)
    c = kit.gate.commit(r.receipt, req, "any-token")
    assert c.outcome == "DENY" and c.reasons[0].rule == "AP-EXP-06" and c.reasons[0].guarantee == "G2"
    assert kit.executes == 0
