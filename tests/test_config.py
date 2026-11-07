"""Invariant 7: config comes from validated env; anything wrong fails closed (ConfigError)."""
import pydantic
import pytest

from actionproof.config import ConfigError, Settings, load_settings

GOOD = {
    "DATABASE_URL": "postgresql://u:p@localhost:5433/db",
    "OPA_URL": "http://localhost:8181",
    "TESSERACT_CMD": "tesseract",
    "SIGNING_KEY_PATH": "keys/dev-signing.key",
}


def test_valid_env_ok_with_defaults():
    s = load_settings(GOOD)
    assert s.database_url == GOOD["DATABASE_URL"]
    assert s.signing_kid == "k1"
    assert s.receipt_ttl_seconds == 300
    assert s.review_token_ttl_seconds == 3600
    assert s.opa_timeout_seconds == 0.2


def test_overrides_parsed():
    s = load_settings({**GOOD, "SIGNING_KID": "k2", "RECEIPT_TTL_SECONDS": "60",
                       "REVIEW_TOKEN_TTL_SECONDS": "120", "OPA_TIMEOUT_SECONDS": "0.5"})
    assert (s.signing_kid, s.receipt_ttl_seconds, s.review_token_ttl_seconds, s.opa_timeout_seconds) == ("k2", 60, 120, 0.5)


@pytest.mark.parametrize("missing", ["DATABASE_URL", "OPA_URL", "TESSERACT_CMD", "SIGNING_KEY_PATH"])
def test_missing_required_raises(missing):
    env = {k: v for k, v in GOOD.items() if k != missing}
    with pytest.raises(ConfigError):
        load_settings(env)


@pytest.mark.parametrize("key,value", [
    ("DATABASE_URL", ""), ("DATABASE_URL", "   "), ("SIGNING_KEY_PATH", ""),
    ("OPA_URL", "localhost:8181"), ("OPA_URL", "ftp://x"), ("SIGNING_KID", ""),
    ("RECEIPT_TTL_SECONDS", "0"), ("RECEIPT_TTL_SECONDS", "-5"), ("RECEIPT_TTL_SECONDS", "abc"),
    ("RECEIPT_TTL_SECONDS", "1.5"), ("REVIEW_TOKEN_TTL_SECONDS", "0"),
    ("OPA_TIMEOUT_SECONDS", "0"), ("OPA_TIMEOUT_SECONDS", "-1"), ("OPA_TIMEOUT_SECONDS", "nan"),
])
def test_invalid_values_raise(key, value):
    with pytest.raises(ConfigError):
        load_settings({**GOOD, key: value})


def test_unknown_env_key_ignored():
    assert load_settings({**GOOD, "PATH": "x", "SOMETHING_ELSE": "y"}).signing_kid == "k1"


def test_extra_field_in_model_forbidden():
    fields = {"database_url": "postgresql://x", "opa_url": "http://x", "tesseract_cmd": "t",
              "signing_key_path": "k"}
    Settings(**fields)
    with pytest.raises(pydantic.ValidationError):
        Settings(**fields, bogus="1")


def test_error_message_does_not_echo_values():
    with pytest.raises(ConfigError) as e:
        load_settings({**GOOD, "DATABASE_URL": "postgresql://u:supersecret@h/db", "OPA_URL": "nope"})
    assert "supersecret" not in str(e.value)
