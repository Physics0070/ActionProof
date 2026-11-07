"""G1 claim verification (deck S3.3, S4.1-S4.5). No LLM, no floats; arithmetic is Decimal only.

DIRECT: hash + deterministic re-extraction must reproduce the value.
DERIVED: recomputed by an allowlisted pure fn over verified args or system-of-record values.
ASSERTED: never fills a money field; fills another authority field only if the system of record agrees.
verify_request never raises: any failure is a not-ok result with Reason AP-VER-01 / G1 (invariant 1).
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from actionproof import extract
from actionproof.contracts import MONEY, ActionRequest, ClaimType


@dataclass(frozen=True)
class Reason:
    rule: str
    guarantee: str
    msg: str


@dataclass(frozen=True)
class ClaimResult:
    name: str
    claim: str
    ok: bool
    value: str | None
    method: str | None
    reason: Reason | None


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    claims: dict[str, ClaimResult]
    reasons: list[Reason]


REGISTRY: dict[str, dict] = {
    "payments.approve_invoice": {
        "required": {"amount", "variance"},
        "authority": {"amount", "variance", "vendor_id", "invoice_id"},
        "money": {"amount", "variance"},
    }
}

CENT = Decimal("0.01")


def _reason(msg: str) -> Reason:
    return Reason("AP-VER-01", "G1", msg)


class _Fail(Exception):
    pass


def _collapse(s: str) -> str:
    return " ".join(s.split())


def _direct(name, c, docs, money: set) -> tuple[str, str]:
    blob = docs.get(c.src.doc)
    if not isinstance(blob, bytes):
        raise _Fail(f"cited document {c.src.doc!r} not supplied as bytes")
    if hashlib.sha256(blob).hexdigest() != c.doc_sha256:
        raise _Fail("document hash mismatch")
    if name in money and not MONEY.match(c.value):
        raise _Fail("money field must be a 2dp decimal string")
    try:
        ex = extract.extract_src(blob, c.src)
    except extract.ExtractionError as e:
        raise _Fail(f"extraction failed: {e}") from None
    if MONEY.match(c.value):
        text = re.sub(r"[\s$,]", "", ex.value)
        same = bool(MONEY.match(text)) and Decimal(text) == Decimal(c.value)
    else:
        same = _collapse(ex.value) == _collapse(c.value)
    if not same:
        raise _Fail("cited span lacks the value")
    return c.value, ex.method


def verify_request(req: ActionRequest, docs: Mapping[str, bytes], sor: Mapping[str, str]) -> VerifyResult:
    try:
        return _verify(req, docs, sor)
    except Exception as e:  # fail closed (invariant 1)
        return VerifyResult(False, {}, [_reason(f"verification error: {type(e).__name__}")])


def _verify(req: ActionRequest, docs, sor) -> VerifyResult:
    if not isinstance(req, ActionRequest) or not isinstance(docs, Mapping) or not isinstance(sor, Mapping):
        return VerifyResult(False, {}, [_reason("request, docs and sor must be ActionRequest and mappings")])
    spec = REGISTRY.get(req.tool)
    if spec is None:
        return VerifyResult(False, {}, [_reason(f"unknown tool {req.tool!r}")])
    reasons = [_reason(f"{n}: required argument missing (evidence gap)") for n in sorted(spec["required"] - req.args.keys())]

    results: dict[str, ClaimResult] = {}
    visiting: set[str] = set()

    def money_input(i: str) -> Decimal:
        if i in req.args:
            r = check(i)
            if not r.ok:
                raise _Fail(f"input {i} did not verify")
            v = r.value
        elif i in sor:
            v = sor[i]
        else:
            raise _Fail(f"input {i} is neither a verified argument nor a system-of-record value")
        if not isinstance(v, str) or not MONEY.match(v):
            raise _Fail(f"input {i} is not a 2dp decimal string")
        return Decimal(v)

    def derived(c) -> tuple[str, str]:
        vals = [money_input(i) for i in c.inputs]
        if c.fn in ("sub", "add") and len(vals) != 2:
            raise _Fail(f"{c.fn} needs exactly 2 inputs")
        if c.fn == "sub":
            out = vals[0] - vals[1]
        elif c.fn in ("add", "sum"):
            out = sum(vals, Decimal(0))
        else:
            raise _Fail(f"fn {c.fn!r} is not allowlisted")
        out = out.quantize(CENT)
        if out != Decimal(c.value):
            raise _Fail(f"recomputed {out} does not match claimed {c.value}")
        return c.value, f"derived:{c.fn}"

    def asserted(name, c) -> tuple[str, str]:
        if name not in spec["authority"]:
            return c.value, "asserted"
        if name in spec["money"]:
            raise _Fail("ASSERTED cannot fill a money field")
        if sor.get(name) != c.value:
            raise _Fail("ASSERTED authority value not confirmed by system of record")
        return c.value, "asserted"

    def check(name: str) -> ClaimResult:
        if name in results:
            return results[name]
        if name in visiting:
            raise _Fail(f"dependency cycle at {name}")
        c = req.args[name]
        visiting.add(name)
        try:
            if c.claim is ClaimType.DIRECT:
                value, method = _direct(name, c, docs, spec["money"])
            elif c.claim is ClaimType.DERIVED:
                value, method = derived(c)
            else:
                value, method = asserted(name, c)
            res = ClaimResult(name, c.claim.value, True, value, method, None)
        except _Fail as f:
            res = ClaimResult(name, c.claim.value, False, None, None, _reason(f"{name}: {f}"))
        except Exception as e:  # fail closed per claim
            res = ClaimResult(name, c.claim.value, False, None, None, _reason(f"{name}: verification error {type(e).__name__}"))
        finally:
            visiting.discard(name)
        results[name] = res
        return res

    for name in req.args:
        check(name)
    claims = {n: results[n] for n in req.args}
    reasons += [r.reason for r in claims.values() if not r.ok]
    return VerifyResult(not reasons, claims, reasons)
