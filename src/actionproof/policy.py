"""OPA client: decide(payload, opa_url, timeout) -> Decision. Rules live in policy/actionproof.rego (docs/POLICY.md).

The caller passes the OPA URL and timeout from Settings (invariant 7); this module reads no environment.
decide never raises. Any failure (empty OPA URL, connect error, timeout, non-200, missing or malformed
result, float in the payload) is DENY AP-POL-FAIL / G1 (invariant 1, invariant 4).
"""

import json
import time
from dataclasses import dataclass

import httpx

from actionproof.verify import Reason

OUTCOMES = ("DENY", "REVIEW", "ALLOW")
# One client for the process: building one per call (SSL context, env proxy lookup) costs ~200 ms on Windows.
# The timeout is passed per request, so the shared client carries none of its own.
# trust_env=False: OPA is a local sidecar; never route the policy call through an env-configured proxy.
_client = httpx.Client(trust_env=False)


@dataclass(frozen=True)
class Decision:
    outcome: str
    reasons: list[Reason]


def _fail(msg: str) -> Decision:
    return Decision("DENY", [Reason("AP-POL-FAIL", "G1", msg)])


def _has_float(o) -> bool:
    if isinstance(o, float):
        return True
    if isinstance(o, dict):
        return any(_has_float(k) or _has_float(v) for k, v in o.items())
    if isinstance(o, (list, tuple)):
        return any(_has_float(v) for v in o)
    return False


def _reason(r) -> Reason:
    if not isinstance(r, dict) or r.get("guarantee") not in ("G1", "G2"):
        raise ValueError
    if not all(isinstance(r.get(k), str) and r[k] for k in ("rule", "msg")):
        raise ValueError
    return Reason(r["rule"], r["guarantee"], r["msg"])


def decide(payload: dict, opa_url: str, timeout: float) -> Decision:
    try:
        if not isinstance(payload, dict) or _has_float(payload):
            return _fail("policy input must be a dict with no floats")
        if not opa_url:
            return _fail("OPA URL not configured")
        deadline = time.monotonic() + timeout
        body = b""
        # ponytail: per-chunk deadline check bounds a trickling server to ~2x timeout; a hard wall clock
        # needs a worker thread/async cancel.
        with _client.stream("POST", f"{opa_url.rstrip('/')}/v1/data/actionproof/decision",
                            json={"input": payload}, timeout=timeout) as r:
            if r.status_code != 200:
                return _fail(f"OPA returned HTTP {r.status_code}")
            for chunk in r.iter_bytes():
                body += chunk
                if time.monotonic() > deadline:
                    return _fail("OPA timed out")
        if time.monotonic() > deadline:
            return _fail("OPA timed out")
        result = json.loads(body)["result"]
        outcome, raw = result["outcome"], result["reasons"]
        if outcome not in OUTCOMES or not isinstance(raw, list):
            return _fail("OPA returned a malformed decision")
        reasons = [_reason(x) for x in raw]
        if outcome != "ALLOW" and not reasons:
            return _fail("OPA returned DENY/REVIEW without reasons")
        return Decision(outcome, reasons)
    except httpx.TimeoutException:
        return _fail("OPA timed out")
    except Exception:
        return _fail("policy evaluation failed")
