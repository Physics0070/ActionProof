"""OPA client: decide(payload, opa_url, timeout) -> Decision. Rules live in policy/actionproof.rego (docs/POLICY.md).

The caller passes the OPA URL and timeout from Settings (invariant 7); this module reads no environment.
decide never raises. Any failure (empty OPA URL, connect error, timeout, non-200, missing or malformed
result, float in the payload) is DENY AP-POL-FAIL / G1 (invariant 1, invariant 4). With a policy authority configured
(ADR-033) an active revision without a valid signature by a trusted authority key is the same DENY.
"""

import hashlib
import json
import re
import shutil
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import rfc8785

from actionproof.signing import KeyRegistry
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
    # Provenance (ADR-028) is not part of what a decision IS: excluded from equality so `Decision("ALLOW", [])` still holds.
    revision: str = field(default="", compare=False)  # sha256 of the decision policy OPA had loaded
    opa_version: str = field(default="", compare=False)
    signed_by: str | None = field(default=None, compare=False)  # ADR-033: verified policy-authority kid, or None


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


# --------------------------------------------------------------------------------------------- policy provenance
# ADR-028. The revision is derived from what OPA reports it has loaded (GET /v1/policies), never from a local file, so
# it names the exact policy that made the decision. Only `package actionproof` modules count: tests and the
# deployment's system.authz differ per host and do not decide anything.
BUNDLE_FORMAT = 1
POLICY_SCHEMA = 1  # bump when the policy input/decision shape changes
_PKG = re.compile(r"^\s*package\s+actionproof\s*$", re.M)
_versions: dict[str, str] = {}  # revision -> OPA version (a version only changes with the OPA binary)


class PolicyArchiveError(Exception):
    pass


def digest_of(modules: Mapping[str, str]) -> str:
    """Stable sha256 of the decision-policy modules: RFC 8785 of {format, schema, {file name: sha256(text, LF)}}."""
    files = {Path(k.replace("\\", "/")).name: _sha(_lf(v)) for k, v in modules.items() if _PKG.search(_first_package(v))}
    return hashlib.sha256(rfc8785.dumps({"bundle_format": BUNDLE_FORMAT, "policy_schema": POLICY_SCHEMA,
                                         "modules": files})).hexdigest()


def _lf(text: str) -> str:
    return "\n".join(text.splitlines()) + ("\n" if text.endswith(("\n", "\r")) else "")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _first_package(text: str) -> str:
    return next((ln for ln in text.splitlines() if ln.strip().startswith("package ")), "")


def digest_of_dir(path) -> str:
    return digest_of({f.name: f.read_text(encoding="utf-8") for f in sorted(Path(path).glob("*.rego"))})


def active_revision(opa_url: str, timeout: float) -> tuple[str, str]:
    """(revision, OPA version) of the policy OPA has loaded right now. Raises on any failure (callers fail closed)."""
    base = opa_url.rstrip("/")
    r = _client.get(f"{base}/v1/policies", timeout=max(timeout, 2.0))
    r.raise_for_status()
    rev = digest_of({m["id"]: m["raw"] for m in r.json()["result"]})
    if rev not in _versions:
        v = _client.get(f"{base}/v1/data/system/version", timeout=max(timeout, 2.0))
        v.raise_for_status()
        _versions[rev] = str(v.json()["result"]["version"])
    return rev, _versions[rev]


def archive_policy(policy_dir, archive_dir) -> str:
    """Copy the decision-policy modules to <archive>/<revision>/ with a manifest; returns the revision. Immutable
    artifacts: an existing revision directory is left as it is."""
    mods = {f.name: f.read_text(encoding="utf-8") for f in sorted(Path(policy_dir).glob("*.rego"))}
    rev = digest_of(mods)
    dest = Path(archive_dir) / rev
    if not dest.exists():
        dest.mkdir(parents=True)
        files = {}
        for name, text in mods.items():
            if _PKG.search(_first_package(text)):
                (dest / name).write_text(_lf(text), encoding="utf-8", newline="\n")
                files[name] = _sha(_lf(text))
        (dest / "manifest.json").write_text(json.dumps({"revision": rev, "bundle_format": BUNDLE_FORMAT,
                                                        "policy_schema": POLICY_SCHEMA, "modules": files},
                                                       indent=1, sort_keys=True))
    return rev


