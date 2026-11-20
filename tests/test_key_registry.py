"""KeyRegistry: a receipt is verified with the key of ITS kid (active, retired) and never with another kid's key.

Unknown and revoked kids fail, a kid that names someone else's key fails, and a corrupt registry fails to load.
Uses real Postgres only for the gate rotation tests (the kit fixture); the registry itself is pure.
"""
import json
from pathlib import Path

import pytest
from gatekit import INVOICE_TOOL, rules

from actionproof import audit
from actionproof.signing import KeyRegistry, Signer, generate_key

PAYLOAD = {"request_hash": "ab" * 32, "decision": "ALLOW", "reasons": [], "version": 1,
           "nonce": "n1", "exp": 1_900_000_000, "amount": "4800.00"}


def _signer(tmp_path, kid):
    generate_key(tmp_path / f"{kid}.key")
    return Signer.from_path(tmp_path / f"{kid}.key", kid)


def _registry(**entries):
    return KeyRegistry({kid: (s.public_key_b64(), status) for kid, (s, status) in entries.items()})


def test_active_and_retired_keys_verify_their_own_receipts(tmp_path):
    k1, k2 = _signer(tmp_path, "k1"), _signer(tmp_path, "k2")
    reg = _registry(k1=(k1, "retired"), k2=(k2, "active"))
    assert reg.verify(k2.sign(PAYLOAD)) and reg.verify(k1.sign(PAYLOAD))  # rotation keeps history verifiable


def test_unknown_kid_fails(tmp_path):
    k1, k9 = _signer(tmp_path, "k1"), _signer(tmp_path, "k9")
    assert not _registry(k1=(k1, "active")).verify(k9.sign(PAYLOAD))


def test_revoked_kid_fails(tmp_path):
    k1 = _signer(tmp_path, "k1")
    assert not _registry(k1=(k1, "revoked")).verify(k1.sign(PAYLOAD))


def test_kid_substitution_fails(tmp_path):
    """Signed by k1's key but labelled k2: the registry checks k2's key, so it fails (no fallback to another key)."""
    k1, k2 = _signer(tmp_path, "k1"), _signer(tmp_path, "k2")
    forged = {**k1.sign(PAYLOAD), "kid": "k2"}
    assert not _registry(k1=(k1, "active"), k2=(k2, "retired")).verify(forged)


def test_malformed_receipts_fail_never_raise(tmp_path):
    k1 = _signer(tmp_path, "k1")
    reg = _registry(k1=(k1, "active"))
    for bad in (None, "x", {}, {"payload": PAYLOAD, "sig": "AA==", "kid": 1}, {"payload": PAYLOAD, "sig": "AA=="}):
        assert reg.verify(bad) is False


def test_public_keys_excludes_revoked(tmp_path):
    k1, k2 = _signer(tmp_path, "k1"), _signer(tmp_path, "k2")
    reg = _registry(k1=(k1, "revoked"), k2=(k2, "active"))
    assert reg.public_keys() == {"k2": k2.public_key_b64()}
    assert set(reg.public_keys(include_revoked=True)) == {"k1", "k2"}


@pytest.mark.parametrize("entries", [
    {"k1": ("not-base64!!", "active")},
    {"k1": ("AAAA", "active")},                       # decodes, wrong length
    {"": ("x", "active")},
])
def test_corrupt_registry_is_refused(entries):
    with pytest.raises(ValueError):
        KeyRegistry(entries)


def test_bad_status_and_two_active_keys_refused(tmp_path):
    k1, k2 = _signer(tmp_path, "k1"), _signer(tmp_path, "k2")
    with pytest.raises(ValueError):
        KeyRegistry({"k1": (k1.public_key_b64(), "paused")})
    with pytest.raises(ValueError):
        KeyRegistry({"k1": (k1.public_key_b64(), "active"), "k2": (k2.public_key_b64(), "active")})


