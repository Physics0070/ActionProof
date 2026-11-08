"use client";
// /evaluation: everything here is read from GET /api/public/eval (eval/results.json). No result is typed in source;
// when the payload says available:false the page says so and shows nothing in its place.
// Layout: one headline, a three-number target strip, five big comparison rows; the rest sits in <details>.
import { useEffect, useState } from "react";
import { apiGet, type Schemas } from "@/lib/api";
import { CLASSES, FRAMING, SETS, TABLE_COLS, TABLE_ROWS } from "@/lib/site-copy";
import { ms, pct, readEval, utc, type Arm, type EvalResults, type SetCount } from "@/lib/site-data";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal } from "@/components/ui/Signal";

type Load = { attempt: number; out: { ok: Schemas["EvalOut"] } | { err: string } };

const ARM_LABEL: Record<string, string> = {
  no_gate: "No gate",
  schema_only: "Schema validation only",
  llm_judge: "Output filter or LLM judge",
  policy_gateway: "Plain policy gateway (OPA)",
  actionproof: "ActionProof",
};

function Count({ c, emptyText }: { c: SetCount | undefined; emptyText: string }) {
  if (!c || c.n === 0) return <span className="t-muted">{emptyText}</span>;
  return (
    <span>
      {c.success} of {c.n} <span className="t-muted">({pct(c.success, c.n)})</span>
    </span>
  );
}

type Mood = "met" | "missed" | "unmeasured" | "yes" | "partial" | "no";

/** Shape + word + colour, never colour alone: circle = good, triangle = partial or unmeasured, square = bad. */
function Mark({ state, word }: { state: Mood; word?: string }) {
  const tone = state === "met" || state === "yes" ? "ALLOW" : state === "missed" || state === "no" ? "DENY" : "REVIEW";
  const text = word ?? { met: "Met", missed: "Missed", unmeasured: "Not measured", yes: "Yes", partial: "Partial", no: "No" }[state];
  return <Signal state={tone} word={text} />;
}

