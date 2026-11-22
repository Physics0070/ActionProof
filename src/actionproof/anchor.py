"""Local append-only checkpoint anchor: a second copy of the signed audit checkpoints OUTSIDE the database.

The in-database checkpoints cannot reveal an attacker who deletes the newest audit entries together with their
checkpoints. An anchor holding the latest checkpoint elsewhere can: the database head must reach it and match it.

Concurrency: publish and entries take an exclusive file lock (`<file>.lock`), so separate processes serialize.
File format: JSON lines, each {"checkpoint": {payload:{seq,head_hash,ts}, sig, kid}, "prev": sha256(previous raw line)}.
The `prev` links make a deleted, reordered or edited line detectable; every checkpoint is re-verified against the
trusted public key(s). Publishing is idempotent (same seq + head = no-op) and monotonic (older or conflicting = error).

LIMIT (read this): a file on the same machine is NOT immutable storage. Whoever controls the host can rewrite the
database AND this file, or drop the file's last lines (a shortened chain still verifies). To be an independent
trust domain the file must be copied to append-only / WORM storage or another machine after each publish.
The remote adapter with the same shape is `anchor_remote.HttpAnchor`, published by `anchor_publisher` (ADR-030).
"""
import contextlib
import hashlib
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from actionproof import signing

if os.name == "nt":
    import msvcrt
else:
    import fcntl

GENESIS = "0" * 64


class AnchorError(Exception):
    pass


def _h(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class CheckpointAnchor(Protocol):
    """The shape every anchor has (LocalAnchor, anchor_remote.HttpAnchor). `keys`: one base64 public key, a kid -> key
    map, or a signing.KeyRegistry (revoked and unknown kids fail). Every returned checkpoint has been re-verified."""

    def entries(self, keys) -> list[dict]: ...

    def latest(self, keys) -> dict | None: ...

    def publish(self, env, keys) -> bool: ...


def _check_signed(env, keys: "str | Mapping[str, str] | signing.KeyRegistry") -> dict:
    if not isinstance(env, dict) or not isinstance(env.get("payload"), dict):
        raise AnchorError("checkpoint is malformed")
    p = env["payload"]
    if set(p) != {"seq", "head_hash", "ts"} or type(p["seq"]) is not int or p["seq"] < 1 \
            or not isinstance(p["head_hash"], str) or type(p["ts"]) is not int:
        raise AnchorError("checkpoint payload is malformed")
    if isinstance(keys, signing.KeyRegistry):
        ok = keys.verify(env)
    else:
        key = keys if isinstance(keys, str) else keys.get(env.get("kid"))
        ok = key is not None and signing.verify(env, key)
    if not ok:
        raise AnchorError("checkpoint signature invalid or kid unknown")
    return env


@contextlib.contextmanager
def _locked(path: Path, timeout: float = 10.0):
    """Exclusive cross-process lock (a `<file>.lock` sidecar; msvcrt on Windows, flock elsewhere). Serializes the
    read-validate-append of publish and the reads of entries, so two publishers can never fork the chain."""
    fd = os.open(path.with_name(path.name + ".lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise AnchorError("anchor is locked by another process (timeout)") from None
                time.sleep(0.005)
        try:
            yield
        finally:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class LocalAnchor:
    def __init__(self, path):
        self.path = Path(path)

    def entries(self, keys) -> list[dict]:
        """Every anchored checkpoint, oldest first, after verifying links, signatures and monotonic seq.
        Read under the publish lock, so a half-written tail line is never seen."""
        if not self.path.exists():
            return []
        try:
            with _locked(self.path):
                return self._read(keys)
        except PermissionError:  # a read-only anchor directory (verify-only user): read without the lock
            return self._read(keys)

    def _read(self, keys) -> list[dict]:
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
        """Append `env`. True if appended, False if it was already anchored. Raises AnchorError on conflict.
        The whole read-validate-append runs under the cross-process lock."""
        cp = _check_signed(env, keys)
        with _locked(self.path):
            es = self._read(keys)
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
