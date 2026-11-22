"""Archive the current decision policy as an immutable, hash-named artifact (ADR-028).

    python scripts/policy_archive.py            # policy/ -> policy_archive/<revision>/ (+ manifest.json)
    python scripts/policy_archive.py --verify   # print the revision of policy/ and whether it is archived

Commit the new directory whenever policy/actionproof.rego changes, so any past decision (audit detail.policy.revision)
can be re-run with `actionproof.policy.reconstruct`. Deploy OPA from the same files; the running revision is what the
gateway reads from OPA itself.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from actionproof import policy  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--archive", default=str(ROOT / "policy_archive"))
    a = ap.parse_args(argv)
    if a.verify:
        rev = policy.digest_of_dir(ROOT / "policy")
        ok = (Path(a.archive) / rev / "manifest.json").exists()
        print(rev, "archived" if ok else "NOT archived")
        return 0 if ok else 1
    print(policy.archive_policy(ROOT / "policy", a.archive))
    return 0


if __name__ == "__main__":
    sys.exit(main())
