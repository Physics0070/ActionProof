"""Policy-authority signing, run OFFLINE by the policy owner (ADR-033). Never on the gateway host.

    python scripts/policy_sign.py keygen --seed <path>              # new authority seed; prints the PUBLIC key only
    python scripts/policy_sign.py sign --seed <path> --kid <kid>    # archive policy/ and sign its revision
        [--archive policy_archive] [--revision <sha256>]            # or sign an already-archived revision

The seed path is a command-line argument only (no env var, no default). The signature lands in
<archive>/<revision>/signature.json, next to the archived policy; commit it with the archive directory. The gateway
trusts the matching public key through POLICY_AUTHORITY_KEYS (docs/POLICY.md: rotation and revocation).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from actionproof import policy, signing  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    kg = sub.add_parser("keygen")
    kg.add_argument("--seed", required=True)
    sg = sub.add_parser("sign")
    sg.add_argument("--seed", required=True)
    sg.add_argument("--kid", required=True)
    sg.add_argument("--archive", default=str(ROOT / "policy_archive"))
    sg.add_argument("--revision")
    a = ap.parse_args(argv)

    if a.cmd == "keygen":
        signing.generate_key(a.seed)  # refuses to overwrite an existing file
        print(signing.Signer.from_path(a.seed, "policy-authority").public_key_b64())
        return 0

    receipt_key = os.environ.get("SIGNING_KEY_PATH")
    if receipt_key and Path(receipt_key).resolve() == Path(a.seed).resolve():
        print("refused: that is the receipt-signing key; the policy authority needs its own key", file=sys.stderr)
        return 2
    if a.revision:
        d = Path(a.archive) / a.revision
        try:
            man = json.loads((d / "manifest.json").read_text())
            ok = policy.digest_of({n: (d / n).read_text(encoding="utf-8") for n in man["modules"]}) == a.revision
        except (OSError, ValueError, KeyError):
            ok = False
        if not ok:
            print("refused: revision is not archived or does not match its archive", file=sys.stderr)
            return 2
        rev = a.revision
    else:
        rev = policy.archive_policy(ROOT / "policy", a.archive)
    signer = signing.Signer.from_path(a.seed, a.kid)
    doc = signer.sign(policy.authority_statement(rev, a.kid, int(time.time())))
    (Path(a.archive) / rev / "signature.json").write_text(json.dumps(doc, indent=1, sort_keys=True))
    print(f"{rev} signed by {a.kid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
