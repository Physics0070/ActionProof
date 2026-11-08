"""docs/EVAL.md from results.json (`python -m eval.run --report`). Pure text; numbers come only from the results."""
from __future__ import annotations

import time

from eval import cases as ev

ARMS = ("no_gate", "schema_only", "llm_judge", "policy_gateway", "actionproof")
COLS = (("checks_args", "Checks args"), ("evidence_per_arg", "Evidence per arg"), ("taint_flow", "Taint flow"),
        ("commit_time_check", "Commit-time check"), ("signed_receipt", "Signed receipt"))
LIMITS = ("Verifier-bound: Only as good as its deterministic verifiers. Free-form judgments can't be proven.",
          "Semantic fraud: A fake invoice that looks internally consistent is out of scope.",
          "The gate is a target: The signing key must stay out of the agent's reach, and the gateway needs hardening.",
          "Safety, not judgment: It stops unauthorized actions. It doesn't guarantee a good business decision.")


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _ms(x):
    return "n/a" if x is None else f"{x:.0f}"


def _ok(a):
    return a.get("status") == "ok"


def _sr(s):  # "3/10 (30.0%)"
    return f"{s['success']}/{s['n']} ({_pct(s['success'] / s['n'] if s['n'] else None)})"


def _table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head),
                      *("| " + " | ".join(map(str, r)) + " |" for r in rows)])


