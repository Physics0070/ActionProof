"""Audit demo for the video: verify the real demo DB, copy it, edit one audit row in the COPY, verify again.
Writes video/data/audit-run.txt (real verifier output). Run with the repo venv python from the repo root."""
import os, subprocess, sys
from pathlib import Path
import psycopg
ROOT = Path(__file__).resolve().parents[1]
env = dict(os.environ)
for l in (ROOT / ".env.example").read_text().splitlines():
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1); env.setdefault(k.strip(), v.split("#")[0].strip())
base = env["DATABASE_URL"].rsplit("/", 1)[0]
src, cp = "actionproof_demo", "actionproof_demo_tampered"
from actionproof import signing
PUB = signing.Signer.from_path(str(ROOT / env["SIGNING_KEY_PATH"]), env.get("SIGNING_KID", "k1")).public_key_b64()
def run(db):
    e = dict(env, DATABASE_URL=f"{base}/{db}")
    r = subprocess.run([sys.executable, "-m", "actionproof.audit", "verify", "--public-key", PUB], cwd=ROOT, env=e, capture_output=True, text=True)
    return r.stdout.strip() + r.stderr.strip(), r.returncode
with psycopg.connect(f"{base}/postgres", autocommit=True) as c:
    c.execute(f"DROP DATABASE IF EXISTS {cp} WITH (FORCE)")
    c.execute(f"CREATE DATABASE {cp} TEMPLATE {src}")
out = []
l, rc = run(src); out.append(("$ python -m actionproof.audit verify        # the demo database", l, rc))
with psycopg.connect(f"{base}/{cp}", autocommit=True) as c:
    seq = 9
    c.execute("ALTER TABLE audit_log DISABLE TRIGGER USER")  # what a DB admin could do; the live DB keeps its append-only trigger
    c.execute("UPDATE audit_log SET ts = ts + 1 WHERE seq = %s", (seq,))
out.append((f"$ (a DB admin edits one row of a COPY: audit_log seq {seq}, ts + 1)", "", 0))
l, rc = run(cp); out.append(("$ python -m actionproof.audit verify        # the edited copy", l, rc))
with psycopg.connect(f"{base}/postgres", autocommit=True) as c:
    c.execute(f"DROP DATABASE IF EXISTS {cp} WITH (FORCE)")
(ROOT / "video/data/audit-run.txt").write_text("\n".join(f"{a}\n{b}\n[exit {r}]" if b else a for a, b, r in out) + "\n", encoding="utf-8")
print((ROOT / "video/data/audit-run.txt").read_text())
