"""Ed25519 receipt signing (PyNaCl) over RFC 8785 canonical bytes.

Invariant 6 / ADR-007: this module is the ONLY place the private key is read or held.
The key is never returned, logged, put in an exception message, repr'd, or pickled.
"""
import base64
import hashlib
import json
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


_STATUSES = ("active", "retired", "revoked")


class KeyRegistry:
    """kid -> trusted PUBLIC key + status. A receipt is verified with the key of ITS kid, never another's.

    active: the one key that signs now. retired: stopped signing, history still verifies (rotation). revoked:
    distrusted (compromise): its receipts and checkpoints no longer verify. Unknown kid: fails. No private key
    here (invariant 6). A malformed registry raises ValueError at load (fail closed)."""

    def __init__(self, keys):
        self._keys: dict[str, tuple[str, str]] = {}
        seen: set[str] = set()
        for kid, (pub, status) in dict(keys).items():
            if not isinstance(kid, str) or not kid or status not in _STATUSES:
                raise ValueError("key registry entry is malformed")
            try:
                raw = bytes(VerifyKey(base64.b64decode(pub, validate=True)))
            except Exception:
                raise ValueError("key registry holds an invalid public key") from None
            fp = hashlib.sha256(raw).hexdigest()
            if fp in seen:  # one key under two kids would let an old or revoked kid borrow another's status
                raise ValueError("key registry lists the same public key under two kids")
            seen.add(fp)
            self._keys[kid] = (pub, status)
        if sum(st == "active" for _, st in self._keys.values()) > 1:
            raise ValueError("key registry has more than one active key")

    @classmethod
    def for_signer(cls, signer: "Signer") -> "KeyRegistry":
        return cls({signer.kid: (signer.public_key_b64(), "active")})

    @classmethod
    def from_json(cls, path) -> "KeyRegistry":
        """{"keys": {"<kid>": {"pub": "<base64>", "status": "active|retired|revoked"}}}"""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls({kid: (e["pub"], e["status"]) for kid, e in raw["keys"].items()})
        except ValueError:
            raise
        except Exception:
            raise ValueError("key registry file is unreadable or malformed") from None

    def status(self, kid: str) -> str | None:
        e = self._keys.get(kid)
        return e[1] if e else None

    def signature_valid(self, receipt) -> bool:
        """CRYPTOGRAPHY ONLY: the key registered for the receipt's kid (any status) signed this payload. Says nothing
        about whether that key may still authorize anything: use it for history and forensics, never to authorize."""
        try:
            e = self._keys.get(receipt["kid"])
        except Exception:
            return False
        return e is not None and verify(receipt, e[0])

    def verify(self, receipt) -> bool:
        """AUTHORIZATION: signature_valid AND the kid is currently trusted (active or retired; revoked and unknown
        fail closed). A kid is never resolved to another kid's key."""
        try:
            return self.status(receipt["kid"]) in ("active", "retired") and self.signature_valid(receipt)
        except Exception:
            return False

    def public_keys(self, include_revoked: bool = False) -> dict[str, str]:
        """kid -> public key, the mapping audit.verify takes. Revoked keys are left out unless asked for."""
        return {k: pub for k, (pub, st) in self._keys.items() if include_revoked or st != "revoked"}
