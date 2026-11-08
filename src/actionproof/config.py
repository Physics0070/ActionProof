"""Validated settings from the environment (invariant 7). Fail closed: any problem raises ConfigError.

No defaults for database_url or signing_key_path in code; they must come from env.
"""
import math
import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


class ConfigError(Exception):
    """Configuration is missing or invalid. Callers treat this as DENY at startup."""


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    database_url: str
    opa_url: str
    tesseract_cmd: str
    signing_key_path: str
    signing_kid: str = "k1"
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
