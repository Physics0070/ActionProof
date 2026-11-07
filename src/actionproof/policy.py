"""OPA client: decide(payload) -> Decision. Rules live in policy/actionproof.rego (docs/POLICY.md).

decide never raises. Any failure (OPA_URL unset, connect error, timeout > 200 ms, non-200, missing or
malformed result, float in the payload) is DENY AP-POL-FAIL / G1 (invariant 1, invariant 4).
"""

import json
import os
import time
from dataclasses import dataclass

import httpx

from actionproof.verify import Reason

TIMEOUT_S = 0.2
OUTCOMES = ("DENY", "REVIEW", "ALLOW")
# One client for the process: building one per call (SSL context, env proxy lookup) costs ~200 ms on Windows.
# trust_env=False: OPA is a local sidecar; never route the policy call through an env-configured proxy.
_client = httpx.Client(timeout=TIMEOUT_S, trust_env=False)


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


def decide(payload: dict) -> Decision:
    try:
        if not isinstance(payload, dict) or _has_float(payload):
            return _fail("policy input must be a dict with no floats")
        url = os.environ.get("OPA_URL")
        if not url:
            return _fail("OPA_URL not configured")
        deadline = time.monotonic() + TIMEOUT_S
        body = b""
        # ponytail: per-chunk deadline check bounds a trickling server to ~2x TIMEOUT_S; a hard wall clock
        # needs a worker thread/async cancel.
        with _client.stream("POST", f"{url.rstrip('/')}/v1/data/actionproof/decision", json={"input": payload}) as r:
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
