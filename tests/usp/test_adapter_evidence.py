"""USP G1+G2 (ADR-035): an adapter can say "definitely not applied" only with evidence the gate can verify.

The adapter contract: CONFIRMED (the tool returned), DEFINITE_FAILURE (journal.DefiniteFailure carrying a signed
adapter statement: op "execute", status NOT_APPLIED, a typed reason code and the provider response digest, bound to
THIS execution's idempotency key, amount and counterparty, signed by a key in the gate's adapter trust registry), or
AMBIGUOUS (anything else). An unsigned, untrusted, mismatched or malformed failure claim is AMBIGUOUS
(EXECUTION_UNKNOWN), never a release. A verified definite failure is EXECUTION_FAILED with the evidence (kid, digest,
reason) in the journal detail, and accounting is unchanged (ADR-010): the receipt stays spent, the amount stays
counted, the record stays quarantined. The mock adapter's signing key lives in tests/fixtures only.
"""
from decimal import Decimal
from pathlib import Path

import pytest
from gatekit import INVOICE_TOOL, rules

from actionproof import evidence, gate as gate_mod, journal
from actionproof.signing import KeyRegistry, Signer, generate_key

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "adapter-evidence.seed"
ADAPTER = Signer.from_path(FIXTURE, "adapter-test-1")
TRUST = KeyRegistry.for_signer(ADAPTER)


def _prepared(kit, invoice, total="100.00"):
    kit.set_scope("5000.00")
    req, docs = kit.json_request(invoice, total)
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW", r.reasons
    return req, r.receipt


def _statement(invoice, total="100.00", **over):
    s = evidence.statement("execute", f"idem-{invoice}", "NOT_APPLIED", total, "V-ACME", b'{"declined":true}',
                           reason="CARD_DECLINED")
    s.update(over)
    return s


def _decline_with(kit, env):
    def declined(*a, **kw):
        raise journal.DefiniteFailure("downstream declined; nothing applied", evidence=env)

    kit.tool.execute = declined


def _events(kit, nonce):
    return kit.sql("SELECT event, detail FROM execution_journal WHERE nonce = %s ORDER BY seq", (nonce,))


def test_signed_definite_failure_is_failed_with_evidence_and_still_burned(kit):
    kit.gate._adapter_keys = TRUST
    req, receipt = _prepared(kit, "INV-E1")
    _decline_with(kit, ADAPTER.sign(_statement("INV-E1")))
    res = kit.gate.commit(receipt, req)
    assert res.outcome == "DENY" and rules(res) == ["AP-ERR-11"]
    nonce = receipt["payload"]["nonce"]
    ev = _events(kit, nonce)
    assert [e[0] for e in ev] == ["RESERVATION_CREATED", "DISPATCH_STARTED", "EXECUTION_FAILED"]
    digest = evidence.statement("execute", "x", "NOT_APPLIED", "1.00", "x", b'{"declined":true}')["response_digest"]
    assert ev[-1][1] == {"error": "DefiniteFailure",
                         "evidence": {"kid": "adapter-test-1", "digest": digest, "reason": "CARD_DECLINED"}}
    # ADR-010 unchanged: a definite failure does not un-burn the key, the cap or the quarantine.
    assert rules(kit.gate.commit(receipt, req)) == ["AP-REP-05"]
    assert kit.sql("SELECT amount FROM reservations") == [(Decimal("100.00"),)]
    assert kit.sql("SELECT record_id FROM quarantine") == [("invoice:INV-E1",)]


@pytest.mark.parametrize("case", ["bare", "untrusted_key", "tampered", "other_key", "other_amount",
                                  "other_counterparty", "applied", "no_reason", "bad_digest", "lookup_op",
                                  "float", "extra_field", "not_an_envelope"])
