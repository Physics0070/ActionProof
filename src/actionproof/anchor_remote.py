"""Remote append-only checkpoint anchor over HTTP (ADR-030). Same shape as anchor.LocalAnchor (CheckpointAnchor).

Protocol of the generic append-only service (the adapter speaks only this):
    GET  {url}/checkpoints        200 {"checkpoints": [<signed checkpoint>, ...]}  ascending seq
    PUT  {url}/checkpoints/{seq}  body = {"payload": {seq, head_hash, ts}, "sig", "kid"}
         201 appended | 200 the identical checkpoint is already held (idempotent)
         409 a different checkpoint is held at seq, or seq is not after the remote head (append-only)
    Authorization: Bearer <ANCHOR_REMOTE_TOKEN>; redirects are not followed; proxy env vars are ignored.

The remote is never trusted: every listed checkpoint is re-verified through the KeyRegistry and the listing must be
strictly increasing. It only ever receives signed public checkpoints, never a key. Errors name the exception type and
HTTP status only (no URL, no token).
UNVERIFIED: tested only against the in-process stub in tests/usp/test_anchor_remote.py. Nothing here makes a remote
WORM; that holds only if the provider enforces immutable retention and the operator has verified it.
"""
import httpx

from actionproof.anchor import AnchorError, _check_signed


class RemoteUnavailable(AnchorError):
    """Network error, timeout or 5xx: nothing was decided, retry later (the backlog stays in order)."""


class HttpAnchor:
    def __init__(self, url: str, token: str, timeout: float, event_hooks=None):
        self._url = url.rstrip("/")
        self._client = httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False,
                                    headers={"Authorization": f"Bearer {token}"}, event_hooks=event_hooks or {})

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            r = self._client.request(method, self._url + path, **kw)
        except httpx.HTTPError as e:
            raise RemoteUnavailable(f"remote unreachable ({type(e).__name__})") from None
        if r.status_code >= 500:
            raise RemoteUnavailable(f"remote unavailable (HTTP {r.status_code})")
        return r

    def entries(self, keys) -> list[dict]:
        r = self._request("GET", "/checkpoints")
        if r.status_code != 200:
            raise AnchorError(f"remote refused the listing (HTTP {r.status_code})")
        try:
            listed = r.json()["checkpoints"]
            if not isinstance(listed, list):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            raise AnchorError("remote listing is malformed") from None
        out, last = [], 0
        for env in listed:
            cp = _check_signed(env, keys)
            if cp["payload"]["seq"] <= last:
                raise AnchorError("remote sequence is not strictly increasing")
            last = cp["payload"]["seq"]
            out.append({"checkpoint": cp})
        return out

    def latest(self, keys) -> dict | None:
        es = self.entries(keys)
        return es[-1]["checkpoint"] if es else None

    def publish(self, env, keys) -> bool:
        """True if appended, False if the identical checkpoint was already held. Verified BEFORE any request."""
        cp = _check_signed(env, keys)
        seq = cp["payload"]["seq"]
        r = self._request("PUT", f"/checkpoints/{seq}", json=cp)
        if r.status_code == 201:
            return True
        if r.status_code == 200:
            return False
        if r.status_code == 409:
            raise AnchorError(f"remote refused seq {seq}: a different checkpoint is held there or it is not after "
                              "the remote head")
        raise AnchorError(f"remote refused seq {seq} (HTTP {r.status_code})")
