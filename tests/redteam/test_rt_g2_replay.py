"""Red team (Phase 3 gate), G2: an approval applied twice or out of context.

Every assertion encodes the SAFE behavior. A failing test here is a finding.
"""
import base64
import copy

from gatekit import AGENT, rules

from actionproof import gate as gate_mod
from actionproof.gate import Principal
from attacks._concurrency import race

ROUNDS = 10
L = 2**252 + 27742317777372353535851937790883648493  # Ed25519 group order


def _allow(kit, inv="INV-RTR1", idem=None, principal=AGENT, **kw):
    req, docs = kit.json_request(inv, "100.00", idem=idem, **kw)
    p = kit.gate.prepare(req, docs, principal=principal)
    assert p.decision == "ALLOW", p.reasons
    return req, p.receipt


def _review(kit, inv="INV-RTR2", idem=None):
    req, docs = kit.json_request(inv, "1000.00", "500.00", idem=idem)
    p = kit.gate.prepare(req, docs)
    assert p.decision == "REVIEW", p.reasons
    return req, p.receipt


def _reset(kit):
    kit.sql("DELETE FROM commits")
    kit.sql("DELETE FROM review_tokens")
    kit.tool.calls.clear()
    kit.tool._results.clear()
    kit.executes = 0


def test_burned_receipt_then_reprepare_with_new_key(kit):
    """Tool fails AFTER its effect: the gate rolls back and burns nonce + idempotency key, but the invoice record
    stays 'open'. A fresh prepare with a new idempotency key approves the same invoice again -> the tool's effect
    happens twice for one invoice (with a real payment rail, a double payment). ADR-010: 'the tool-side idempotency
    key bounds that' - not when the agent picks a new key."""
    kit.tool.fail_after_effect = True
    req, receipt = _allow(kit, "INV-RTR3", idem="burn-1")
    assert kit.gate.commit(receipt, req).outcome == "DENY"
    assert len(kit.tool.calls) == 1  # the effect happened tool-side
    kit.tool.fail_after_effect = False
    # ADR-014: the burned record is quarantined, so the re-prepare itself is refused (no receipt to commit).
    req2, docs2 = kit.json_request("INV-RTR3", "100.00", idem="burn-2", seed=False)
    p2 = kit.gate.prepare(req2, docs2)
    if p2.receipt is not None:
        kit.gate.commit(p2.receipt, req2)
    assert len(kit.tool.calls) == 1, "same invoice approved again after a burned (unknown-outcome) commit"


def test_burned_receipt_then_reprepare_same_key(kit):
    """Same idempotency key after a burn -> AP-REP-05 (HELD). Since ADR-014 the refusal comes at prepare (the
    record is quarantined), so there is no second receipt; the rule and the single tool call are unchanged."""
    kit.tool.fail_after_effect = True
    req, receipt = _allow(kit, "INV-RTR4", idem="burn-same")
    assert kit.gate.commit(receipt, req).outcome == "DENY"
    kit.tool.fail_after_effect = False
    req2, docs2 = kit.json_request("INV-RTR4", "100.00", idem="burn-same", seed=False)
    p2 = kit.gate.prepare(req2, docs2)
    assert p2.receipt is None and rules(p2) == ["AP-REP-05"]
    assert rules(kit.gate.commit(receipt, req)) == ["AP-REP-05"]  # the burned receipt itself stays spent
    assert len(kit.tool.calls) == 1


def test_receipt_prepared_before_burn_blocked_at_commit(kit):
    """A second receipt for the same invoice, prepared BEFORE the first commit burned, is refused inside the commit
    tx by the quarantine (ADR-014), even though its own nonce and key are fresh."""
    kit.tool.fail_after_effect = True
    a, ra = _allow(kit, "INV-RTRQ", idem="q-a")
    b, rb = _allow(kit, "INV-RTRQ", idem="q-b", seed=False)
    assert kit.gate.commit(ra, a).outcome == "DENY"
    kit.tool.fail_after_effect = False
    assert rules(kit.gate.commit(rb, b)) == ["AP-REP-05"]
    assert len(kit.tool.calls) == 1


