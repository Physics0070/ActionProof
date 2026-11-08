"""Park one fresh hero REVIEW and print {"request_hash": ...}: python scripts/mint_review.py

For e2e and demos (docker compose exec -T api python scripts/mint_review.py). Goes through the real gate.prepare +
review.park exactly like the MCP server; needs the demo seed (hero invoice) and the signing key. Not tool-facing.
"""
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from actionproof import review, server  # noqa: E402
from actionproof.config import ConfigError, load_settings  # noqa: E402
from actionproof.gate import Principal  # noqa: E402
from fixtures import hero  # noqa: E402

if __name__ == "__main__":
    try:
        app = server.build_app(load_settings(), server.load_server_settings(need_principal=False))
    except ConfigError as e:
        sys.exit(f"ConfigError: {e}")
    req = hero.hero_request(f"e2e-{secrets.token_hex(6)}")
    res = app.gate.prepare(req, hero.load_docs(), principal=Principal("agent-7", "user-123"))
    if res.decision != "REVIEW":
        sys.exit(f"expected REVIEW, got {res.decision}; is the demo seeded (DEMO_SEED=1)?")
    review.park(app._conn_factory, req, res.receipt, res.reasons, res=res)
    print(json.dumps({"request_hash": res.receipt["payload"]["request_hash"]}))
