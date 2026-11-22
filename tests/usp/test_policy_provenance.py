"""USP G1/G2 (ADR-028): decisions are bound to the policy revision OPA actually has loaded.

The revision is the sha256 of the `package actionproof` modules as OPA reports them (/v1/policies), not of a local
file. A receipt carries it; commit re-reads it and denies (AP-STALE-07) if it moved; the prepare audit entry records it
with the exact policy input so a historical decision can be re-run against the archived artifact. Real OPA + Postgres.
"""
import json
import os
import urllib.parse
from pathlib import Path

import httpx
import pytest
from gatekit import rules

from actionproof import policy

ROOT = Path(__file__).resolve().parents[2]
OPA_BIN = os.environ.get("OPA_BIN", "opa")


def _loaded(opa_url):
    """(module id, raw source) of the loaded `package actionproof` module."""
    mods = httpx.get(f"{opa_url}/v1/policies", timeout=5).json()["result"]
    return next((m["id"], m["raw"]) for m in mods if m["raw"].lstrip().startswith("package actionproof\n"))


def _put(opa_url, mid, raw):
    r = httpx.put(f"{opa_url}/v1/policies/{urllib.parse.quote(mid, safe='/')}", content=raw.encode(), timeout=5)
    assert r.status_code == 200, r.text


@pytest.fixture
def mutable_policy(opa_url):
    """Lets a test edit the loaded policy; always restores the original text."""
    mid, raw = _loaded(opa_url)
    yield lambda new: _put(opa_url, mid, new)
    _put(opa_url, mid, raw)


def test_digest_is_stable_and_covers_only_the_decision_policy(tmp_path):
    base = policy.digest_of_dir(ROOT / "policy")
    mods = {"a.rego": "package actionproof\nx := 1\n", "b_test.rego": "package actionproof_test\n",
            "authz.rego": "package system.authz\n"}
    d = policy.digest_of(mods)
    assert policy.digest_of({**mods, "authz.rego": "package system.authz\nallow := true\n"}) == d  # other packages ignored
    assert policy.digest_of({"dir/a.rego": mods["a.rego"].replace("\n", "\r\n")}) == d  # id prefix and CRLF normalised
    assert policy.digest_of({"a.rego": mods["a.rego"] + "# edit\n"}) != d
    assert policy.digest_of_dir(ROOT / "policy") == base and len(base) == 64


def test_digest_matches_what_opa_loaded(opa_url):
    revision, version = policy.active_revision(opa_url, 5)
    assert revision == policy.digest_of_dir(ROOT / "policy") and version


def test_receipt_carries_the_active_revision_and_it_is_signed(kit, opa_url):
    req, docs = kit.json_request("INV-A001", "100.00")
    receipt = kit.gate.prepare(req, docs).receipt
    assert receipt["payload"]["policy_revision"] == policy.active_revision(opa_url, 5)[0]
    forged = {**receipt, "payload": {**receipt["payload"], "policy_revision": "0" * 64}}
    assert kit.gate.commit(forged, req).outcome != "EXECUTED" and kit.tool.calls == []  # AP-SIG-09


def test_policy_changed_after_prepare_blocks_commit_until_reprepared(kit, opa_url, mutable_policy):
    req, docs = kit.json_request("INV-A002", "100.00")
    receipt = kit.gate.prepare(req, docs).receipt
    _, raw = _loaded(opa_url)
    mutable_policy(raw + "\n# policy revision bump\n")
    c = kit.gate.commit(receipt, req)
    assert rules(c) == ["AP-STALE-07"] and c.outcome != "EXECUTED" and kit.tool.calls == []
    assert any("policy revision" in r.msg for r in c.reasons)
    new = kit.gate.prepare(req, docs).receipt  # re-prepared under the new revision: works
    assert new["payload"]["policy_revision"] != receipt["payload"]["policy_revision"]
    assert kit.gate.commit(new, req).outcome == "EXECUTED"


def test_pending_review_does_not_survive_a_policy_change(kit, opa_url, mutable_policy):
    req, docs = kit.json_request("INV-A003", "4800.00", "4300.00")
    receipt = kit.gate.prepare(req, docs).receipt
    assert receipt["payload"]["decision"] == "REVIEW"
    token = kit.mint(receipt, req)
    _, raw = _loaded(opa_url)
    mutable_policy(raw + "\n# changed after the human review was requested\n")
    c = kit.gate.commit(receipt, req, review_token=token)
    assert rules(c) == ["AP-STALE-07"] and kit.tool.calls == []
    assert kit.sql("SELECT used_at FROM review_tokens") == [(None,)]  # the approval is not burned


def test_old_receipt_shape_without_a_revision_is_refused(kit):
    req, docs = kit.json_request("INV-A004", "100.00")
    p = dict(kit.gate.prepare(req, docs).receipt["payload"])
    del p["policy_revision"]
    c = kit.gate.commit(kit.gate._signer.sign(p), req)  # validly signed, but pre-ADR-028 shape
    assert c.outcome != "EXECUTED" and kit.tool.calls == []


def test_audit_records_provenance_and_the_decision_can_be_reconstructed(kit, opa_url, tmp_path):
    req, docs = kit.json_request("INV-A005", "4800.00", "4300.00")
    res = kit.gate.prepare(req, docs)
    detail = kit.sql("SELECT detail FROM audit_log WHERE kind = 'prepare' ORDER BY seq DESC LIMIT 1")[0][0]
    prov = detail["policy"]
    assert prov["revision"] == res.receipt["payload"]["policy_revision"] and prov["opa_version"]
    assert detail["nonce"] == res.receipt["payload"]["nonce"] and "input" in prov
    archive = tmp_path / "archive"
    policy.archive_policy(ROOT / "policy", archive)
    got = policy.reconstruct(archive, prov["revision"], prov["input"], OPA_BIN)
    assert got["outcome"] == res.decision == "REVIEW"
    assert [r["rule"] for r in got["reasons"]] == [r.rule for r in res.reasons]


def test_unknown_revision_and_incorrect_manifest_are_refused(tmp_path):
    archive = tmp_path / "archive"
    rev = policy.archive_policy(ROOT / "policy", archive)
    with pytest.raises(policy.PolicyArchiveError):
        policy.reconstruct(archive, "f" * 64, {}, OPA_BIN)  # unknown revision
    (archive / rev / "actionproof.rego").write_text("package actionproof\ndefault decision := {}\n")
    with pytest.raises(policy.PolicyArchiveError):  # file no longer matches its manifest digest
        policy.reconstruct(archive, rev, {}, OPA_BIN)
    (archive / rev / "manifest.json").write_text(json.dumps({"revision": "0" * 64}))
    with pytest.raises(policy.PolicyArchiveError):
        policy.reconstruct(archive, rev, {}, OPA_BIN)
