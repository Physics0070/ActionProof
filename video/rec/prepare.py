"""Prepare the demo DB for a live console take: reset + seed (same as demo.sh's start), console users with the logins
from keys/demo-logins.txt, then mint one real REVIEW through the gate. Prints {"request_hash": ...}.
Run from repo root with .venv python and .env.example exported."""
import json, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import creds
ROOT = Path(__file__).resolve().parents[2]
env = dict(os.environ)
for l in (ROOT / ".env.example").read_text().splitlines():
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1); env.setdefault(k.strip(), v.split("#")[0].strip())
env["DATABASE_URL"] = env["DATABASE_URL"].rsplit("/", 1)[0] + "/actionproof_demo"
env["PYTHONPATH"] = str(ROOT / "src")
for login, pw in creds.logins().items():
    env["CONSOLE_PASSWORD_" + login.upper().replace("-", "_")] = pw
def run(*a):
    r = subprocess.run([sys.executable, *a], cwd=ROOT, env=env, capture_output=True, text=True)
    if r.returncode: sys.exit(f"{a}: {r.stderr[-600:]}")
    return r.stdout
run("scripts/demo_seed.py", "--reset")
run("scripts/seed_console.py")
print(run("scripts/mint_review.py").strip().splitlines()[-1])
