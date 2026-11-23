"""USP G1 (ADR-033): only a policy revision signed by a trusted policy-authority key may decide.

ADR-028 proves WHICH policy decided (the revision OPA loaded). This proves an AUTHORISED owner published it: with
POLICY_AUTHORITY_KEYS set, decide() (prepare AND the commit re-check) verifies `<archive>/<revision>/signature.json`
against a separate Ed25519 authority key before evaluating, and anything else is DENY AP-POL-FAIL / G1. Real OPA and
Postgres; signatures are made with scripts/policy_sign.py.
"""
import base64
import importlib.util
import json
import urllib.parse
from pathlib import Path

import httpx
import pytest
from gatekit import INVOICE_TOOL, REFUND_TOOL, KitGate, rules

from actionproof import policy
from actionproof.config import ConfigError, Settings, load_settings
from actionproof.gate import PAYLOAD_KEYS
from actionproof.signing import Signer

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("policy_sign", ROOT / "scripts" / "policy_sign.py")
policy_sign = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(policy_sign)


# ------------------------------------------------------------------------------------------------------ helpers
def _keygen(tmp_path, name, capsys):
    seed = tmp_path / f"{name}.seed"
    capsys.readouterr()  # drop earlier output
    assert policy_sign.main(["keygen", "--seed", str(seed)]) == 0
    pub = capsys.readouterr().out.strip()
    raw = seed.read_bytes()
    for form in (raw.hex(), base64.b64encode(raw).decode()):  # only the PUBLIC key is printed
        assert form not in pub
    assert len(base64.b64decode(pub, validate=True)) == 32
    return seed, pub


def _keys_file(path, entries):
    path.write_text(json.dumps({"keys": {kid: {"pub": pub, "status": st} for kid, (pub, st) in entries.items()}}))
    return path


def _sign(seed, kid, archive, revision=None):
    argv = ["sign", "--seed", str(seed), "--kid", kid, "--archive", str(archive)]
    assert policy_sign.main(argv + (["--revision", revision] if revision else [])) == 0


@pytest.fixture
def authority(tmp_path, capsys):
    """An archive of policy/ signed by authority kid `pa1`, and a keys file trusting it."""
    archive = tmp_path / "archive"
    rev = policy.archive_policy(ROOT / "policy", archive)
    seed, pub = _keygen(tmp_path, "pa1", capsys)
    _sign(seed, "pa1", archive)
    keys = _keys_file(tmp_path / "authority.json", {"pa1": (pub, "active")})
    return {"archive": archive, "rev": rev, "seed": seed, "pub": pub, "keys": keys}


def _decide(opa_url, a, payload=None):
    return policy.decide(payload or {}, opa_url, 5, str(a["keys"]), str(a["archive"]))


def _pol_fail(d, text):
    assert d.outcome == "DENY" and [r.rule for r in d.reasons] == ["AP-POL-FAIL"], d
    assert d.reasons[0].guarantee == "G1" and text in d.reasons[0].msg, d.reasons[0].msg
    assert d.signed_by is None


def _loaded(opa_url):
    mods = httpx.get(f"{opa_url}/v1/policies", timeout=5).json()["result"]
    return next((m["id"], m["raw"]) for m in mods if m["raw"].lstrip().startswith("package actionproof\n"))


@pytest.fixture
def mutable_policy(opa_url):
    mid, raw = _loaded(opa_url)

    def put(text):
        r = httpx.put(f"{opa_url}/v1/policies/{urllib.parse.quote(mid, safe='/')}", content=text.encode(), timeout=5)
        assert r.status_code == 200, r.text

    yield put
    put(raw)


def _signed_gate(kit, a):
    s = kit.settings.model_copy(update={"policy_authority_keys": str(a["keys"]), "policy_archive_dir": str(a["archive"])})
    kit.gate = KitGate(s, kit.signer, kit.factory, {INVOICE_TOOL: kit.tool, REFUND_TOOL: kit.refunds})
    return kit


# ----------------------------------------------------------------------------------------- decide(): signature
def test_valid_signature_decides_and_names_the_authority(opa_url, authority):
    d = _decide(opa_url, authority)
    assert "AP-POL-FAIL" not in [r.rule for r in d.reasons]  # the policy itself evaluated the input
    assert d.signed_by == "pa1" and d.revision == authority["rev"]


def test_unsigned_revision_denies(opa_url, authority):
    (authority["archive"] / authority["rev"] / "signature.json").unlink()
    _pol_fail(_decide(opa_url, authority), "unsigned")


def test_tampered_policy_text_changes_the_revision_and_denies(opa_url, authority, mutable_policy):
    _, raw = _loaded(opa_url)
    mutable_policy(raw + "\n# pushed straight to OPA by someone without the authority key\n")
    _pol_fail(_decide(opa_url, authority), "unsigned")