def test_release_quarantine_reconciles(kit):
    """After a human reconciles (the tool's effect did NOT happen on the rail), release_quarantine lifts the block."""
    kit.tool.fail_after_effect = True
    req, receipt = _allow(kit, "INV-RTRR", idem="rel-1")
    assert kit.gate.commit(receipt, req).outcome == "DENY"
    kit.tool.fail_after_effect = False
    assert kit.sql("SELECT record_id FROM quarantine") == [("invoice:INV-RTRR",)]
    for bad in (("", "alice"), ("invoice:INV-RTRR", " ")):
        try:
            kit.gate.release_quarantine(*bad)
            raise AssertionError("bad input accepted")
        except ValueError:
            pass
    assert kit.gate.release_quarantine("invoice:INV-RTRR", "alice") is True
    assert kit.gate.release_quarantine("invoice:INV-RTRR", "alice") is False
    kit.tool.calls.clear()
    kit.tool._results.clear()
    req2, receipt2 = _allow(kit, "INV-RTRR", idem="rel-2", seed=False)
    assert kit.gate.commit(receipt2, req2).outcome == "EXECUTED" and len(kit.tool.calls) == 1


def test_same_receipt_two_threads(kit):
    """Two threads commit the same receipt at once: the tool runs once (HELD)."""
    for n in range(ROUNDS):
        _reset(kit)
        req, receipt = _allow(kit, f"INV-RTC{n}", idem=f"conc-{n}")
        out = race(lambda: kit.gate.commit(receipt, req), lambda: kit.gate.commit(receipt, req))
        assert sorted(o.outcome for o in out) == ["DENY", "EXECUTED"], (n, out)
        assert len(kit.tool.calls) == 1 and kit.executes == 1, n


def test_review_token_two_threads(kit):
    """One review token, same receipt, two threads: one execution (HELD)."""
    for n in range(ROUNDS):
        _reset(kit)
        req, receipt = _review(kit, f"INV-RTV{n}", idem=f"rv-{n}")
        tok = kit.mint(req)
        out = race(lambda: kit.gate.commit(receipt, req, review_token=tok),
                   lambda: kit.gate.commit(receipt, req, review_token=tok))
        assert sorted(o.outcome for o in out) == ["DENY", "EXECUTED"], (n, out)
        assert len(kit.tool.calls) == 1, n


def test_review_token_minted_for_other_request(kit):
    """Token for request A presented with REVIEW receipt B (HELD)."""
    a, _ = _review(kit, "INV-RTR5", idem="tok-a")
    b, rb = _review(kit, "INV-RTR6", idem="tok-b")
    tok = kit.mint(a)
    c = kit.gate.commit(rb, b, review_token=tok)
    assert c.outcome == "DENY" and rules(c) == ["AP-REV-10"] and kit.tool.calls == []


def test_review_token_reused_after_success(kit):
    """A consumed token cannot authorize a re-prepared receipt of the same request (HELD)."""
    req, receipt = _review(kit, "INV-RTR7", idem="tok-reuse")
    tok = kit.mint(req)
    assert kit.gate.commit(receipt, req, review_token=tok).outcome == "EXECUTED"
    kit.sql("UPDATE records SET data = data || '{\"status\": \"open\"}'::jsonb WHERE record_id = 'invoice:INV-RTR7'")
    p = kit.gate.prepare(req, kit.json_request("INV-RTR7", "1000.00", "500.00", seed=False)[1])
    if p.receipt is not None:
        kit.gate.commit(p.receipt, req, review_token=tok)
    assert len(kit.tool.calls) == 1


def test_receipt_exp_equals_now(kit, monkeypatch):
    """exp == now is expired (HELD)."""
    req, receipt = _allow(kit, "INV-RTR8")
    monkeypatch.setattr(gate_mod, "_now", lambda: receipt["payload"]["exp"])
    c = kit.gate.commit(receipt, req)
    assert rules(c) == ["AP-EXP-06"] and kit.tool.calls == []


