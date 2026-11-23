"""Validated settings from the environment (invariant 7). Fail closed: any problem raises ConfigError.

No defaults for database_url or signing_key_path in code; they must come from env.
"""
import math
import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, ValidationError, ValidationInfo, field_validator


class ConfigError(Exception):
    """Configuration is missing or invalid. Callers treat this as DENY at startup."""


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    database_url: str
    opa_url: str
    tesseract_cmd: str
    signing_key_path: str
    signing_kid: str = "k1"
    # Optional JSON registry of trusted receipt-signing public keys (rotation, revocation); unset = the signer only.
    key_registry_path: str | None = None
    # ADR-033 policy authority: the archive holding <revision>/signature.json, and a KeyRegistry-format JSON file of
    # trusted policy-authority PUBLIC keys. Both unset = no signature check (dev/CI default). Keys need the archive.
    policy_archive_dir: str | None = None
    policy_authority_keys: str | None = None
    # ADR-035: a KeyRegistry-format JSON file (the policy-authority format) of trusted adapter evidence PUBLIC keys.
    # Unset = no adapter is trusted: every DefiniteFailure is UNKNOWN and `reconcile auto` refuses to run.
    adapter_evidence_keys: str | None = None
    receipt_ttl_seconds: int = 300
    # `exp` of REVIEW receipts only: a human review can outlast RECEIPT_TTL_SECONDS (ALLOW keeps the short TTL).
    review_receipt_ttl_seconds: int = 3600
    review_token_ttl_seconds: int = 3600
    opa_timeout_seconds: float = 0.2
    # ponytail: entries after the last checkpoint can be truncated undetected, so the default checkpoints every
    # entry (one signature per append); raise it only with an external anchor for the head.
    audit_checkpoint_every: int = 1
    # Warm tesseract processes kept ready (extract.py reads OCR_POOL_SIZE from the environment too); 0 = off.
    ocr_pool_size: int = 0

    @field_validator("database_url", "opa_url", "tesseract_cmd", "signing_key_path", "signing_kid")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v

    @field_validator("opa_url")
    @classmethod
    def _http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("must be an http(s) URL")
        return v

    @field_validator("policy_authority_keys")
    @classmethod
    def _authority(cls, v: str | None, info: ValidationInfo) -> str | None:
        """Fail closed at load: the file parses strictly (public keys only), the archive is configured, and no
        authority key is a receipt-signing key (the gate's signer, or any key in KEY_REGISTRY_PATH)."""
        if v is None:
            return v
        from actionproof.policy import load_authority_keys  # lazy: policy pulls in httpx/verify
        from actionproof.signing import KeyRegistry, Signer
        archive = info.data.get("policy_archive_dir")
        if not archive or not os.path.isdir(archive):
            raise ValueError("needs POLICY_ARCHIVE_DIR (an existing directory)")
        try:
            authority = set(load_authority_keys(v).public_keys(include_revoked=True).values())
            receipt = {Signer.from_path(info.data["signing_key_path"], info.data["signing_kid"]).public_key_b64()}
            if info.data.get("key_registry_path"):
                receipt |= set(KeyRegistry.from_json(info.data["key_registry_path"])
                               .public_keys(include_revoked=True).values())
        except Exception:
            raise ValueError("policy authority keys or the receipt key are unreadable") from None
        if authority & receipt:
            raise ValueError("a policy-authority key must never be a receipt-signing key")
        return v

    @field_validator("adapter_evidence_keys")
    @classmethod
    def _adapter_keys(cls, v: str | None) -> str | None:
        """Fail closed at load: the file parses strictly (public keys only). Disjointness from the receipt key is
        checked where both are loaded (Gate.__init__)."""
        if v is not None:
            from actionproof.evidence import load_keys  # lazy, like the policy authority check
            load_keys(v)
        return v

    @field_validator("ocr_pool_size")
    @classmethod
    def _pool(cls, v: int) -> int:
        if not 0 <= v <= 16:
            raise ValueError("must be 0..16")
        return v

    @field_validator("receipt_ttl_seconds", "review_receipt_ttl_seconds", "review_token_ttl_seconds",
                     "opa_timeout_seconds", "audit_checkpoint_every")
    @classmethod
    def _positive(cls, v):
        if not (math.isfinite(v) and v > 0):
            raise ValueError("must be > 0")
        return v


# Field name -> env var. Env keys not listed here are ignored.
_ENV = {name: name.upper() for name in Settings.model_fields}


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    raw = {field: env[var] for field, var in _ENV.items() if var in env}
    try:
        return Settings.model_validate(raw, strict=False)
    except ValidationError as e:
        # Name the bad fields only; never echo values (a DSN may hold a password).
        bad = sorted({str(err["loc"][0]) for err in e.errors() if err.get("loc")})
        raise ConfigError(f"invalid or missing config: {', '.join(_ENV[b] for b in bad if b in _ENV)}") from None
