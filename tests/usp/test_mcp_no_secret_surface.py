"""USP invariant 6 at the MCP surface (G1+G2): nothing an agent can list or call returns signing material,
receipts, review tokens, or a way to approve (complete_review / mint). Every tool is called with hostile inputs."""
import base64
import json

import pytest
from mcpkit import app_for, body, call, listing

from actionproof import review

HOSTILE = [
    None, {}, {"doc_id": 1}, {"doc_id": ["invoice.pdf"]}, {"doc_id": "../../keys/dev-signing.key"}, {"doc_id": "C:/Windows/win.ini"},
    {"request_hash": "' OR 1=1 --"}, {"request_hash": "0" * 64}, {"tool": "payments.approve_invoice"},
    {"actor": "agent-7", "on_behalf_of": "user-123", "idempotency_key": "k", "args": {"amount": {"value": "1e999",
     "claim": "DIRECT", "src": {"doc": "../../keys/x", "pointer": "/"}, "doc_sha256": "0" * 64}}},
    {"__proto__": {"admin": True}, "args": {"x": {"value": "1", "claim": "ASSERTED"}}},
]


@pytest.fixture
def app(kit):
    return app_for(kit)


def _secrets(kit) -> list[str]:
    seed = open(kit.settings.signing_key_path, "rb").read()
    out = [seed.hex(), base64.b64encode(seed).decode(), base64.urlsafe_b64encode(seed).decode().rstrip("=")]
    out += [t for (t,) in kit.sql("SELECT token FROM review_tokens")]
    out += [n for (n,) in kit.sql("SELECT receipt->'payload'->>'nonce' FROM pending_reviews")]
    out += [s for (s,) in kit.sql("SELECT receipt->>'sig' FROM pending_reviews")]
    return [s for s in out if s]


def test_surface_lists_no_approval_or_secret_path(app):
    names, tools, resources, prompts = listing(app)
    assert not any(w in n for n in names for w in ("complete", "mint", "review_token", "release", "key", "sign"))
    assert resources == [] and prompts == []
    text = json.dumps([t.model_dump(mode="json") for t in tools])
    assert "receipt" not in text.lower() or "never" in text.lower()


def test_hostile_calls_leak_nothing(kit, app):
    # Real secrets exist: one pending review (signed receipt stored server-side) and one minted token.
    _, s, _ = call(app, "payments_approve_invoice", body(kit.hero()[0]))
    kit.sql("INSERT INTO people (login, person_id, roles) VALUES ('rev-user123', 'p-user123', '{reviewer}')")
    _, s2, _ = call(app, "payments_approve_invoice", body(kit.hero("idem-2")[0]))
    review.complete_review(kit.gate, kit.factory, s2["request_hash"], "rev-alice", True, "ok")
    secrets = _secrets(kit)
    assert len(secrets) >= 5

    names = listing(app)[0] + ["complete_review", "mint_review_token", "release_quarantine", "../etc"]
    seen = [json.dumps(s)]
    for name in names:
        for args in HOSTILE:
            texts, structured, _ = call(app, name, args)
            seen.append("".join(texts) + json.dumps(structured))
    for h in (s["request_hash"], s2["request_hash"]):
        texts, structured, _ = call(app, "review_status", {"request_hash": h})
        seen.append("".join(texts) + json.dumps(structured))
    blob = "\n".join(seen)
    for secret in secrets:
        assert secret not in blob
    for word in ('"sig"', '"nonce"', '"payload"', "review_token", "Traceback", "SigningKey", "_sk"):
        assert word not in blob, word
