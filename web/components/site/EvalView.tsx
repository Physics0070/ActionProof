"use client";
// /evaluation: everything here is read from GET /api/public/eval (eval/results.json). No result is typed in source;
// when the payload says available:false the page says so and shows nothing in its place.
import { useEffect, useState } from "react";
import { apiGet, type Schemas } from "@/lib/api";
import { CLASSES, FRAMING, SETS, TABLE_COLS, TABLE_ROWS } from "@/lib/site-copy";
import { ms, pct, readEval, utc, type Arm, type EvalResults, type SetCount } from "@/lib/site-data";
import { MonoLabel } from "@/components/ui/MonoLabel";

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

function Status({ state }: { state: "met" | "missed" | "unmeasured" }) {
  const text = state === "met" ? "Met" : state === "missed" ? "Missed" : "Not measured";
  return <strong className="status" data-status={state}>{text}</strong>;
}

function Lead({ r }: { r: EvalResults }) {
  const ap = r.arms["actionproof"];
  const ng = r.arms["no_gate"];
  if (!ap || ap.status !== "ok" || !ap.attacks) {
    return <p role="status">The ActionProof arm did not run in this evaluation, so there is no headline result to show.</p>;
  }
  const hw = ap.attacks.by_set.handwritten;
  return (
    <div className="lead-grid">
      <div>
        <p className="t-kinetic lead-num" aria-label={`${ap.attacks.total.success} of ${ap.attacks.total.n} attacks executed`}>
          {ap.attacks.total.success}
          <span className="lead-of"> of {ap.attacks.total.n}</span>
        </p>
        <p className="t-lede">
          attacks executed against ActionProof
          {ng?.attacks ? <>, against {ng.attacks.total.success} of {ng.attacks.total.n} with no gate</> : null}. Handwritten set: {hw.success} of {hw.n}.
        </p>
      </div>
      <ul className="plain-list lead-side">
        {ap.benign ? (
          <li>
            <MonoLabel muted>False blocks on benign cases</MonoLabel>
            <br />
            {ap.benign.false_blocks} of {ap.benign.n} ({pct(ap.benign.false_blocks, ap.benign.n)})
          </li>
        ) : null}
        {ap.latency_ms ? (
          <li>
            <MonoLabel muted>Added latency, p95</MonoLabel>
            <br />
            {ms(ap.latency_ms.added_p95)}
          </li>
        ) : null}
        <li>
          <MonoLabel muted>Targets</MonoLabel>
          <br />
          {r.targets_met?.all ? "all met" : "not all met, see below"}
        </li>
      </ul>
    </div>
  );
}

function CapabilityTable({ r }: { r: EvalResults }) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <caption className="visually-hidden">Capabilities of each approach, measured by probes in the evaluation</caption>
        <thead>
          <tr>
            <th scope="col">Approach</th>
            {TABLE_COLS.map((c) => (
              <th key={c.key} scope="col">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {TABLE_ROWS.map((row) => {
            const caps = row.measured ? r.capabilities[row.key] : undefined;
            return (
              <tr key={row.key} data-self={row.key === "actionproof"}>
                <th scope="row">
                  {row.label}
                  {!row.measured ? (
                    <>
                      <br />
                      <MonoLabel muted>typical design, not measured</MonoLabel>
                    </>
                  ) : null}
                </th>
                {TABLE_COLS.map((c) => (
                  <td key={c.key}>{caps ? (caps[c.key] ?? "n/a") : <span className="t-muted">n/a</span>}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
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

function Targets({ r }: { r: EvalResults }) {
  const t = r.targets;
  const m = r.targets_met;
  const ap = r.arms["actionproof"];
  if (!t || !m) return <p className="t-muted">This evaluation did not record targets.</p>;
  const heldN = m.held_out_n ?? 0;
  const held: "met" | "missed" | "unmeasured" =
    heldN > 0 && m.held_out_successes != null ? (m.held_out_successes <= t.held_out_successes_max ? "met" : "missed") : "unmeasured";
  const fb = m.false_block_rate == null ? "unmeasured" : m.false_block_rate ? "met" : "missed";
  const lat = m.added_p95_ms == null ? "unmeasured" : m.added_p95_ms ? "met" : "missed";
  return (
    <>
      <p className="t-muted">Proposed targets, not results. Each is checked against what this run measured.</p>
      <div className="table-wrap">
        <table className="data-table">
          <caption className="visually-hidden">Targets against measured values</caption>
          <thead>
            <tr>
              <th scope="col">Target</th>
              <th scope="col">Measured</th>
              <th scope="col">Result</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">{t.held_out_successes_max} successful attacks on the held-out set</th>
              <td>
                {held === "unmeasured"
                  ? `not measured: the held-out set (${m.held_out_set ?? "unnamed"}) has ${heldN} cases`
                  : `${m.held_out_successes} successful of ${heldN}`}
              </td>
              <td>
                <Status state={held} />
              </td>
            </tr>
            <tr>
              <th scope="row">At most {Math.round(t.false_block_rate_max * 1000) / 10}% false blocks</th>
              <td>{ap?.benign ? `${pct(ap.benign.false_blocks, ap.benign.n)} (${ap.benign.false_blocks} of ${ap.benign.n})` : "n/a"}</td>
              <td>
                <Status state={fb} />
              </td>
            </tr>
            <tr>
              <th scope="row">p95 under {t.added_p95_ms_max} ms added</th>
              <td>{ap?.latency_ms ? ms(ap.latency_ms.added_p95) : "n/a"}</td>
              <td>
                <Status state={lat} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </>
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
        <h2 id="ev-lead" className="t-h2">
          Proof before permission, measured
        </h2>
        <Lead r={r} />
        <MonoLabel as="p" muted>
          {r.commit ? `commit ${r.commit.sha.slice(0, 12)}${r.commit.dirty ? " (working tree had uncommitted changes)" : ""}` : "commit not recorded"}
          {r.generated_at ? `, run ${utc(r.generated_at)}` : ""}
        </MonoLabel>
      </section>

      <section aria-labelledby="ev-caps" className="ev-section">
        <h2 id="ev-caps" className="t-h2">
          What each approach checks
        </h2>
        <p className="t-muted">Filled from capabilities the evaluation measured. The CaMeL-style row is a typical design and was not run.</p>
        <CapabilityTable r={r} />
      </section>

      <section aria-labelledby="ev-attacks" className="ev-section">
        <h2 id="ev-attacks" className="t-h2">
          Seven attack classes
        </h2>
        <p className="t-muted">Attacks that executed against ActionProof, by class and set. Lower is better. The second handwritten set is NOT independent.</p>
        {ap && ap.status === "ok" ? <ClassTable ap={ap} /> : <p>The ActionProof arm did not run.</p>}
        <h3 className="t-h3">Every approach, same cases</h3>
        <ArmTable r={r} />
      </section>

      <section aria-labelledby="ev-targets" className="ev-section">
        <h2 id="ev-targets" className="t-h2">
          Targets against actuals
        </h2>
        <Targets r={r} />
      </section>

      <section aria-labelledby="ev-honest" className="ev-section">
        <h2 id="ev-honest" className="t-h3">
          How to read this
        </h2>
        <p>{FRAMING}</p>
      </section>
    </>
  );
}
