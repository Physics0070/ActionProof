"""Proxy map validation (src/actionproof/proxy.py): anything ambiguous aborts startup with ConfigError (fail closed)."""
import json
from pathlib import Path

import pytest

from actionproof import proxy
from actionproof.config import ConfigError

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "proxy-map.json"
GOOD = {"approve_invoice": {"action": "payments.approve_invoice",
                            "args": {"invoice_id": "invoice_id", "amount": "amount"}}}


def _load(tmp_path, m) -> proxy.ProxyMap:
    p = tmp_path / "m.json"
    p.write_text(m if isinstance(m, str) else json.dumps(m), encoding="utf-8")
    return proxy.load_map(str(p))


def test_example_map_is_valid():
    m = proxy.load_map(str(EXAMPLE))
    assert m.exposed() == {"approve_invoice": "payments.approve_invoice"}
    assert m.upstream_names() == {"approve_invoice", "get_record", "preview_approval"}


@pytest.mark.parametrize("bad", [
    "{", "[]", {}, {"tools": {}},
    {"tools": {"x": {"action": "payments.wire_money", "args": {}}}},                       # unknown action
    {"tools": {"x": {"action": "payments.approve_invoice", "args": {"a": "secret_field"}}}},  # arg not in registry
    {"tools": {"x": {"action": "payments.approve_invoice", "args": {}, "extra": 1}}},         # unknown key
    {"tools": {**GOOD, "approve2": GOOD["approve_invoice"]}},                                # one action twice
    {"tools": {"extract_fields": GOOD["approve_invoice"]}},                                  # reserved name
    {"tools": {"bad name!": GOOD["approve_invoice"]}},
    {"tools": {"approve_invoice": {**GOOD["approve_invoice"], "read_record": "approve_invoice"}}},  # read = write
    {"tools": {"approve_invoice": {**GOOD["approve_invoice"], "idempotency_arg": "amount"}}},      # param clash
    {"timeout_seconds": 0, "tools": GOOD},
])
def test_invalid_maps_raise(tmp_path, bad):
    with pytest.raises(ConfigError) as e:
        _load(tmp_path, bad)
    assert "PROXY_MAP_PATH" in str(e.value)


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        proxy.load_map(str(tmp_path / "nope.json"))


def test_upstream_must_offer_every_mapped_tool(tmp_path):
    m = _load(tmp_path, {"tools": {"approve_invoice": {**GOOD["approve_invoice"], "dry_run": "preview_approval"}}})
    m.check_offered({"approve_invoice", "preview_approval", "delete_all_invoices"})  # extra upstream tools are fine
    with pytest.raises(ConfigError):
        m.check_offered({"approve_invoice"})