def test_unknown_authority_key_denies(opa_url, authority, tmp_path, capsys):
    seed, _ = _keygen(tmp_path, "rogue", capsys)
    _sign(seed, "rogue", authority["archive"])  # overwrites the signature with one by an untrusted kid
    _pol_fail(_decide(opa_url, authority), "unknown")


def test_kid_claiming_a_trusted_name_with_another_key_is_a_bad_signature(opa_url, authority, tmp_path, capsys):
    seed, _ = _keygen(tmp_path, "rogue", capsys)
    _sign(seed, "pa1", authority["archive"])  # right kid, wrong key
    _pol_fail(_decide(opa_url, authority), "bad signature")


def test_revoked_authority_key_denies(opa_url, authority):
    _keys_file(authority["keys"], {"pa1": (authority["pub"], "revoked")})
    _pol_fail(_decide(opa_url, authority), "revoked")


def test_retired_key_still_verifies_its_old_revisions(opa_url, authority, tmp_path, capsys):
    _, pub2 = _keygen(tmp_path, "pa2", capsys)  # rotation: pa2 signs from now on, pa1's revisions still verify
    _keys_file(authority["keys"], {"pa1": (authority["pub"], "retired"), "pa2": (pub2, "active")})
    assert _decide(opa_url, authority).signed_by == "pa1"


def test_signature_over_another_revision_denies(opa_url, authority, tmp_path):
    other = tmp_path / "other-policy"
    other.mkdir()
    (other / "actionproof.rego").write_text("package actionproof\ndefault decision := {}\n")
    rev2 = policy.archive_policy(other, authority["archive"])
    _sign(authority["seed"], "pa1", authority["archive"], rev2)
    sig = authority["archive"] / authority["rev"] / "signature.json"
    sig.write_text((authority["archive"] / rev2 / "signature.json").read_text())  # a valid signature, for rev2
    _pol_fail(_decide(opa_url, authority), "another revision")


@pytest.mark.parametrize("body", [
    "not json", "[]", "{}", json.dumps({"payload": {}, "sig": "x", "kid": "pa1"}),
])
def test_malformed_signature_file_denies(opa_url, authority, body):
    (authority["archive"] / authority["rev"] / "signature.json").write_text(body)
    _pol_fail(_decide(opa_url, authority), "malformed")


def test_edited_statement_is_a_bad_signature(opa_url, authority):
    f = authority["archive"] / authority["rev"] / "signature.json"
    doc = json.loads(f.read_text())
    doc["payload"]["signed_at"] += 1
    f.write_text(json.dumps(doc))
    _pol_fail(_decide(opa_url, authority), "bad signature")


def test_malformed_or_missing_keys_file_denies(opa_url, authority):
    authority["keys"].write_text("{not json")
    _pol_fail(_decide(opa_url, authority), "authority keys")
    authority["keys"].unlink()
    _pol_fail(_decide(opa_url, authority), "authority keys")


def test_no_authority_configured_keeps_todays_behaviour(opa_url):
    d = policy.decide({}, opa_url, 5)
    assert "AP-POL-FAIL" not in [r.rule for r in d.reasons] and d.revision and d.signed_by is None


# ---------------------------------------------------------------------------------------------- config load
def _env(tmp_path, signing_key_path, **extra):
    return {"DATABASE_URL": "postgresql://u:p@localhost:5433/db", "OPA_URL": "http://localhost:8181",
            "TESSERACT_CMD": "tesseract", "SIGNING_KEY_PATH": str(signing_key_path), **extra}


def test_config_accepts_a_separate_authority_key(tmp_path, signing_key_path, authority):
    s = load_settings(_env(tmp_path, signing_key_path, POLICY_AUTHORITY_KEYS=str(authority["keys"]),
                           POLICY_ARCHIVE_DIR=str(authority["archive"])))
    assert s.policy_authority_keys == str(authority["keys"])
    assert load_settings(_env(tmp_path, signing_key_path)).policy_authority_keys is None  # the default: off


def test_config_refuses_the_receipt_key_as_an_authority_key(tmp_path, signing_key_path, authority):
    receipt_pub = Signer.from_path(signing_key_path, "k1").public_key_b64()  # the gate's receipt-signing key
    keys = _keys_file(tmp_path / "bad.json", {"pa1": (authority["pub"], "retired"), "oops": (receipt_pub, "active")})
    with pytest.raises(ConfigError) as e:
        load_settings(_env(tmp_path, signing_key_path, POLICY_AUTHORITY_KEYS=str(keys),
                           POLICY_ARCHIVE_DIR=str(authority["archive"])))
    assert "POLICY_AUTHORITY_KEYS" in str(e.value)