function Headline({ r }: { r: EvalResults }) {
  const ap = r.arms["actionproof"];
  if (!ap || ap.status !== "ok" || !ap.attacks) {
    return <p role="status">The ActionProof arm did not run in this evaluation, so there is no headline result to show.</p>;
  }
  const total = ap.attacks.total;
  const rivals = ["no_gate", "schema_only", "llm_judge", "policy_gateway"].filter((k) => r.arms[k]?.attacks);
  return (
    <div className="ev-hero">
      <p className="ev-big" aria-label={`${total.success} of ${total.n} attacks executed against ActionProof`}>
        <span className="ev-num">{total.success}</span> of {total.n}
        <span className="ev-big-cap">attacks executed against ActionProof</span>
      </p>
      <ul className="ev-bars" aria-label="Attacks that executed, by approach">
        {[...rivals, "actionproof"].map((k) => {
          const a = r.arms[k]?.attacks?.total;
          if (!a) return null;
          return (
            <li key={k} data-self={k === "actionproof"}>
              <span className="ev-bar-label">{ARM_LABEL[k] ?? k}</span>
              <span className="ev-bar" aria-hidden="true">
                <span style={{ width: `${a.n ? (a.success / a.n) * 100 : 0}%` }} />
              </span>
              <span className="ev-bar-n">
                {a.success} of {a.n}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function TargetStrip({ r }: { r: EvalResults }) {
  const t = r.targets;
  const m = r.targets_met;
  const ap = r.arms["actionproof"];
  if (!t || !m) return <p className="t-muted">This evaluation did not record targets.</p>;
  const heldN = m.held_out_n ?? 0;
  const raw: unknown = m.held_out_successes;
  const held: Mood = heldN === 0 || raw == null ? "unmeasured" : typeof raw === "boolean" ? (raw ? "met" : "missed") : (raw as number) <= t.held_out_successes_max ? "met" : "missed";
  const heldSet = ap?.attacks?.by_set.handwritten2;
  const fb: Mood = m.false_block_rate == null ? "unmeasured" : m.false_block_rate ? "met" : "missed";
  const lat: Mood = m.added_p95_ms == null ? "unmeasured" : m.added_p95_ms ? "met" : "missed";
  const cards: { k: string; label: string; value: string; state: Mood }[] = [
    {
      k: "attacks",
      label: `Attacks that executed on the held-out set (target ${t.held_out_successes_max})`,
      value: heldSet && String(m.held_out_set ?? "").startsWith("handwritten2") ? `${heldSet.success} of ${heldSet.n}` : heldN > 0 ? `${heldN} cases` : "none",
      state: held,
    },
    {
      k: "blocks",
      label: `False blocks on benign cases (target at most ${Math.round(t.false_block_rate_max * 1000) / 10}%)`,
      value: ap?.benign ? pct(ap.benign.false_blocks, ap.benign.n) : "n/a",
      state: fb,
    },
    {
      k: "latency",
      label: `Added latency, p95 (target under ${t.added_p95_ms_max} ms)`,
      value: ap?.latency_ms ? ms(ap.latency_ms.added_p95) : "n/a",
      state: lat,
    },
  ];
  return (
    <ul className="ev-targets">
      {cards.map((c) => (
        <li key={c.k}>
          <p className="ev-target-v">{c.value}</p>
          <p className="ev-target-l">{c.label}</p>
          <Mark state={c.state} />
        </li>
      ))}
    </ul>
  );
}

function Comparison({ r }: { r: EvalResults }) {
  return (
    <div className="ev-compare" role="table" aria-label="What each approach checks, measured by probes in the evaluation">
      <div className="ev-crow ev-chead" role="row">
        <span role="columnheader">Approach</span>
        {TABLE_COLS.map((c) => (
          <span key={c.key} role="columnheader">
            {c.label}
          </span>
        ))}
      </div>
      {TABLE_ROWS.map((row) => {
        const caps = row.measured ? r.capabilities[row.key] : undefined;
        return (
          <div key={row.key} className="ev-crow" role="row" data-self={row.key === "actionproof"}>
            <span role="rowheader" className="ev-cname">
              {row.label}
              {!row.measured ? <small>typical design, not measured</small> : null}
            </span>
            {TABLE_COLS.map((c) => {
              const v = caps?.[c.key];
              const k = (v ?? "").toLowerCase();
              return (
                <span key={c.key} role="cell" data-col={c.label}>
                  {v ? <Mark state={k.startsWith("y") ? "yes" : k.startsWith("p") ? "partial" : "no"} word={v} /> : <span className="t-muted">n/a</span>}
                </span>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

function ClassTable({ ap }: { ap: Arm }) {
  const by = ap.attacks?.by_class ?? {};
  return (
    <div className="table-wrap">
      <table className="data-table">
        <caption className="visually-hidden">Attacks that executed against ActionProof, by class and by set</caption>
        <thead>
          <tr>
            <th scope="col">Attack class</th>
            <th scope="col">Control</th>
            <th scope="col">Test scenario</th>
            {SETS.map((s) => (
              <th key={s.key} scope="col">
                {s.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {CLASSES.map((c) => (
            <tr key={c.key}>
              <th scope="row">{c.label}</th>
              <td>{c.control}</td>
              <td>{c.test}</td>
              <td>
                <Count c={by[c.key]?.handwritten} emptyText="not run" />
              </td>
              <td>
                <Count c={by[c.key]?.handwritten2} emptyText="not run" />
              </td>
              <td>
                <Count c={by[c.key]?.generated} emptyText="absent: the independent generator was blocked" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ArmTable({ r }: { r: EvalResults }) {
  const order = ["no_gate", "schema_only", "llm_judge", "policy_gateway", "actionproof"].filter((k) => r.arms[k]);
  return (
    <div className="table-wrap">
      <table className="data-table">
        <caption className="visually-hidden">All approaches on the same cases</caption>
        <thead>
          <tr>
            <th scope="col">Approach</th>
            <th scope="col">Attacks executed (handwritten)</th>
            <th scope="col">False blocks (benign)</th>
            <th scope="col">Added latency p95</th>
          </tr>
        </thead>
        <tbody>
          {order.map((k) => {
            const a = r.arms[k];
            if (!a) return null;
            if (a.status !== "ok") {
              return (
                <tr key={k}>
                  <th scope="row">{ARM_LABEL[k]}</th>
                  <td colSpan={3} className="t-muted">
                    did not run ({a.status})
                  </td>
                </tr>
              );
            }
            return (
              <tr key={k} data-self={k === "actionproof"}>
                <th scope="row">{ARM_LABEL[k] ?? k}</th>
                <td>
                  <Count c={a.attacks?.by_set.handwritten} emptyText="n/a" />
                </td>
                <td>{a.benign ? `${a.benign.false_blocks} of ${a.benign.n} (${pct(a.benign.false_blocks, a.benign.n)})` : "n/a"}</td>
                <td>{a.latency_ms ? ms(a.latency_ms.added_p95) : "n/a"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function EvalView() {
  const [attempt, setAttempt] = useState(0);
  const [load, setLoad] = useState<Load | null>(null);

  useEffect(() => {
    let live = true;
    apiGet("/api/public/eval")
      .then((ok) => live && setLoad({ attempt, out: { ok } }))
      .catch((e: unknown) => live && setLoad({ attempt, out: { err: e instanceof Error ? e.message : "request failed" } }));
    return () => {
      live = false;
    };
  }, [attempt]);

  if (!load || load.attempt !== attempt) {
    return (
      <p role="status" className="t-muted">
        Loading the evaluation results...
      </p>
    );
  }
  if ("err" in load.out) {
    return (
      <div role="alert">
        <p>The evaluation could not be loaded ({load.out.err}).</p>
        <button type="button" className="button" onClick={() => setAttempt((a) => a + 1)}>
          Try again
        </button>
      </div>
    );
  }
  const r = load.out.ok.available ? readEval(load.out.ok.results) : null;
  if (!r) {
    return (
      <div role="status" className="card">
        <h2 className="t-h3">Evaluation not run yet</h2>
        <p>The gate has no evaluation results to show. No numbers are displayed until a run has produced them.</p>
      </div>
    );
  }
  const ap = r.arms["actionproof"];
  return (
    <>
      <section aria-labelledby="ev-lead" className="ev-section">
        <h2 id="ev-lead" className="visually-hidden">
          Headline result
        </h2>
        <Headline r={r} />
      </section>

      <section aria-labelledby="ev-targets" className="ev-section">
        <h2 id="ev-targets" className="t-h3">
          Three targets
        </h2>
        <TargetStrip r={r} />
      </section>

      <section aria-labelledby="ev-caps" className="ev-section">
        <h2 id="ev-caps" className="t-h3">
          What each approach checks
        </h2>
        <Comparison r={r} />
      </section>

      <section aria-labelledby="ev-honest" className="ev-section">
        <h2 id="ev-honest" className="t-h3">
          Read this before trusting it
        </h2>
        <ul className="ev-honest">
          <li>The second handwritten set is NOT independent.</li>
          <li>The independent generator is absent, so the generated set did not run.</li>
          <li>The CaMeL-style row is a typical design, not measured.</li>
        </ul>
      </section>

      <section aria-label="Details" className="ev-section ev-details">
        <details>
          <summary>Attack classes, by set</summary>
          <p className="t-muted">Attacks that executed against ActionProof. Lower is better.</p>
          {ap && ap.status === "ok" ? <ClassTable ap={ap} /> : <p>The ActionProof arm did not run.</p>}
        </details>
        <details>
          <summary>Every approach on the same cases, with latency</summary>
          <ArmTable r={r} />
        </details>
        <details>
          <summary>How to read this, and which commit produced it</summary>
          <p>{FRAMING}</p>
          <MonoLabel as="p" muted>
            {r.commit ? `commit ${r.commit.sha.slice(0, 12)}${r.commit.dirty ? " (working tree had uncommitted changes)" : ""}` : "commit not recorded"}
            {r.generated_at ? `, run ${utc(r.generated_at)}` : ""}
          </MonoLabel>
        </details>
      </section>
    </>
  );
}
