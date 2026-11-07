"""USP G1+G2: the signing key is unreachable from anything the agent can call (invariant 6, ADR-007).

No public Gate method returns, logs or raises key material: scan repr, receipts, reasons, cards and error text
for the seed bytes in raw, hex and base64 form.
"""
import base64
import copy
import json
import logging
import pickle

import pytest


def _forms(seed: bytes) -> list[str]:
    return [seed.hex(), seed.hex().upper(), base64.b64encode(seed).decode(), base64.urlsafe_b64encode(seed).decode(),
            seed.decode("latin-1")]


def _clean(text: str, seed: bytes) -> None:
    for f in _forms(seed):
        assert f not in text


def test_no_key_material_anywhere(kit, signing_key_path, caplog):
    """USP G1+G2: repr, receipts, reasons, cards and commit results carry no key material."""
    seed = signing_key_path.read_bytes()
    caplog.set_level(logging.DEBUG)
    req, docs = kit.json_request("INV-5501", "100.00")
    prep = kit.gate.prepare(req, docs)
    denied = kit.gate.prepare({"tool": "nope"}, {})
    com = kit.gate.commit(prep.receipt, req)
    replay = kit.gate.commit(prep.receipt, req)
    garbage = kit.gate.commit({"payload": {}, "sig": "x", "kid": "k1"}, req)
    kit.gate._conn_factory = lambda: (_ for _ in ()).throw(RuntimeError(seed.hex()))  # hostile error text
    boom = kit.gate.commit(prep.receipt, req)
    blob = "\n".join([
        repr(kit.gate), str(kit.gate), json.dumps(prep.receipt), prep.card(), denied.card(), repr(prep), repr(denied),
        repr(com), repr(replay), repr(garbage), repr(boom), json.dumps(com.tool_result), caplog.text,
        repr(vars(kit.gate)),
    ])
    _clean(blob, seed)
    assert com.outcome == "EXECUTED" and boom.outcome == "DENY"
    assert seed.hex() not in boom.reasons[0].msg  # exception messages are never echoed


def test_public_surface_is_three_methods(kit):
    """USP G1+G2: the Gate exposes prepare/commit/mint_review_token only; nothing returns the signer."""
    public = {n for n in dir(kit.gate) if not n.startswith("_")}
    assert public == {"prepare", "commit", "mint_review_token"}


def test_gate_cannot_be_serialized_or_copied(kit):
    """USP G1+G2: pickling or deep-copying the gate would drag the key along, so it is refused."""
    with pytest.raises(TypeError):
        pickle.dumps(kit.gate)
    with pytest.raises(TypeError):
        copy.deepcopy(kit.gate)
