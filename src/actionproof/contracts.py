"""Strict ActionRequest contract (deck slide 4, S4.4 / S7.2).

Invariant 1: unknown fields or any parse failure -> ContractError (caller DENYs).
Invariant 4: amounts and bbox coords are decimal strings; strict mode rejects every float.
request_hash = sha256(RFC 8785 canonical JSON of the full model, nulls included).
"""

import hashlib
import re
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal

import rfc8785
from pydantic import BaseModel, ConfigDict, Field, model_validator

MONEY = re.compile(r"^-?\d+\.\d{2}$")
INTEGER = re.compile(r"^-?\d+$")
COORD = re.compile(r"^-?\d+(\.\d+)?$")
POINTER = re.compile(r"^(/([^~/]|~[01])*)*$")  # RFC 6901
DERIVED_FNS = {"sub", "add", "sum"}

_STRICT = ConfigDict(strict=True, extra="forbid")


class ContractError(Exception):
    """Any contract violation. Never carries partial data."""


class ClaimType(str, Enum):
    DIRECT = "DIRECT"
    DERIVED = "DERIVED"
    ASSERTED = "ASSERTED"


class Src(BaseModel):
    model_config = _STRICT

    doc: str
    page: Annotated[int, Field(ge=1)] | None = None
    bbox: Annotated[list[str], Field(min_length=4, max_length=4)] | None = None  # [x0, top, x1, bottom]
    pointer: str | None = None

    @model_validator(mode="after")
    def _locator(self):
        located = self.page is not None and self.bbox is not None
        partial = (self.page is None) != (self.bbox is None)
        if partial or located == (self.pointer is not None):
            raise ValueError("src needs exactly one of (page and bbox) or pointer")
        if self.bbox is not None:
            if not all(COORD.match(c) for c in self.bbox):
                raise ValueError("bbox coords must be decimal strings")
            x0, top, x1, bottom = map(Decimal, self.bbox)
            if not (x0 < x1 and top < bottom):
                raise ValueError("bbox needs x0 < x1 and top < bottom")
        if self.pointer is not None and not POINTER.match(self.pointer):
            raise ValueError("pointer must be an RFC 6901 JSON pointer")
        return self


def _money_looking(v: str) -> bool:
    """Parses as a Decimal (incl. NaN/exponent/whitespace) but is not a bare integer id."""
    try:
        Decimal(v)
    except InvalidOperation:
        return False
    return not INTEGER.match(v)


class Claim(BaseModel):
    model_config = _STRICT

    value: str
    claim: Annotated[ClaimType, Field(strict=False)]  # lax only to accept "DIRECT" from dicts; still enum-checked
    src: Src | None = None
    doc_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    fn: Literal["sub", "add", "sum"] | None = None
    inputs: list[str] | None = None
    taint: Literal["doc"] | None = None

    @model_validator(mode="after")
    def _rules(self):
        t = self.claim
        if t is ClaimType.DIRECT:
            if self.src is None or self.doc_sha256 is None:
                raise ValueError("DIRECT requires src and doc_sha256")
            if self.fn is not None or self.inputs is not None:
                raise ValueError("DIRECT forbids fn/inputs")
            if _money_looking(self.value) and not MONEY.match(self.value):
                raise ValueError("money value must match -?digits.2dp")
        elif t is ClaimType.DERIVED:
            if self.fn not in DERIVED_FNS or not self.inputs:
                raise ValueError("DERIVED requires allowlisted fn and non-empty inputs")
            if self.src is not None or self.doc_sha256 is not None:
                raise ValueError("DERIVED forbids src/doc_sha256")
            if not MONEY.match(self.value):
                raise ValueError("DERIVED value must match -?digits.2dp")
        elif self.src is not None or self.fn is not None or self.inputs is not None:
            raise ValueError("ASSERTED forbids src/fn/inputs")
        return self


class ActionRequest(BaseModel):
    model_config = _STRICT

    tool: str
    on_behalf_of: str
    actor: str
    idempotency_key: str
    args: dict[str, Claim]


def canonical_bytes(req: ActionRequest) -> bytes:
    return rfc8785.dumps(req.model_dump(mode="json", exclude_none=False))


def request_hash(req: ActionRequest) -> str:
    return hashlib.sha256(canonical_bytes(req)).hexdigest()


def parse_request(raw: bytes | str | dict) -> ActionRequest:
    try:
        if isinstance(raw, (bytes, str)):
            return ActionRequest.model_validate_json(raw)
        if isinstance(raw, dict):
            return ActionRequest.model_validate(raw)
    except Exception as e:  # fail closed (invariant 1)
        raise ContractError(str(e)) from None
    raise ContractError(f"unsupported request type {type(raw).__name__}")
