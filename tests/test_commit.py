"""gate.commit: one SERIALIZABLE tx; signature, expiry, hash, token, UNIQUE, cumulative, version; execute once."""
import copy
import re
from pathlib import Path

import pytest
from gatekit import rules
from psycopg import errors

from actionproof import gate as gate_mod
from actionproof import signing
from actionproof.signing import Signer

ROOT = Path(__file__).resolve().parents[1]


def _allow(kit, idem="idem-allow"):
    req, docs = kit.hero_allow(idem)
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW", r.reasons
    return req, r.receipt


def _review(kit, idem="idem-1"):
    req, docs = kit.hero(idem)
    r = kit.gate.prepare(req, docs)
    assert r.decision == "REVIEW", r.reasons
    return req, r.receipt


def test_allow_executes_once(kit):
    req, receipt = _allow(kit)
    c = kit.gate.commit(receipt, req)
    assert c.outcome == "EXECUTED" and c.reasons == []
    assert c.tool_result["status"] == "approved" and c.tool_result["amount"] == "4800.00"
    assert len(kit.tool.calls) == 1 and kit.executes == 1
    assert kit.version() == 2
    row = kit.sql("SELECT nonce, idempotency_key, actor, vendor_id, amount::text, record_id FROM commits")
    assert row == [(receipt["payload"]["nonce"], "idem-allow", "agent-7", "V-ACME", "4800.00", "invoice:INV-2048")]
    assert kit.sql("SELECT data->>'status' FROM records WHERE record_id = 'invoice:INV-2048'") == [("approved",)]


def test_allow_with_unpooled_connections(kit):
    """The kit pools connections for speed; the gate also works with plain fresh psycopg connections."""
    from gatekit import AGENT

    from actionproof import db as dbmod
    from actionproof.gate import Gate

    raw = lambda: dbmod.connect(url=kit.pg)  # noqa: E731
    g = Gate(kit.settings, kit.signer, raw, kit.tool)
    req, docs = kit.json_request("INV-1201", "100.00")
    r = g.prepare(req, docs, principal=AGENT)
    assert r.decision == "ALLOW"
    assert g.commit(r.receipt, req, principal=AGENT).outcome == "EXECUTED"
    assert rules(g.commit(r.receipt, req, principal=AGENT)) == ["AP-REP-05"] and len(kit.tool.calls) == 1


def test_review_without_token_denied(kit):
    req, receipt = _review(kit)
    c = kit.gate.commit(receipt, req)
    assert c.outcome == "DENY" and [(x.rule, x.guarantee) for x in c.reasons] == [("AP-REV-10", "G2")]
    assert kit.tool.calls == [] and kit.executes == 0 and kit.commits() == 0


def test_review_with_unknown_token_denied(kit):
    req, receipt = _review(kit)
    c = kit.gate.commit(receipt, req, review_token="made-up")
    assert rules(c) == ["AP-REV-10"] and kit.tool.calls == []


def test_review_with_token_executes_once(kit):
    req, receipt = _review(kit)
    token = kit.mint(receipt, req)
    c = kit.gate.commit(receipt, req, review_token=token)
    assert c.outcome == "EXECUTED", c.reasons
    assert len(kit.tool.calls) == 1 and kit.version() == 2
    used = kit.sql("SELECT used_at IS NOT NULL, used_nonce, minted_by, submitter FROM review_tokens")
    assert used == [(True, receipt["payload"]["nonce"], "rev-alice", "agent-7")]


def test_expired_receipt_denied(kit, monkeypatch):
    req, receipt = _allow(kit)
    exp = receipt["payload"]["exp"]
    monkeypatch.setattr(gate_mod, "_now", lambda: exp)
    c = kit.gate.commit(receipt, req)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-EXP-06", "G2")]
    assert kit.tool.calls == [] and kit.version() == 1


def test_receipt_expiring_while_waiting_for_lock_denied(kit, monkeypatch):
    req, receipt = _allow(kit)
    exp = receipt["payload"]["exp"]
    times = iter([exp - 1, exp, exp])  # valid at the door, expired once the commit lane is acquired
    monkeypatch.setattr(gate_mod, "_now", lambda: next(times))
    assert rules(kit.gate.commit(receipt, req)) == ["AP-EXP-06"] and kit.tool.calls == []


