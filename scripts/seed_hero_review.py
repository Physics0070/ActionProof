"""Park the honest INV-2048 request as a real REVIEW through the real gate, once (idempotent). Used on first boot of a
hosted demo so the public replay and the console queue are not empty. Needs the same env as the API (signing key, OPA)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "fixtures")]

import hero  # noqa: E402

from actionproof.config import load_settings  # noqa: E402
from actionproof.gate import Principal  # noqa: E402
from actionproof.server import build_app, load_server_settings  # noqa: E402

app = build_app(load_settings(), load_server_settings(need_principal=False))
with app._conn_factory() as conn:
    if conn.execute("SELECT 1 FROM pending_reviews WHERE request->'args'->'invoice_id'->>'value' = 'INV-2048'").fetchone():
        print("hero review already parked")
        sys.exit(0)
r = app.call("payments_approve_invoice", hero.hero_request("hosted-hero").model_dump(mode="json"),
             Principal("agent-7", "user-123"))
print("hero review:", r.get("status"), r.get("decision"))
sys.exit(0 if r.get("status") == "pending" else 1)
