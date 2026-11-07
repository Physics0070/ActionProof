"""Generate the Ed25519 signing seed: python scripts/gen_key.py [path]

Path defaults to SIGNING_KEY_PATH, then keys/dev-signing.key (git-ignored). Refuses to overwrite.
Prints only the path and the PUBLIC key.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from actionproof.signing import Signer, generate_key  # noqa: E402

if __name__ == "__main__":
    path = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SIGNING_KEY_PATH", "keys/dev-signing.key"))
    if not path.is_absolute():
        path = ROOT / path
    try:
        generate_key(path)
    except FileExistsError:
        sys.exit(f"refusing to overwrite existing key at {path}")
    print(f"wrote {path}\npublic key (b64): {Signer.from_path(path, 'k1').public_key_b64()}")
