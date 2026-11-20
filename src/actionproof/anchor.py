"""Local append-only checkpoint anchor: a second copy of the signed audit checkpoints OUTSIDE the database.

The in-database checkpoints cannot reveal an attacker who deletes the newest audit entries together with their
checkpoints. An anchor holding the latest checkpoint elsewhere can: the database head must reach it and match it.

File format: JSON lines, each {"checkpoint": {payload:{seq,head_hash,ts}, sig, kid}, "prev": sha256(previous raw line)}.
The `prev` links make a deleted, reordered or edited line detectable; every checkpoint is re-verified against the
trusted public key(s). Publishing is idempotent (same seq + head = no-op) and monotonic (older or conflicting = error).

LIMIT (read this): a file on the same machine is NOT immutable storage. Whoever controls the host can rewrite the
database AND this file, or drop the file's last lines (a shortened chain still verifies). To be an independent
trust domain the file must be copied to append-only / WORM storage or another machine after each publish.
# ponytail: local file only; a remote HTTP / transparency-log anchor is the upgrade path (same publish/verify shape).
"""
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

from actionproof import signing

GENESIS = "0" * 64


class AnchorError(Exception):
    pass


def _h(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _check_signed(env, keys: "str | Mapping[str, str]") -> dict:
    if not isinstance(env, dict) or not isinstance(env.get("payload"), dict):
        raise AnchorError("checkpoint is malformed")
    p = env["payload"]
    if set(p) != {"seq", "head_hash", "ts"} or not isinstance(p["seq"], int) or p["seq"] < 1 \
            or not isinstance(p["head_hash"], str):
        raise AnchorError("checkpoint payload is malformed")
    key = keys if isinstance(keys, str) else keys.get(env.get("kid"))
    if key is None or not signing.verify(env, key):
        raise AnchorError("checkpoint signature invalid or kid unknown")
    return env


class LocalAnchor:
    def __init__(self, path):
        self.path = Path(path)

    def entries(self, keys) -> list[dict]:
        """Every anchored checkpoint, oldest first, after verifying links, signatures and monotonic seq."""
        try:
            raw = self.path.read_bytes() if self.path.exists() else b""
        except OSError:
            raise AnchorError("anchor file is unreadable") from None
        out, prev, last = [], GENESIS, 0
        for line in raw.splitlines():
            try:
                e = json.loads(line)
                ok = isinstance(e, dict) and set(e) == {"checkpoint", "prev"} and e["prev"] == prev
            except ValueError:
                ok = False
            if not ok:
                raise AnchorError("anchor chain broken (a line was edited, deleted or reordered)")
            cp = _check_signed(e["checkpoint"], keys)
            if cp["payload"]["seq"] <= last:
                raise AnchorError("anchor sequence is not increasing")
            last, prev = cp["payload"]["seq"], _h(line)
            out.append({"checkpoint": cp, "prev": e["prev"], "hash": prev})
        return out

    def latest(self, keys) -> dict | None:
        es = self.entries(keys)
        return es[-1]["checkpoint"] if es else None

    def publish(self, env, keys) -> bool:
        """Append `env`. True if appended, False if it was already anchored. Raises AnchorError on conflict."""
        cp = _check_signed(env, keys)
        es = self.entries(keys)
        if es:
            last = es[-1]["checkpoint"]["payload"]
            if cp["payload"]["seq"] == last["seq"]:
                if cp["payload"]["head_hash"] != last["head_hash"]:
                    raise AnchorError("conflicting checkpoint for an already anchored seq")
                return False
            if cp["payload"]["seq"] < last["seq"]:
                raise AnchorError("older checkpoint than the latest anchor")
        line = json.dumps({"checkpoint": cp, "prev": es[-1]["hash"] if es else GENESIS},
                          sort_keys=True, separators=(",", ":")).encode() + b"\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        return True
