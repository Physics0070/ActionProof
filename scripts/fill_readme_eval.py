"""Fill the README evaluation block from eval/results.json: python scripts/fill_readme_eval.py [--check]

Replaces everything between <!-- EVAL-TABLE --> and <!-- /EVAL-TABLE --> in README.md. Numbers come only from the
results file; with no file (or no usable arms) the block says "not run". --check exits 1 if README.md is stale.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README, RESULTS = ROOT / "README.md", ROOT / "eval" / "results.json"
BEGIN, END = "<!-- EVAL-TABLE -->", "<!-- /EVAL-TABLE -->"
NOT_RUN = ("**Not run yet.** The evaluation numbers are filled in after the final eval run "
           "(`python -m eval.run`, then `python scripts/fill_readme_eval.py`). Until then this README claims none.")
ORDER = ("no_gate", "schema_only", "llm_judge", "policy_gateway", "actionproof")


def render(results: dict | None) -> str:
    arms = (results or {}).get("arms") if isinstance(results, dict) else None
    if not isinstance(arms, dict) or not arms:
        return NOT_RUN
    rows = ["| Arm | Attacks succeeded | False blocks (benign) | Added p95 (ms) |", "|---|---|---|---|"]
    for name in [a for a in ORDER if a in arms] + [a for a in arms if a not in ORDER]:
        a = arms[name]
        if a.get("status") != "ok":
            rows.append(f"| {name} | {a.get('status', 'not run')} | - | - |")
            continue
        t, b, lat = a["attacks"]["total"], a["benign"], a["latency_ms"]
        rows.append(f"| {name} | {t['success']} / {t['n']} | {b['false_blocks']} / {b['n']} ({b['false_block_rate']:.1%}) "
                    f"| {lat['added_p95']:.0f} |")
    c = results.get("commit") or {}
    tm, tg = results.get("targets_met") or {}, results.get("targets") or {}
    out = ["\n".join(rows), "",
           f"Run on commit `{str(c.get('sha', 'unknown'))[:10]}`{' (working tree dirty)' if c.get('dirty') else ''}. "
           f"Held-out set: {tm.get('held_out_set', 'unknown')}, n = {tm.get('held_out_n', '?')}; NOT independent."]
    if tg:
        out.append(f"Proposed targets (not results): at most {tg.get('held_out_successes_max')} held-out successes, "
                   f"false-block rate at most {tg.get('false_block_rate_max', 0):.0%}, added p95 at most "
                   f"{tg.get('added_p95_ms_max')} ms. Met: held-out successes {tm.get('held_out_successes')}, "
                   f"false blocks {tm.get('false_block_rate')}, latency {tm.get('added_p95_ms')}.")
    return "\n".join(out)


def apply(text: str, block: str) -> str:
    i, j = text.index(BEGIN) + len(BEGIN), text.index(END)
    return f"{text[:i]}\n{block}\n{text[j:]}"


def main(argv=None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    try:
        results = json.loads(RESULTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        results = None
    text = README.read_text(encoding="utf-8")
    new = apply(text.replace("\r\n", "\n"), render(results))
    if check:
        return 0 if new == text.replace("\r\n", "\n") else 1
    README.write_text(new, encoding="utf-8", newline="\n")
    print("README evaluation block " + ("filled from eval/results.json" if results else "set to 'not run'"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