def test_from_json_roundtrip_and_corruption(tmp_path):
    k1, k2 = _signer(tmp_path, "k1"), _signer(tmp_path, "k2")
    p = tmp_path / "keys.json"
    p.write_text(json.dumps({"keys": {"k1": {"pub": k1.public_key_b64(), "status": "retired"},
                                      "k2": {"pub": k2.public_key_b64(), "status": "active"}}}))
    assert KeyRegistry.from_json(p).verify(k1.sign(PAYLOAD))
    for bad in ("{", "[]", json.dumps({"keys": {"k1": {"pub": k1.public_key_b64()}}}),
                json.dumps({"keys": {"k1": {"pub": "AAAA", "status": "active"}}})):
        p.write_text(bad)
        with pytest.raises(ValueError):
            KeyRegistry.from_json(p)
    with pytest.raises(ValueError):
        KeyRegistry.from_json(tmp_path / "missing.json")


def test_same_public_key_under_two_kids_is_refused(tmp_path):
    """One key listed as both k1 (retired) and k2 (active) would let a revoked/old kid launder trust."""
    k1 = _signer(tmp_path, "k1")
    with pytest.raises(ValueError):
        KeyRegistry({"k1": (k1.public_key_b64(), "retired"), "k2": (k1.public_key_b64(), "active")})
    with pytest.raises(ValueError):
        KeyRegistry({"k1": (k1.public_key_b64(), "revoked"), "k2": (k1.public_key_b64(), "retired")})


def test_from_json_refuses_duplicate_fingerprints(tmp_path):
    k1 = _signer(tmp_path, "k1")
    p = tmp_path / "keys.json"
    p.write_text(json.dumps({"keys": {"k1": {"pub": k1.public_key_b64(), "status": "retired"},
                                      "k2": {"pub": k1.public_key_b64(), "status": "active"}}}))
    with pytest.raises(ValueError):
        KeyRegistry.from_json(p)


def test_kid_substitution_every_direction_fails(tmp_path):
    """Relabelling a receipt's kid never borrows another kid's trust: not active<-retired, not retired<-revoked,
    not to an unknown kid, and a revoked kid cannot be swapped for the active one."""
    k1, k2, k3 = _signer(tmp_path, "k1"), _signer(tmp_path, "k2"), _signer(tmp_path, "k3")
    reg = _registry(k1=(k1, "revoked"), k2=(k2, "retired"), k3=(k3, "active"))
    for signer, claimed in ((k1, "k3"), (k1, "k2"), (k2, "k3"), (k3, "k2"), (k3, "k1"), (k2, "k9")):
        forged = {**signer.sign(PAYLOAD), "kid": claimed}
        assert reg.signature_valid(forged) is False and reg.verify(forged) is False, (signer.kid, claimed)


def test_signature_validity_is_separate_from_trust(tmp_path):
    """signature_valid answers 'did the key of this kid sign it' (history, forensics); verify answers 'may it
    authorize now' and fails closed for revoked and unknown kids."""
    k1, k2, k9 = _signer(tmp_path, "k1"), _signer(tmp_path, "k2"), _signer(tmp_path, "k9")
    reg = _registry(k1=(k1, "revoked"), k2=(k2, "retired"))
    assert reg.signature_valid(k1.sign(PAYLOAD)) is True and reg.verify(k1.sign(PAYLOAD)) is False   # revoked
    assert reg.signature_valid(k2.sign(PAYLOAD)) is True and reg.verify(k2.sign(PAYLOAD)) is True    # retired
    assert reg.signature_valid(k9.sign(PAYLOAD)) is False and reg.verify(k9.sign(PAYLOAD)) is False  # unknown
    bad = {**k2.sign(PAYLOAD), "payload": {**PAYLOAD, "amount": "1.00"}}
    assert reg.signature_valid(bad) is False and reg.verify(bad) is False                            # tampered
    assert reg.status("k1") == "revoked" and reg.status("k2") == "retired" and reg.status("zz") is None


# ---- through the gate: rotation while older receipts exist

def _receipt_from_old_key(kit, tmp_path, status):
    """A receipt signed by k1, then the gate rotates to k2 with k1 in the registry as `status`."""
    req, docs = kit.json_request("INV-8201", "100.00")
    r = kit.gate.prepare(req, docs)
    assert r.decision == "ALLOW", r.reasons
    k2 = _signer(tmp_path, "k2")
    reg = KeyRegistry({"k1": (kit.signer.public_key_b64(), status), "k2": (k2.public_key_b64(), "active")})
    from gatekit import KitGate
    kit.gate = KitGate(kit.settings, k2, kit.factory, {INVOICE_TOOL: kit.tool}, registry=reg)
    return req, r.receipt