def reconstruct(archive_dir, revision: str, opa_input: dict, opa_bin: str = "opa") -> dict:
    """Re-run a historical decision with `opa eval` against the archived policy of `revision`. The archive is
    re-verified (manifest and file digests, and the revision recomputed) before anything is evaluated."""
    d = Path(archive_dir) / revision
    try:
        man = json.loads((d / "manifest.json").read_text())
        mods = {n: (d / n).read_text(encoding="utf-8") for n in man["modules"]}
    except (OSError, ValueError, KeyError):
        raise PolicyArchiveError("unknown policy revision or unreadable archive") from None
    if man.get("revision") != revision or digest_of(mods) != revision or any(
            hashlib.sha256(t.encode()).hexdigest() != man["modules"][n] for n, t in mods.items()):
        raise PolicyArchiveError("archive does not match its manifest or revision")
    exe = shutil.which(opa_bin) or opa_bin
    p = subprocess.run([exe, "eval", "-d", str(d), "-I", "-f", "json", "data.actionproof.decision"],
                       input=json.dumps(opa_input), capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise PolicyArchiveError("opa eval failed")
    return json.loads(p.stdout)["result"][0]["expressions"][0]["value"]


# --------------------------------------------------------------------------------------------- policy authority
# ADR-033. The revision says WHICH policy decided; a signature by a separate policy-authority key says an AUTHORISED
# owner published it. The owner signs offline (scripts/policy_sign.py); the gateway holds PUBLIC keys only, in a
# KeyRegistry-format file (active / retired / revoked), and verifies `<archive>/<revision>/signature.json`.
_STATEMENT_KEYS = {"bundle_format", "policy_schema", "revision", "authority_kid", "signed_at"}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PolicyAuthorityError(Exception):
    """The message is safe to show (never carries file contents or key material)."""


def authority_statement(revision: str, kid: str, signed_at: int) -> dict:
    """What the authority signs (RFC 8785 via signing.Signer): the revision plus the format it was computed under."""
    return {"bundle_format": BUNDLE_FORMAT, "policy_schema": POLICY_SCHEMA, "revision": revision,
            "authority_kid": kid, "signed_at": signed_at}


def load_authority_keys(path):
    """Strict KeyRegistry load: exactly {"keys": {kid: {"pub", "status"}}}. Any extra field (private key material)
    is refused rather than ignored. Raises PolicyAuthorityError."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if set(raw) != {"keys"} or not isinstance(raw["keys"], dict) or not raw["keys"] or any(
                not isinstance(e, dict) or set(e) != {"pub", "status"} for e in raw["keys"].values()):
            raise ValueError
        return KeyRegistry({kid: (e["pub"], e["status"]) for kid, e in raw["keys"].items()})
    except Exception:
        raise PolicyAuthorityError("policy authority keys file is unreadable or malformed") from None


def verify_authority(revision: str, keys_path, archive_dir) -> str:
    """The kid of a trusted (active or retired), non-revoked authority key that signed exactly `revision`. Raises
    PolicyAuthorityError otherwise. Keys are re-read per call, so a revocation applies to the next decision."""
    registry = load_authority_keys(keys_path)
    if not isinstance(revision, str) or not _HEX64.match(revision):
        raise PolicyAuthorityError("active policy revision is not a sha256")
    try:
        text = (Path(archive_dir) / revision / "signature.json").read_text(encoding="utf-8")
    except OSError:
        raise PolicyAuthorityError("active policy revision is unsigned (no signature in the archive)") from None
    try:
        doc = json.loads(text)
        p = doc["payload"]
        if set(doc) != {"payload", "sig", "kid"} or set(p) != _STATEMENT_KEYS or p["authority_kid"] != doc["kid"] \
                or type(p["signed_at"]) is not int or not all(isinstance(p[k], str) for k in ("revision", "authority_kid")):
            raise ValueError
    except Exception:
        raise PolicyAuthorityError("policy signature file is malformed") from None
    if p["revision"] != revision or (p["bundle_format"], p["policy_schema"]) != (BUNDLE_FORMAT, POLICY_SCHEMA):
        raise PolicyAuthorityError("policy signature is for another revision or bundle format")
    status = registry.status(doc["kid"])
    if status is None:
        raise PolicyAuthorityError("policy signed by an unknown authority key")
    if status == "revoked":
        raise PolicyAuthorityError("policy signed by a revoked authority key")
    if not registry.verify(doc):
        raise PolicyAuthorityError("policy signature is a bad signature for its authority key")
    return doc["kid"]


def decide(payload: dict, opa_url: str, timeout: float, authority_keys: str | None = None,
           archive_dir: str | None = None) -> Decision:
    """authority_keys / archive_dir are Settings.policy_authority_keys / policy_archive_dir. authority_keys None = no
    ADR-033 check (dev and CI default): signed_by stays None and behaviour is exactly ADR-028's."""
    try:
        if not isinstance(payload, dict) or _has_float(payload):
            return _fail("policy input must be a dict with no floats")
        if not opa_url:
            return _fail("OPA URL not configured")
        revision, opa_version = active_revision(opa_url, timeout)  # before the decision; any failure is DENY
        signed_by = None
        if authority_keys is not None:
            if not (authority_keys and archive_dir):
                return _fail("policy authority keys configured without a policy archive dir")
            try:
                signed_by = verify_authority(revision, authority_keys, archive_dir)  # before evaluating
            except PolicyAuthorityError as e:
                return _fail(str(e))
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
        return Decision(outcome, reasons, revision, opa_version, signed_by)
    except httpx.TimeoutException:
        return _fail("OPA timed out")
    except Exception:
        return _fail("policy evaluation failed")
