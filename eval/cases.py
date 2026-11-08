"""Eval case format (spec/cases-format.md): strict models, loader, and catalog helpers.

Pure data: nothing here imports the gate. `python -m eval.cases validate` prints counts, exits 1 on any invalid case.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "out"
CASES = Path(__file__).resolve().parent / "cases"
CLASSES = ("prompt_injection", "argument_tampering", "evidence_forgery", "confused_deputy", "split_payments",
           "replay", "race")
MONEY = re.compile(r"^-?\d+\.\d{2}$")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _money(v: str | None) -> str | None:
    if v is not None and not MONEY.match(v):
        raise ValueError(f"not a 2dp decimal string: {v!r}")
    return v


# ---------------------------------------------------------------- setup
class Record(_M):
    kind: Literal["invoice", "po", "payment"]
    id: str
    vendor_id: str | None = None
    customer_id: str | None = None
    total: str | None = None
    amount: str | None = None
    method_id: str | None = None
    po_id: str | None = None
    status: str | None = None
    refunded: str | None = None
    version: int = 1

    @model_validator(mode="after")
    def _shape(self):
        need = {"invoice": ("vendor_id", "total", "po_id"), "po": ("vendor_id", "total"),
                "payment": ("customer_id", "amount", "method_id")}[self.kind]
        for f in need:
            if getattr(self, f) is None:
                raise ValueError(f"{self.kind} record needs {f}")
        for f in ("total", "amount", "refunded"):
            _money(getattr(self, f))
        return self

    @property
    def record_id(self) -> str:
        return f"{self.kind}:{self.id}"

    def data(self) -> dict:
        d = {k: v for k, v in self.model_dump().items() if v is not None and k not in ("kind", "id", "version")}
        if self.kind != "po":
            d.setdefault("status", "captured" if self.kind == "payment" else "open")
        return d


class Delegation(_M):
    on_behalf_of: str
    max_amount: str
    vendors: list[str] = []
    customers: list[str] = []

    @model_validator(mode="after")
    def _m(self):
        _money(self.max_amount)
        return self


class Person(_M):
    login: str
    person_id: str
    roles: list[str] = []


class PriorCommit(_M):
    actor: str
    counterparty: str
    amount: str
    on_behalf_of: str = "user-123"
    record_id: str | None = None

    @model_validator(mode="after")
    def _m(self):
        _money(self.amount)
        return self


class Edit(_M):
    op: Literal["replace_text", "add_text"]
    field: str | None = None      # replace_text: the catalog field whose box is overwritten
    text: str
    page: int = 1                 # add_text
    at: list[str] | None = None   # add_text: [x, y] baseline origin, pt, top-left
    size: str = "12"
    hidden: bool = False          # add_text: white 1 pt text

    @model_validator(mode="after")
    def _m(self):
        if self.op == "replace_text" and not self.field:
            raise ValueError("replace_text needs field")
        if self.op == "add_text" and not self.at:
            raise ValueError("add_text needs at")
        return self


class DocRef(_M):
    name: str
    derive_from: str | None = None
    edits: list[Edit] = []

    @model_validator(mode="after")
    def _m(self):
        if bool(self.derive_from) != bool(self.edits):
            raise ValueError("derive_from and edits go together")
        return self


class Setup(_M):
    records: list[Record] = []
    delegations: list[Delegation] | None = None
    people: list[Person] = []
    prior_commits: list[PriorCommit] = []
    documents: list[DocRef] = []


class Principal(_M):
    actor: str = "agent-7"
    on_behalf_of: str = "user-123"


# ---------------------------------------------------------------- request
class Cite(_M):
    doc: str
    field: str


class Arg(_M):
    claim: Literal["DIRECT", "DERIVED", "ASSERTED"]
    value: str | None = None
    cite: Cite | None = None
    src: dict | None = None
    doc_sha256: str | None = None
    doc_sha256_of: str | None = None
    fn: str | None = None
    inputs: list[str] | None = None
    taint: str | None = None

    @model_validator(mode="after")
    def _m(self):
        if self.claim == "DIRECT" and not (self.cite or (self.src and self.doc_sha256 and self.value is not None)):
            raise ValueError("DIRECT needs cite, or src + doc_sha256 + value")
        if self.claim != "DIRECT" and (self.cite or self.src or self.doc_sha256 or self.doc_sha256_of):
            raise ValueError("only DIRECT claims carry evidence")
        if self.claim == "DERIVED" and not (self.fn and self.inputs and self.value is not None):
            raise ValueError("DERIVED needs fn, inputs, value")
        if self.claim == "ASSERTED" and self.value is None:
            raise ValueError("ASSERTED needs value")
        return self


class Request(_M):
    tool: str
    actor: str | None = None
    on_behalf_of: str | None = None
    idempotency_key: str
    args: dict[str, Arg]


# ---------------------------------------------------------------- steps
class _S(_M):
    id: str


class Prepare(_S):
    op: Literal["prepare"]
    request: Request
    principal: Principal | None = None


class Commit(_S):
    op: Literal["commit"]
    receipt_from: str
    request_from: str | None = None
    request_override: dict | None = None  # RFC 7386 merge patch over the resolved wire request
    review_token_from: str | None = None
    receipt_override: dict | None = None  # RFC 7386 merge patch over the receipt as issued
    principal: Principal | None = None


class MintToken(_S):
    op: Literal["mint_token"]
    receipt_from: str
    reviewer_login: str
    request_from: str | None = None


class MutateRecord(_S):
    op: Literal["mutate_record"]
    record_id: str
    set: dict[str, str] = {}
    version: int | None = None  # absent: version + 1


class SetDelegation(_S):
    op: Literal["set_delegation"]
    on_behalf_of: str
    max_amount: str | None = None
    vendors: list[str] | None = None
    customers: list[str] | None = None
    revoke: bool = False


class AdvanceClock(_S):
    op: Literal["advance_clock"]
    seconds: int = Field(gt=0)


class Replay(_S):
    op: Literal["replay"]
    step: str


Leaf = Annotated[Union[Prepare, Commit, MintToken], Field(discriminator="op")]


class Concurrent(_S):
    op: Literal["concurrent"]
    steps: list[Leaf] = Field(min_length=2)


Step = Annotated[Union[Prepare, Commit, MintToken, MutateRecord, SetDelegation, AdvanceClock, Concurrent, Replay],
                 Field(discriminator="op")]


class Expect(_M):
    max_tool_executions: int | None = None
    final: Literal["EXECUTED", "REVIEW_PENDING"] | None = None
    rules_any_of: list[str] = []


_REFS = (("receipt_from", ("prepare",)), ("request_from", ("prepare",)),
         ("review_token_from", ("mint_token",)), ("step", ("commit",)))


class Case(_M):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    kind: Literal["attack", "benign"]
    class_: str | None = Field(alias="class")
    description: str
    origin: Literal["handwritten", "generated", "corpus"]
    setup: Setup = Setup()
    principal: Principal = Principal()
    steps: list[Step] = Field(min_length=1)
    expect: Expect
    _set_name: str = PrivateAttr(default="")

    @property
    def set_name(self) -> str:
        """Parent directory of the case file ('handwritten', 'handwritten2', 'generated', 'benign', ...)."""
        return self._set_name

    @model_validator(mode="after")
    def _check(self):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", self.id):
            raise ValueError("id must be lowercase [a-z0-9_.-]")
        if self.kind == "attack":
            if self.class_ not in CLASSES:
                raise ValueError(f"attack class must be one of {CLASSES}")
            if self.expect.final is not None:
                raise ValueError("attack expect has no final")
            if self.expect.max_tool_executions is None:
                self.expect.max_tool_executions = 0
        elif self.class_ is not None or self.expect.final is None or self.expect.max_tool_executions is not None:
            raise ValueError("benign: class null, final required, no max_tool_executions")
        docs = {d.name: d for d in self.setup.documents}
        known: dict[str, str] = {}  # step id -> op, for steps already run
        flat: list = []

        def check_refs(s):
            for ref, ops in _REFS:
                v = getattr(s, ref, None)
                if v is not None and known.get(v) not in ops:
                    raise ValueError(f"step {s.id}: {ref}={v} must name an earlier {ops[0]} step")

        for s in self.steps:
            if s.id in known:
                raise ValueError(f"duplicate step id {s.id}")
            check_refs(s)
            if s.op == "concurrent":
                for sub in s.steps:  # members run together: they may only reference steps before the group
                    if sub.id in known or sub.id == s.id:
                        raise ValueError(f"duplicate step id {sub.id}")
                    check_refs(sub)
                    flat.append(sub)
                for sub in s.steps:
                    known[sub.id] = sub.op
            flat.append(s)
            known[s.id] = s.op
        for s in flat:
            if s.op == "prepare":
                for a in s.request.args.values():
                    if a.cite and a.cite.doc not in docs:
                        raise ValueError(f"step {s.id}: cites {a.cite.doc}, not in setup.documents")
                    if a.doc_sha256_of and a.doc_sha256_of not in docs:
                        raise ValueError(f"step {s.id}: doc_sha256_of {a.doc_sha256_of} not in setup.documents")
        for d in docs.values():
            if d.derive_from and d.derive_from not in docs:
                raise ValueError(f"{d.name}: derive_from {d.derive_from} not in setup.documents")
        return self


# ---------------------------------------------------------------- loading and catalog helpers
def load_cases(directory: Path | str = CASES) -> list[Case]:
    out = []
    for path in sorted(Path(directory).rglob("*.json")):
        try:
            case = Case.model_validate(json.loads(path.read_text(encoding="utf-8")))
            case._set_name = path.parent.name
            out.append(case)
        except (ValidationError, ValueError) as e:
            raise ValueError(f"{path}: {e}") from e
    return out


def load_manifest() -> dict:
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))["docs"]


def build_derived(base: bytes, base_fields: dict, edits: list[Edit]) -> bytes:
    """Apply edits to a copy of a catalog PDF (PyMuPDF). replace_text redacts the field's box and writes the new
    text on the same baseline; add_text writes text at a point (white 1 pt when hidden)."""
    import pymupdf

    doc = pymupdf.open(stream=base, filetype="pdf")
    for e in edits:
        if e.op == "replace_text":
            f = base_fields[e.field]
            page = doc[f["page"] - 1]
            x0, top, x1, bottom = (float(v) for v in f["bbox"])
            page.add_redact_annot(pymupdf.Rect(x0, top, x1, bottom))
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
            page.insert_text((x0 + 0.01, bottom - 4.2), e.text, fontname="helv", fontsize=14.0)
        else:
            page = doc[e.page - 1]
            kw = {"color": (1, 1, 1)} if e.hidden else {}
            page.insert_text((float(e.at[0]), float(e.at[1])), e.text, fontname="helv",
                             fontsize=1.0 if e.hidden else float(e.size), **kw)
    data = doc.tobytes(deflate=True)
    doc.close()
    return data


def materialize_docs(setup: Setup, manifest: dict | None = None) -> tuple[dict[str, bytes], dict[str, dict]]:
    """name -> bytes, and name -> manifest-style entry (fields/sha256/kind) for every document of the case."""
    manifest = manifest or load_manifest()
    blobs: dict[str, bytes] = {}
    entries: dict[str, dict] = {}
    for d in setup.documents:
        if d.derive_from is None:
            blobs[d.name] = (FIXTURES / manifest[d.name]["path"]).read_bytes()
            entries[d.name] = manifest[d.name]
    for d in setup.documents:
        if d.derive_from is not None:
            base = manifest[d.derive_from]
            data = build_derived(blobs[d.derive_from], base["fields"], d.edits)
            fields = copy.deepcopy(base["fields"])
            for e in d.edits:
                if e.op == "replace_text":
                    fields[e.field]["value"] = e.text.replace("$", "").replace(",", "")
            blobs[d.name] = data
            entries[d.name] = {**base, "fields": fields, "sha256": hashlib.sha256(data).hexdigest()}
    return blobs, entries


def resolve_request(req: Request, principal: Principal, entries: dict[str, dict]) -> dict:
    """The wire ActionRequest (spec/actionrequest.md) for a case request: cites become src + doc_sha256."""
    args = {}
    for name, a in req.args.items():
        d = {"claim": a.claim}
        if a.claim == "DIRECT":
            if a.cite:
                e = entries[a.cite.doc]
                f = e["fields"][a.cite.field]
                src = {"doc": a.cite.doc, **({"pointer": f["pointer"]} if "pointer" in f
                                              else {"page": f["page"], "bbox": f["bbox"]})}
                d["value"], d["src"], d["doc_sha256"] = f["value"], src, e["sha256"]
            if a.value is not None:
                d["value"] = a.value
            if a.src is not None:
                d["src"] = a.src
            if a.doc_sha256 is not None:
                d["doc_sha256"] = a.doc_sha256
            if a.doc_sha256_of is not None:
                d["doc_sha256"] = entries[a.doc_sha256_of]["sha256"]
        else:
            d["value"] = a.value
            if a.claim == "DERIVED":
                d["fn"], d["inputs"] = a.fn, a.inputs
            elif a.taint:
                d["taint"] = a.taint
        args[name] = d
    return {"tool": req.tool, "actor": req.actor or principal.actor,
            "on_behalf_of": req.on_behalf_of or principal.on_behalf_of,
            "idempotency_key": req.idempotency_key, "args": args}


def merge_patch(doc, patch):
    """RFC 7386 JSON merge patch."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out = dict(doc) if isinstance(doc, dict) else {}
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = merge_patch(out.get(k), v)
    return out


def summarize(cases: list[Case]) -> dict:
    return {"total": len(cases), "kind": dict(Counter(c.kind for c in cases)),
            "origin": dict(Counter(c.origin for c in cases)),
            "class": dict(Counter(c.class_ for c in cases if c.class_)),
            "handwritten_class": dict(Counter(c.class_ for c in cases if c.class_ and c.origin == "handwritten"))}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] != ["validate"]:
        print("usage: python -m eval.cases validate [dir]", file=sys.stderr)
        return 2
    try:
        cases = load_cases(argv[1] if len(argv) > 1 else CASES)
    except (ValueError, OSError) as e:
        print(f"INVALID: {e}", file=sys.stderr)
        return 1
    dup = [i for i, n in Counter(c.id for c in cases).items() if n > 1]
    if dup:
        print(f"INVALID: duplicate ids {dup}", file=sys.stderr)
        return 1
    print(json.dumps(summarize(cases), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