def test_config_refuses_a_receipt_registry_key_as_an_authority_key(tmp_path, signing_key_path, authority):
    registry = _keys_file(tmp_path / "receipt-registry.json", {"r0": (authority["pub"], "retired")})
    with pytest.raises(ConfigError):
        load_settings(_env(tmp_path, signing_key_path, KEY_REGISTRY_PATH=str(registry),
                           POLICY_AUTHORITY_KEYS=str(authority["keys"]), POLICY_ARCHIVE_DIR=str(authority["archive"])))


def test_no_setting_accepts_a_private_key(tmp_path, signing_key_path, authority):
    seed_b64 = base64.b64encode(authority["seed"].read_bytes()).decode()
    with_seed = tmp_path / "with-seed.json"
    with_seed.write_text(json.dumps({"keys": {"pa1": {"pub": authority["pub"], "status": "active", "seed": seed_b64}}}))
    for bad in (str(authority["seed"]), str(with_seed), seed_b64):  # a raw seed file, a seed field, a seed value
        with pytest.raises(ConfigError):
            load_settings(_env(tmp_path, signing_key_path, POLICY_AUTHORITY_KEYS=bad,
                               POLICY_ARCHIVE_DIR=str(authority["archive"])))


def test_config_requires_the_archive_dir_and_a_valid_keys_file(tmp_path, signing_key_path, authority):
    base = dict(database_url="postgresql://x", opa_url="http://x", tesseract_cmd="t",
                signing_key_path=str(signing_key_path))
    with pytest.raises(ValueError):
        Settings(**base, policy_authority_keys=str(authority["keys"]))  # no archive to find signatures in
    two_active = _keys_file(tmp_path / "two.json", {"a": (authority["pub"], "active"),
                                                    "b": (base64.b64encode(b"\x01" * 32).decode(), "active")})
    with pytest.raises(ValueError):
        Settings(**base, policy_authority_keys=str(two_active), policy_archive_dir=str(authority["archive"]))


# ------------------------------------------------------------------------------------- the gate: prepare+commit
def test_gate_signed_policy_allows_and_audit_names_the_authority(kit, authority):
    _signed_gate(kit, authority)
    req, docs = kit.json_request("INV-PA01", "100.00")
    res = kit.gate.prepare(req, docs)
    assert res.decision == "ALLOW"
    assert set(res.receipt["payload"]) == PAYLOAD_KEYS  # receipts keep their shape: no signed_by in them
    detail = kit.sql("SELECT detail FROM audit_log WHERE kind = 'prepare' ORDER BY seq DESC LIMIT 1")[0][0]
    assert detail["policy"]["signed_by"] == "pa1" and detail["policy"]["revision"] == authority["rev"]
    assert kit.gate.commit(res.receipt, req).outcome == "EXECUTED"


def test_gate_unsigned_policy_denies_prepare(kit, authority):
    (authority["archive"] / authority["rev"] / "signature.json").unlink()
    _signed_gate(kit, authority)
    req, docs = kit.json_request("INV-PA02", "100.00")
    res = kit.gate.prepare(req, docs)
    assert res.decision == "DENY" and "AP-POL-FAIL" in rules(res) and res.receipt is None


def test_commit_recheck_enforces_the_signature_when_opa_switches(kit, authority, opa_url, mutable_policy):
    _signed_gate(kit, authority)
    req, docs = kit.json_request("INV-PA03", "100.00")
    receipt = kit.gate.prepare(req, docs).receipt
    _, raw = _loaded(opa_url)
    mutable_policy(raw + "\n# unsigned revision pushed between prepare and commit\n")
    c = kit.gate.commit(receipt, req)
    assert c.outcome != "EXECUTED" and kit.tool.calls == []
    assert rules(c) == ["AP-POL-FAIL"]  # the signature check, not merely the ADR-028 revision move (AP-STALE-07)


def test_commit_recheck_enforces_revocation_between_prepare_and_commit(kit, authority):
    _signed_gate(kit, authority)
    req, docs = kit.json_request("INV-PA04", "100.00")
    receipt = kit.gate.prepare(req, docs).receipt
    _keys_file(authority["keys"], {"pa1": (authority["pub"], "revoked")})  # compromise reported mid-flight
    c = kit.gate.commit(receipt, req)
    assert rules(c) == ["AP-POL-FAIL"] and c.outcome != "EXECUTED" and kit.tool.calls == []


def test_gate_without_authority_records_no_signer(kit):
    req, docs = kit.json_request("INV-PA05", "100.00")
    kit.gate.prepare(req, docs)
    detail = kit.sql("SELECT detail FROM audit_log WHERE kind = 'prepare' ORDER BY seq DESC LIMIT 1")[0][0]
    assert detail["policy"]["signed_by"] is None


def test_sign_script_refuses_the_receipt_signing_key(tmp_path, signing_key_path, monkeypatch, authority):
    monkeypatch.setenv("SIGNING_KEY_PATH", str(signing_key_path))
    assert policy_sign.main(["sign", "--seed", str(signing_key_path), "--kid", "pa1",
                             "--archive", str(authority["archive"])]) != 0