def test_tampered_argument_denied(kit):
    req, receipt = _allow(kit)
    d = req.model_dump(mode="json")
    d["args"]["amount"]["value"] = "4900.00"
    c = kit.gate.commit(receipt, d)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-HASH-08", "G2")]
    assert kit.tool.calls == []


@pytest.mark.parametrize("field,value", [("idempotency_key", "idem-other"), ("actor", "agent-9"),
                                         ("on_behalf_of", "user-999")])
def test_tampered_envelope_denied(kit, field, value):
    req, receipt = _allow(kit)
    c = kit.gate.commit(receipt, req.model_copy(update={field: value}))
    assert rules(c) == ["AP-HASH-08"] and kit.tool.calls == []


def test_bad_signature_denied(kit):
    req, receipt = _allow(kit)
    bad = copy.deepcopy(receipt)
    sig = bytearray(__import__("base64").b64decode(bad["sig"]))
    sig[0] ^= 1
    bad["sig"] = __import__("base64").b64encode(bytes(sig)).decode()
    c = kit.gate.commit(bad, req)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-SIG-09", "G2")] and kit.tool.calls == []


@pytest.mark.parametrize("field,value", [("version", 99), ("decision", "ALLOW"), ("exp", 9999999999),
                                         ("record_id", "invoice:OTHER"), ("diff_hash", "0" * 64)])
def test_edited_payload_denied(kit, field, value):
    req, receipt = _review(kit)  # REVIEW -> "ALLOW" edit is the interesting one
    bad = copy.deepcopy(receipt)
    bad["payload"][field] = value
    assert rules(kit.gate.commit(bad, req)) == ["AP-SIG-09"]
    assert kit.tool.calls == []


def test_wrong_key_receipt_denied(kit, tmp_path):
    req, receipt = _allow(kit)
    signing.generate_key(tmp_path / "evil.key")
    forged = Signer.from_path(tmp_path / "evil.key", kit.signer.kid).sign(receipt["payload"])
    assert rules(kit.gate.commit(forged, req)) == ["AP-SIG-09"] and kit.tool.calls == []


@pytest.mark.parametrize("receipt", [None, {}, "receipt", [], {"payload": {}, "sig": "", "kid": "k1"}])
def test_garbage_receipt_denied(kit, receipt):
    req, _ = kit.hero_allow()
    assert rules(kit.gate.commit(receipt, req)) == ["AP-SIG-09"]


def test_db_down_denied(kit):
    req, receipt = _allow(kit)

    def down():
        raise OSError("connection refused")

    kit.gate._conn_factory = down
    c = kit.gate.commit(receipt, req)
    assert rules(c) == ["AP-ERR-11"] and kit.tool.calls == []


def test_serialization_failures_retried_then_succeed(kit, monkeypatch):
    req, receipt = _allow(kit)
    real, n = kit.tool.dry_run, {"fails": 0}

    def flaky(r):
        if n["fails"] < gate_mod.MAX_RETRIES:
            n["fails"] += 1
            raise errors.SerializationFailure("could not serialize")
        return real(r)

    monkeypatch.setattr(kit.tool, "dry_run", flaky)
    c = kit.gate.commit(receipt, req)
    assert c.outcome == "EXECUTED" and n["fails"] == 3 and len(kit.tool.calls) == 1


@pytest.mark.parametrize("exc", [errors.SerializationFailure, errors.DeadlockDetected])
def test_serialization_failures_exhausted_denied(kit, monkeypatch, exc):
    req, receipt = _allow(kit)
    seen = []

    def always(r):
        seen.append(1)
        raise exc("nope")

    monkeypatch.setattr(kit.tool, "dry_run", always)
    c = kit.gate.commit(receipt, req)
    assert rules(c) == ["AP-ERR-11"] and len(seen) == gate_mod.MAX_RETRIES + 1
    assert kit.tool.calls == [] and kit.commits() == 0 and kit.version() == 1