def test_unverifiable_failure_claim_is_unknown(kit, tmp_path, case):
    kit.gate._adapter_keys = TRUST
    req, receipt = _prepared(kit, "INV-E2")
    s = _statement("INV-E2")
    if case == "bare":
        env = None
    elif case == "untrusted_key":
        generate_key(tmp_path / "rogue.seed")
        env = Signer.from_path(tmp_path / "rogue.seed", "adapter-test-1").sign(s)  # same kid, wrong key
    elif case == "tampered":
        env = ADAPTER.sign(s)
        env["payload"] = {**env["payload"], "amount": "1.00"}
    else:
        over = {"other_key": {"idempotency_key": "idem-other"}, "other_amount": {"amount": "100.01"},
                "other_counterparty": {"counterparty": "V-EVIL"}, "applied": {"status": "APPLIED"},
                "no_reason": {"reason": ""}, "bad_digest": {"response_digest": "abc"},
                "lookup_op": {"op": "lookup"}, "extra_field": {"note": "x"}}.get(case, {})
        env = ADAPTER.sign({**s, **over}) if case not in ("float", "not_an_envelope") else None
        if case == "float":  # signing refuses floats, so forge the envelope by hand
            env = {"payload": {**s, "ts": 1.5}, "sig": ADAPTER.sign(s)["sig"], "kid": ADAPTER.kid}
        if case == "not_an_envelope":
            env = "declined, trust me"
    _decline_with(kit, env)
    assert rules(kit.gate.commit(receipt, req)) == ["AP-ERR-11"]
    ev = _events(kit, receipt["payload"]["nonce"])
    assert [e[0] for e in ev] == ["RESERVATION_CREATED", "DISPATCH_STARTED", "EXECUTION_UNKNOWN"]
    assert ev[-1][1] == {"error": "DefiniteFailure", "evidence": "unverified"}
    assert kit.sql("SELECT amount FROM reservations") == [(Decimal("100.00"),)]


def test_no_adapter_trust_configured_means_every_failure_claim_is_unknown(kit):
    assert kit.gate._adapter_keys is None  # the setting-free default trusts no adapter key
    req, receipt = _prepared(kit, "INV-E3")
    _decline_with(kit, ADAPTER.sign(_statement("INV-E3")))
    kit.gate.commit(receipt, req)
    assert _events(kit, receipt["payload"]["nonce"])[-1][0] == "EXECUTION_UNKNOWN"


def test_revoked_adapter_key_is_unknown(kit, tmp_path):
    generate_key(tmp_path / "new.seed")
    new = Signer.from_path(tmp_path / "new.seed", "adapter-test-2")
    kit.gate._adapter_keys = KeyRegistry({"adapter-test-1": (ADAPTER.public_key_b64(), "revoked"),
                                          "adapter-test-2": (new.public_key_b64(), "active")})
    req, receipt = _prepared(kit, "INV-E4")
    _decline_with(kit, ADAPTER.sign(_statement("INV-E4")))
    kit.gate.commit(receipt, req)
    assert _events(kit, receipt["payload"]["nonce"])[-1][0] == "EXECUTION_UNKNOWN"


def test_ambiguous_errors_keep_their_existing_detail(kit):
    kit.gate._adapter_keys = TRUST
    req, receipt = _prepared(kit, "INV-E5")

    def boom(*a, **kw):
        raise TimeoutError("response lost")

    kit.tool.execute = boom
    kit.gate.commit(receipt, req)
    assert _events(kit, receipt["payload"]["nonce"])[-1] == ("EXECUTION_UNKNOWN", {"error": "TimeoutError"})


def test_mock_adapter_declines_with_signed_evidence_and_no_effect(kit):
    kit.gate._adapter_keys = TRUST
    req, receipt = _prepared(kit, "INV-E6")
    kit.tool.evidence_signer, kit.tool.decline_reason = ADAPTER, "INSUFFICIENT_FUNDS"
    assert rules(kit.gate.commit(receipt, req)) == ["AP-ERR-11"]
    ev = _events(kit, receipt["payload"]["nonce"])
    assert ev[-1][0] == "EXECUTION_FAILED" and ev[-1][1]["evidence"]["reason"] == "INSUFFICIENT_FUNDS"
    assert kit.tool.calls == [] and kit.version("invoice:INV-E6") == 1


def test_adapter_trust_must_not_hold_the_receipt_key(kit):
    with pytest.raises(ValueError):
        gate_mod.Gate(kit.settings, kit.signer, kit.factory, kit.tool,
                      adapter_keys=KeyRegistry.for_signer(kit.signer))
    g = gate_mod.Gate(kit.settings, kit.signer, kit.factory, kit.tool, adapter_keys=TRUST)
    assert g._adapter_keys is TRUST


@pytest.mark.parametrize("junk", [None, 1, "x", [], {}, {"payload": None, "sig": "", "kid": ""}])
def test_verification_never_raises_on_junk(junk):
    x = {"idempotency_key": "k", "amount": "1.00", "vendor_id": "V"}
    assert evidence.verified(junk, x, TRUST, "execute") is None
    assert evidence.lookup_outcome(junk, x, TRUST, 10**10) == (evidence.AMBIGUOUS, None)
    assert evidence.verified(ADAPTER.sign(evidence.statement("execute", "k", "NOT_APPLIED", "1.00", "V", b"",
                                                             reason="NO")), x, None, "execute") is None