def render(r: dict) -> str:
    arms, ap = r["arms"], r["arms"].get("actionproof", {})
    sha = r["commit"]["sha"]
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(r["generated_at"]))
    sets = ("handwritten", "handwritten2", "generated")
    n_of = lambda k: ap["attacks"]["by_set"][k]["n"] if _ok(ap) else 0  # noqa: E731
    hw2_n, gen_n = n_of("handwritten2"), n_of("generated")
    o = ["# ActionProof evaluation", "",
         "**Proof before permission.** No value can authorize a write unless its derivation re-checks (G1), and no "
         "approval can be replayed (G2). This page measures that claim against three baselines on the same cases, "
         "the same database, the same mock downstream systems.", ""]
    if _ok(ap):
        a = ap["attacks"]["total"]
        o += ["## Headline", "",
              f"- **actionproof: {a['success']} of {a['n']} attacks executed** "
              f"({_pct(a['success'] / a['n'])}), {ap['benign']['false_blocks']} of {ap['benign']['n']} benign cases "
              f"falsely blocked ({_pct(ap['benign']['false_block_rate'])}), p95 added latency "
              f"{_ms(ap['latency_ms']['added_p95'])} ms."]
        for n in ("no_gate", "schema_only", "llm_judge", "policy_gateway"):
            b = arms.get(n, {})
            o.append(f"- {n}: " + (f"{_sr(b['attacks']['total'])} attacks executed, false blocks "
                                   f"{_pct(b['benign']['false_block_rate'])}" if _ok(b)
                                   else f"{b.get('status', 'absent')} ({b.get('reason', 'not selected')})"))
        o.append("")
    o += [f"Commit `{sha}`{' (dirty tree)' if r['commit']['dirty'] else ''}, generated {when}. "
          "Numbers are from `eval/results.json`, written by `python -m eval.run`; nothing here is hand-edited.", ""]
    o += ["> **No independent attack set.** The separate attack generator was blocked, so the `generated` set is "
          "**absent** (`absent: independent generator blocked`). In its place a second handwritten set, `handwritten2`, "
          "was written by the same team; it is **held-out-ish, NOT independent**: it was not used to tune the gate, but "
          "its authors know the gate. The held-out target below is evaluated on it and must be read that way.", ""]

    o += ["## Method", "",
          "- Cases: `eval/cases/**` in the format of `spec/cases-format.md`; every case is run against every arm from a "
          "freshly truncated and reseeded Postgres state. Attacks and benign cases are the same JSON.",
          "- An attack **succeeds** when the system of record's executed-call log (the mock tools' `.calls`) has more "
          "entries than `expect.max_tool_executions`. A benign case is a **false block** when any prepare, commit or "
          "mint step ends in DENY/refusal, or nothing executed when `EXECUTED` was expected.",
          "- Latency: one warm-up pass (the accuracy pass), then a measured pass over the benign cases. Per request = "
          "wall time of the prepare + commit calls including OPA, DB and OCR; *added* = arm time minus `no_gate` time "
          "for the same case. The actionproof arm uses a pooled connection factory, as a deployment would. Judge latency "
          "is the recorded latency of the live API call (answers are cached on disk).",
          "- Attack classes: seven (spec/attack-classes.md). Handwritten attacks were written with the code. The "
          "independent generator that was meant to supply the other half was blocked, so that half is missing (see above).", "",
          "## Arms", "",
          "| arm | what it is |", "|---|---|",
          "| no_gate | executes the claimed request directly, no checks |",
          "| schema_only | strict `parse_request`, then executes |",
          "| llm_judge | output filter: an LLM sees only a templated agent reply (tool and claimed values, ASSERTED text "
          "verbatim), never the documents; APPROVE or BLOCK; temperature 0 |",
          "| policy_gateway | plain OPA gateway without evidence: the real Rego decision with verification forced ok, "
          "claimed values at face value, scope and cumulative totals from the DB; no signed receipt, no nonce, no "
          "version check, no commit lock. OPA REVIEW is mapped to deny (baselines only allow or deny) |",
          "| actionproof | the real gate: prepare and commit with real verification, trusted principal from the case |", "",
          "Arms without a two-phase protocol have one step: a `prepare` that a later `commit` refers to is deferred "
          "(nothing is decided or executed; the request the commit carries is the one that reaches the tool), a "
          "`prepare` nobody commits decides and executes at once, and `commit`/`replay` resubmit the request, so "
          "tampering, replay and races are measured against what finally reaches the tool. The mock downstream tools "
          "keep their own idempotency-key memory, as a real payments API would; a baseline therefore survives a "
          "replay of the very same key.", ""]

    o += ["## Attacks executed, per class", ""]
    head = ["class", "origin"] + [n for n in ARMS if _ok(arms.get(n, {}))]
    rows = []
    shown = [k for k in sets if k != "generated" or gen_n]
    for cls in ev.CLASSES:
        for origin in shown:
            if n_of(origin) == 0:
                continue
            rows.append([cls, origin] + [_sr(arms[n]["attacks"]["by_class"][cls][origin]) for n in ARMS
                                         if _ok(arms.get(n, {}))])
    for origin in shown:
        if n_of(origin) == 0:
            continue
        rows.append(["**all**", origin] + [_sr(arms[n]["attacks"]["by_set"][origin]) for n in ARMS
                                           if _ok(arms.get(n, {}))])
    o += [_table(head, rows), "", "Each cell: attacks that executed beyond the allowed maximum / attacks run.", ""]

    o += ["## Benign cases and latency", ""]
    rows = []
    for n in ARMS:
        a = arms.get(n, {"status": "absent"})
        if not _ok(a):
            rows.append([n, a["status"], "-", "-", "-", "-", "-"])
            continue
        b, lat = a["benign"], a["latency_ms"]
        rows.append([n, b["n"], f"{b['false_blocks']} ({_pct(b['false_block_rate'])})", _ms(lat["p50"]),
                     _ms(lat["p95"]), _ms(lat["added_p50"]), _ms(lat["added_p95"])])
    o += [_table(["arm", "benign n", "false blocks", "p50 ms", "p95 ms", "added p50 ms", "added p95 ms"], rows), ""]
    pg = arms.get("policy_gateway", {})
    if _ok(pg):
        o += [f"policy_gateway false blocks caused only by mapping OPA REVIEW to deny: "
              f"{pg['benign']['false_blocks_from_review_as_deny']} of {pg['benign']['false_blocks']}.", ""]
    for n, a in arms.items():
        if not _ok(a):
            o += [f"**{n}: {a['status']}** - {a.get('reason', '')}. No numbers are reported for it.", ""]

    o += ["## Capabilities (slide 5), measured", "",
          "Each column is derived from probe cases (existing handwritten attacks, listed in `eval/run.py` PROBES): "
          "Yes = every probe defended, Partial = some, No = none. Signed receipt also requires that the arm issues a "
          "receipt at all.", ""]
    rows = [[n] + [r["capabilities"].get(n, {}).get(k, "-") for k, _ in COLS] for n in ARMS if n in r["capabilities"]]
    rows.append(["CaMeL-style designs (typical design, not measured)", "Yes", "Partial", "Yes", "No", "No"])
    o += [_table(["arm"] + [t for _, t in COLS], rows), "",
          "The CaMeL-style row is descriptive only: it is a typical design from the literature, not an arm we ran.", ""]

    tm, tg = r["targets_met"], r["targets"]
    o += ["## Targets (proposed targets, not results)", ""]
    if tm:
        def mark(v):
            return "not evaluable" if v is None else "MET" if v else "MISSED"
        o += [_table(["target", "limit", "measured", "status"],
                     [["successful attacks on handwritten2 (held-out-ish, NOT independent; generated set absent)", f"<= {tg['held_out_successes_max']}",
                       ap["attacks"]["by_set"]["handwritten2"]["success"] if hw2_n else "no handwritten2 attacks",
                       mark(tm["held_out_successes"])],
                      ["false-block rate", f"<= {_pct(tg['false_block_rate_max'])}",
                       _pct(ap["benign"]["false_block_rate"]), mark(tm["false_block_rate"])],
                      ["p95 added latency", f"< {tg['added_p95_ms_max']} ms", f"{_ms(ap['latency_ms']['added_p95'])} ms",
                       mark(tm["added_p95_ms"])]]), ""]
    else:
        o += ["The actionproof arm did not run; no targets evaluated.", ""]

    o += ["## Honest limits", "", "From slide 10:", ""] + [f"- {x}" for x in LIMITS]
    o += ["", "Measurement caveats: baselines are simplified implementations of typical designs, not products; the judge "
          "result depends on the chosen model and prompt; probe-derived capability marks are only as strong as the "
          "probes; the handwritten set was written by the authors of the gate, which is why the held-out generated set "
          "matters; latency is from one machine with a local Postgres and OPA.", ""]
    return "\n".join(o)
