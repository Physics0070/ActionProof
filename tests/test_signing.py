"""Receipt signatures (G2) and signing-key isolation (invariant 6)."""
import copy
import pickle
import re
from pathlib import Path

import pytest

from actionproof.signing import Signer, generate_key, verify

SRC = Path(__file__).resolve().parents[1] / "src"
PAYLOAD = {"request_hash": "ab" * 32, "decision": "ALLOW", "reasons": [], "version": 1,
           "nonce": "n1", "exp": 1_900_000_000, "amount": "4800.00"}


@pytest.fixture
def signer(tmp_path):
    p = tmp_path / "k.key"
    generate_key(p)
    return Signer.from_path(p, "k1")


def test_round_trip(signer):
    r = signer.sign(PAYLOAD)
    assert r["kid"] == "k1" and r["payload"] == PAYLOAD
    assert verify(r, signer.public_key_b64())


def test_tampered_payload_fails(signer):
    r = signer.sign(PAYLOAD)
    bad = {**r, "payload": {**PAYLOAD, "amount": "4800.01"}}
    assert not verify(bad, signer.public_key_b64())


def test_wrong_key_fails(signer, tmp_path):
    generate_key(tmp_path / "other.key")
    other = Signer.from_path(tmp_path / "other.key", "k2")
    assert not verify(signer.sign(PAYLOAD), other.public_key_b64())


@pytest.mark.parametrize("garbage", [
    None, 1, "x", [], {}, {"payload": {}}, {"payload": "x", "sig": "y", "kid": "k1"},
    {"payload": {}, "sig": "!!notb64!!", "kid": "k1"}, {"payload": {}, "sig": "", "kid": "k1"},
    {"payload": {"a": 1.5}, "sig": "AAAA", "kid": "k1"}, {"payload": {}, "sig": 5, "kid": "k1"},
])
def test_garbage_never_raises(signer, garbage):
    assert verify(garbage, signer.public_key_b64()) is False


def test_garbage_key_never_raises(signer):
    r = signer.sign(PAYLOAD)
    for k in ("", "not-base64!", "AAAA", None, 7):
        assert verify(r, k) is False


def test_extra_receipt_field_fails(signer):
    assert not verify({**signer.sign(PAYLOAD), "extra": 1}, signer.public_key_b64())


def test_float_payload_refused(signer):
    with pytest.raises(TypeError):
        signer.sign({"amount": 4800.0})


def test_repr_str_pickle_vars_safe(tmp_path):
    p = tmp_path / "k.key"
    generate_key(p)
    seed = p.read_bytes()
    s = Signer.from_path(p, "k1")
    for text in (repr(s), str(s), f"{s}"):
        assert "k1" in text and seed.hex() not in text and "SigningKey" not in text
    for attempt in (lambda: pickle.dumps(s), lambda: copy.copy(s), lambda: copy.deepcopy(s), lambda: vars(s)):
        with pytest.raises(TypeError):
            attempt()


def test_key_file_not_overwritten(tmp_path):
    p = tmp_path / "k.key"
    generate_key(p)
    before = p.read_bytes()
    assert len(before) == 32
    with pytest.raises(FileExistsError):
        generate_key(p)
    assert p.read_bytes() == before


@pytest.mark.parametrize("content", [b"", b"short", b"x" * 64])
def test_bad_key_file_rejected_without_echo(tmp_path, content):
    p = tmp_path / "bad.key"
    p.write_bytes(content)
    with pytest.raises(ValueError) as e:
        Signer.from_path(p, "k1")
    assert "short" not in str(e.value) and "xxxx" not in str(e.value)


def test_missing_key_file_rejected(tmp_path):
    with pytest.raises(ValueError):
        Signer.from_path(tmp_path / "nope.key", "k1")


def test_key_material_not_exposed_outside_signing():
    """Invariant 6: only signing.py may touch key internals (seed / SigningKey / private attr)."""
    pat = re.compile(r"\bseed\b|signing_key(?!_path)|SigningKey|nacl\.signing|\._sk\b", re.IGNORECASE)
    offenders = [f"{f.relative_to(SRC)}:{i}" for f in SRC.rglob("*.py") if f.name != "signing.py"
                 for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1) if pat.search(line)]
    assert offenders == []