def test_receipt_expires_one_second_later_boundary(kit, monkeypatch):
    """exp - 1 at the first check, exp at the in-lane check: denied (HELD)."""
    req, receipt = _allow(kit, "INV-RTR9")
    exp = receipt["payload"]["exp"]
    ticks = iter([exp - 1] + [exp] * 10)
    monkeypatch.setattr(gate_mod, "_now", lambda: next(ticks))
    c = kit.gate.commit(receipt, req)
    assert rules(c) == ["AP-EXP-06"] and kit.tool.calls == []


def test_receipt_payload_tamper_variants(kit):
    """Extra key, decision flip, int-as-string exp, swapped record_id: signature fails (HELD)."""
    req, receipt = _allow(kit, "INV-RTRA")
    for mut in (lambda p: p.update(extra=1), lambda p: p.update(decision="ALLOW "),
                lambda p: p.update(exp=str(p["exp"])), lambda p: p.update(record_id="invoice:INV-2048"),
                lambda p: p.update(exp=True)):
        r = copy.deepcopy(receipt)
        mut(r["payload"])
        c = kit.gate.commit(r, req)
        assert c.outcome == "DENY" and rules(c) == ["AP-SIG-09"]
    assert kit.tool.calls == []


def test_signature_malleability_s_plus_l(kit):
    """A second valid-looking signature (S + L) must not verify (HELD; replay is keyed by nonce anyway)."""
    req, receipt = _allow(kit, "INV-RTRB")
    sig = base64.b64decode(receipt["sig"])
    s = int.from_bytes(sig[32:], "little") + L
    if s < 2**256:
        r = copy.deepcopy(receipt)
        r["sig"] = base64.b64encode(sig[:32] + s.to_bytes(32, "little")).decode()
        assert rules(kit.gate.commit(r, req)) == ["AP-SIG-09"]
    assert kit.gate.commit(receipt, req).outcome == "EXECUTED"
    assert len(kit.tool.calls) == 1


def test_idempotency_key_reuse_across_actors(kit):
    """Actor B reusing actor A's idempotency key for another invoice: denied, tool not called again (HELD)."""
    a, ra = _allow(kit, "INV-RTRC", idem="shared-key")
    assert kit.gate.commit(ra, a).outcome == "EXECUTED"
    agent9 = Principal("agent-9", "user-123")
    b, rb = _allow(kit, "INV-RTRD", idem="shared-key", actor="agent-9", principal=agent9)
    assert rules(kit.gate.commit(rb, b, principal=agent9)) == ["AP-REP-05"]
    assert len(kit.tool.calls) == 1


def test_two_receipts_same_record_two_threads(kit):
    """Two receipts (different keys) for the same invoice raced: one execution (HELD)."""
    for n in range(ROUNDS):
        _reset(kit)
        a, ra = _allow(kit, f"INV-RTS{n}", idem=f"s-{n}-a")
        b, rb = _allow(kit, f"INV-RTS{n}", idem=f"s-{n}-b", seed=False)
        out = race(lambda: kit.gate.commit(ra, a), lambda: kit.gate.commit(rb, b))
        assert sorted(o.outcome for o in out) == ["DENY", "EXECUTED"], (n, out)
        assert len(kit.tool.calls) == 1, n


def test_receipt_for_one_request_with_mutated_request(kit):
    """Mutating a non-authority field (note) or whitespace in idempotency_key changes the hash (HELD)."""
    req, receipt = _allow(kit, "INV-RTRE")
    for upd in ({"idempotency_key": req.idempotency_key + " "}, {"actor": "agent-7 "}):
        assert rules(kit.gate.commit(receipt, req.model_copy(update=upd))) == ["AP-HASH-08"]
    assert kit.tool.calls == []


def test_key_not_exposed(kit, signing_key_path):
    """Seed never appears in repr/str of gate, signer, results, or deny reasons (HELD)."""
    seed = signing_key_path.read_bytes()
    forms = {seed.hex(), base64.b64encode(seed).decode(), repr(seed)}
    req, docs = kit.json_request("INV-RTRF", "100.00")
    p = kit.gate.prepare(req, docs)
    c = kit.gate.commit({"payload": {}, "sig": "x", "kid": "k"}, req)
    blob = " ".join(map(repr, (kit.gate, kit.signer, p, c, p.receipt))) + str(kit.gate)
    assert not any(f in blob for f in forms)