def test_gate_commits_a_receipt_signed_by_a_retired_key(kit, tmp_path):
    req, receipt = _receipt_from_old_key(kit, tmp_path, "retired")
    assert kit.gate.commit(receipt, req).outcome == "EXECUTED"


def test_gate_refuses_a_receipt_from_a_revoked_key(kit, tmp_path):
    req, receipt = _receipt_from_old_key(kit, tmp_path, "revoked")
    assert rules(kit.gate.commit(receipt, req)) == ["AP-SIG-09"] and kit.executes == 0


def test_gate_without_registry_still_accepts_only_its_own_key(kit, tmp_path):
    """Default behaviour is unchanged: no registry means the signer's own kid is the only trusted key."""
    req, receipt = _receipt_from_old_key(kit, tmp_path, "retired")
    from gatekit import KitGate
    kit.gate = KitGate(kit.settings, _signer(tmp_path, "k3"), kit.factory, {INVOICE_TOOL: kit.tool})
    assert rules(kit.gate.commit(receipt, req)) == ["AP-SIG-09"]


def test_gate_refuses_a_registry_that_disagrees_with_its_signer(kit, tmp_path):
    other = _signer(tmp_path, "k7")
    from gatekit import KitGate
    with pytest.raises(ValueError):
        KitGate(kit.settings, other, kit.factory, {INVOICE_TOOL: kit.tool},
                registry=KeyRegistry({"k7": (kit.signer.public_key_b64(), "active")}))


def test_checkpoints_spanning_two_keys_verify_with_the_registry(kit, tmp_path):
    """Checkpoints written under k1 and then under k2 both verify through registry.public_keys()."""
    req, docs = kit.json_request("INV-8202", "100.00")
    kit.gate.prepare(req, docs)  # a checkpoint signed by k1 (default audit_checkpoint_every=1)
    k2 = _signer(tmp_path, "k2")
    reg = KeyRegistry({"k1": (kit.signer.public_key_b64(), "retired"), "k2": (k2.public_key_b64(), "active")})
    from gatekit import KitGate
    kit.gate = KitGate(kit.settings, k2, kit.factory, {INVOICE_TOOL: kit.tool}, registry=reg)
    req2, docs2 = kit.json_request("INV-8203", "100.00")
    kit.gate.prepare(req2, docs2)  # a checkpoint signed by k2
    kids = {k for (k,) in kit.sql("SELECT DISTINCT kid FROM audit_checkpoints")}
    assert kids == {"k1", "k2"}
    with kit.factory() as conn:
        n, m = audit.verify(conn, reg.public_keys())
    assert n > 0 and m > 0
    with kit.factory() as conn, pytest.raises(audit.AuditFailure):  # k1 revoked: its checkpoints no longer verify
        audit.verify(conn, KeyRegistry({"k1": (kit.signer.public_key_b64(), "revoked"),
                                        "k2": (k2.public_key_b64(), "active")}).public_keys())


def test_server_loads_the_registry_and_refuses_a_bad_one(kit, tmp_path):
    from actionproof import server
    from actionproof.config import ConfigError

    docs = Path(__file__).resolve().parents[1] / "fixtures" / "out"
    ss = server.load_server_settings({"DOCS_DIR": str(docs)}, need_principal=False)
    good = tmp_path / "ok.json"
    good.write_text(json.dumps({"keys": {"k1": {"pub": kit.signer.public_key_b64(), "status": "active"}}}))
    assert server.build_app(kit.settings.model_copy(update={"key_registry_path": str(good)}), ss) is not None
    for body in ("{", json.dumps({"keys": {"k9": {"pub": kit.signer.public_key_b64(), "status": "active"}}})):
        bad = tmp_path / "bad.json"
        bad.write_text(body)
        with pytest.raises(ConfigError):
            server.build_app(kit.settings.model_copy(update={"key_registry_path": str(bad)}), ss)
