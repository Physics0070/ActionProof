"""Child for the concurrent-publisher test: waits for the go-file, then publishes one checkpoint to the anchor.
Exit 0 = appended or already anchored (prints 'published' / 'noop'); exit 3 = AnchorError (prints the reason)."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from actionproof.anchor import AnchorError, LocalAnchor  # noqa: E402

anchor_path, env_path, pub, go = sys.argv[1:5]
env = json.loads(Path(env_path).read_text())
deadline = time.time() + 30
while not Path(go).exists() and time.time() < deadline:
    time.sleep(0.001)
try:
    print("published" if LocalAnchor(anchor_path).publish(env, pub) else "noop")
except AnchorError as e:
    print(f"error: {e}")
    sys.exit(3)
