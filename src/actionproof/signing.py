"""Ed25519 receipt signing (PyNaCl) over RFC 8785 canonical bytes.

Invariant 6 / ADR-007: this module is the ONLY place the private key is read or held.
The key is never returned, logged, put in an exception message, repr'd, or pickled.
"""
import base64
import os
from pathlib import Path

import rfc8785
from nacl.signing import SigningKey, VerifyKey

_SEED_LEN = 32


def _reject_floats(v) -> None:
    # Invariant 4: no floats in anything we sign.
    if isinstance(v, float):
        raise TypeError("floats are not allowed in signed payloads")
    if isinstance(v, dict):
        for x in v.values():
            _reject_floats(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _reject_floats(x)


def generate_key(path: str | os.PathLike) -> None:
    """Write a fresh 32-byte seed to `path`. Refuses to overwrite an existing file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(SigningKey.generate().encode())
    # ponytail: on Windows chmod only toggles read-only; real ACLs are an ops concern (README).
    os.chmod(p, 0o600)


class Signer:
    __slots__ = ("_sk", "kid")  # no __dict__, so vars() raises instead of dumping the key

    def __init__(self, _sk: SigningKey, kid: str):
        self._sk = _sk
        self.kid = kid

    @classmethod
    def from_path(cls, path: str | os.PathLike, kid: str) -> "Signer":
        try:
            raw = Path(path).read_bytes()
        except OSError:
            raise ValueError("signing key file unreadable") from None
        if len(raw) != _SEED_LEN:
            raise ValueError("signing key file has the wrong length")
        return cls(SigningKey(raw), kid)

    def sign(self, payload: dict) -> dict:
        _reject_floats(payload)
        sig = self._sk.sign(rfc8785.dumps(payload)).signature
        return {"payload": payload, "sig": base64.b64encode(sig).decode("ascii"), "kid": self.kid}

    def public_key_b64(self) -> str:
        return base64.b64encode(bytes(self._sk.verify_key)).decode("ascii")

    def __repr__(self) -> str:
        return f"Signer(kid={self.kid!r})"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("Signer cannot be pickled")

    def __reduce_ex__(self, protocol):
        raise TypeError("Signer cannot be pickled")

    def __copy__(self):
        raise TypeError("Signer cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("Signer cannot be copied")


def verify(receipt: dict, verify_key_b64: str) -> bool:
    """True only for a well-formed receipt whose signature checks. Never raises."""
    try:
        if not isinstance(receipt, dict) or set(receipt) != {"payload", "sig", "kid"}:
            return False
        payload, sig = receipt["payload"], receipt["sig"]
        if not isinstance(payload, dict) or not isinstance(sig, str) or not isinstance(receipt["kid"], str):
            return False
        _reject_floats(payload)
        vk = VerifyKey(base64.b64decode(verify_key_b64, validate=True))
        vk.verify(rfc8785.dumps(payload), base64.b64decode(sig, validate=True))
        return True
    except Exception:  # BadSignatureError, bad base64, bad key length, non-JSON payload, ...
        return False