def test_serialization_failure_after_execute_is_not_retried(kit):
    """40001 at COMMIT after the tool ran: no second execute, the receipt is burned, a retry is AP-REP-05."""
    req, receipt = _allow(kit)
    real_factory = kit.factory

    class FailFirstCommit:
        """Proxy whose first COMMIT fails like an SSI abort (the server rolls the tx back)."""

        def __init__(self, conn):
            self._c, self._failed = conn, False

        def __getattr__(self, name):
            return getattr(self._c, name)

        def __setattr__(self, name, value):
            if name in ("_c", "_failed"):
                object.__setattr__(self, name, value)
            else:
                setattr(self._c, name, value)

        def commit(self):
            if not self._failed:
                self._failed = True
                self._c.rollback()
                raise errors.SerializationFailure("could not serialize access")
            self._c.commit()

    kit.gate._conn_factory = lambda: FailFirstCommit(real_factory())
    c = kit.gate.commit(receipt, req)
    assert rules(c) == ["AP-ERR-11"] and kit.executes == 1
    assert kit.version() == 1  # the tx rolled back ...
    assert kit.sql("SELECT idempotency_key FROM commits") == [("idem-allow",)]  # ... but the receipt is burned
    kit.gate._conn_factory = real_factory
    assert rules(kit.gate.commit(receipt, req)) == ["AP-REP-05"]
    assert kit.executes == 1


def test_cap_mirrors_rego():
    rego = (ROOT / "policy" / "actionproof.rego").read_text(encoding="utf-8")
    cents = int(re.search(r"^cap_cents := (\d+)$", rego, re.M).group(1))
    assert gate_mod.CAP * 100 == cents


def test_identity_bound_to_transport_principal(kit):
    """ADR-012: the Gate takes the caller identity from the transport; no default, no request-supplied identity."""
    from actionproof.gate import Gate, Principal

    raw = Gate(kit.settings, kit.signer, kit.factory, kit.tool)
    req, docs = kit.json_request("INV-1301", "100.00")
    with pytest.raises(TypeError):
        raw.prepare(req, docs)  # principal is required: forgetting it can never fail open
    with pytest.raises(TypeError):
        raw.commit({}, req)
    for bad in (None, ("agent-7", "user-123"), Principal("agent-8", "user-123"), Principal("agent-7", "cfo")):
        r = raw.prepare(req, docs, principal=bad)
        assert r.decision == "DENY" and r.receipt is None
        assert [(x.rule, x.guarantee) for x in r.reasons] == [("AP-SCOPE-02", "G1")]
    receipt = kit.gate.prepare(req, docs).receipt
    for bad in (None, Principal("agent-8", "user-123"), Principal("agent-7", "user-999")):
        assert rules(raw.commit(receipt, req, principal=bad)) == ["AP-SCOPE-02"]
    assert kit.tool.calls == []
    assert raw.commit(receipt, req, principal=Principal("agent-7", "user-123")).outcome == "EXECUTED"


def test_model_construct_request_revalidated_at_commit(kit):
    """An ActionRequest built without validation (non-canonical actor) is re-parsed at commit and refused."""
    from actionproof.contracts import ActionRequest

    req, receipt = _allow(kit)
    bad = ActionRequest.model_construct(**{**dict(req), "actor": "Agent-7"})
    assert rules(kit.gate.commit(receipt, bad)) == ["AP-HASH-08"] and kit.tool.calls == []


def test_fresh_policy_review_after_allow_is_stale(kit):
    """ADR-014: an ALLOW receipt whose fresh decision is REVIEW (PO moved, honest variance claim) -> AP-STALE-07."""
    req, docs = kit.json_request("INV-1302", "1000.00", "1000.00")
    p = kit.gate.prepare(req, docs)
    assert p.decision == "ALLOW"
    kit.sql("UPDATE records SET data = data || '{\"total\": \"500.00\"}'::jsonb WHERE record_id = 'po:PO-INV-1302'")
    c = kit.gate.commit(p.receipt, req)
    assert c.outcome == "DENY" and "AP-VER-01" in rules(c) and kit.tool.calls == []
    assert kit.commits() == 0


def test_fresh_policy_stricter_outcome(kit, monkeypatch):
    """The fresh decision is computed at commit: REVIEW after an ALLOW receipt is AP-STALE-07 (G2)."""
    from actionproof import policy

    req, receipt = _allow(kit)
    monkeypatch.setattr(gate_mod.policy, "decide", lambda *a: policy.Decision(
        "REVIEW", [gate_mod.Reason("AP-INV-04", "G1", "variance > 100")]))
    c = kit.gate.commit(receipt, req)
    assert [(x.rule, x.guarantee) for x in c.reasons] == [("AP-STALE-07", "G2")] and kit.tool.calls == []
