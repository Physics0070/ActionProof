"use client";
// The signature moment: a REAL recorded INV-2048 decision (GET /api/public/replay/inv-2048), shown in four steps:
//   1 claims as submitted, 2 G1 (the derived value re-checked BEFORE the gate moves), 3 the decision, 4 G2 (replay bounces).
// Nothing here is scripted: every value, rule id and reason is from the payload. All four steps are always in the DOM
// (readable without motion, in order for screen readers); the scroll step only decides which one is lit.
import { useStory } from "@/lib/site-story";
import { OPERATORS, derivations, isReplayBounce, moneyStr, utc, type Claim, type Reason, type Replay } from "@/lib/site-data";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal, type Decision } from "@/components/ui/Signal";

const DECISIONS: readonly string[] = ["ALLOW", "REVIEW", "DENY"];
const asDecision = (s: string): Decision | null => (DECISIONS.includes(s) ? (s as Decision) : null);

function Source({ c }: { c: Claim }) {
  const s = c.source;
  if (!s) return <span className="t-muted">none</span>;
  const parts = Object.entries(s).map(([k, v]) => `${k} ${Array.isArray(v) ? `[${v.join(", ")}]` : String(v)}`);
  return <span>{parts.join(", ")}</span>;
}

function Reasons({ reasons }: { reasons: Reason[] }) {
  return (
    <ul className="plain-list">
      {reasons.map((r, i) => (
        <li key={`${r.rule}-${i}`}>
          <MonoLabel>
            {r.rule} / {r.guarantee}
          </MonoLabel>{" "}
          {r.msg}
        </li>
      ))}
    </ul>
  );
}

function StepBox({ n, step, title, children }: { n: number; step: number; title: string; children: React.ReactNode }) {
  // step < 0: static / reduced motion, every step is lit. Otherwise steps light up cumulatively as the chapter scrolls.
  const on = step < 0 || step >= n - 1;
  return (
    <section className="proof-step" data-on={on} data-open={step < 0 || step === n - 1} aria-current={step === n - 1 ? "step" : undefined} aria-label={`Step ${n}: ${title}`}>
      <h4 className="proof-step-title">
        <MonoLabel muted>Step {n}</MonoLabel> {title}
      </h4>
      <div className="step-body">{children}</div>
    </section>
  );
}

export function ReplayBody({ data, step }: { data: Replay; step: number }) {
  const ders = derivations(data.claims);
  const decision = asDecision(data.decision);
  const bounces = data.outcome_reasons.filter(isReplayBounce);
  return (
    <div className="proof-grid">
      <MonoLabel as="p" muted>
        {data.record_id} / {data.tool} / {data.label}
      </MonoLabel>
      <MonoLabel as="p" muted>
        request {data.request_hash.slice(0, 16)}
      </MonoLabel>

      <StepBox n={1} step={step} title="Claims as submitted">
        <div className="table-wrap">
          <table className="data-table">
            <caption className="visually-hidden">Claims of the recorded INV-2048 request</caption>
            <thead>
              <tr>
                <th scope="col">Argument</th>
                <th scope="col">Claim</th>
                <th scope="col">Value</th>
                <th scope="col">Evidence</th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {data.claims.map((c) => (
                <tr key={c.name}>
                  <th scope="row">
                    <MonoLabel>{c.name}</MonoLabel>
                  </th>
                  <td>
                    <MonoLabel>{c.claim}</MonoLabel>
                    {c.taint ? <MonoLabel muted> (taint: {c.taint})</MonoLabel> : null}
                  </td>
                  <td>{moneyStr(c.value) ?? c.value}</td>
                  <td>{c.evidence ? "cited" : "none: model-only"}</td>
                  <td>
                    <Source c={c} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </StepBox>

      <StepBox n={2} step={step} title="G1: re-derive before the gate moves">
        {ders.length === 0 ? (
          <p className="t-muted">This request has no DERIVED value to re-check.</p>
        ) : (
          ders.map((d) => (
            <div key={d.claim.name} className="derive">
              <p className="derive-eq">
                <MonoLabel>{d.claim.name}</MonoLabel> ={" "}
                {d.operands.map((o, i) => (
                  <span key={o.name}>
                    {i > 0 ? ` ${OPERATORS[d.fn] ?? d.fn} ` : ""}
                    <MonoLabel>{o.name}</MonoLabel> ({moneyStr(o.value) ?? "from the system of record"})
                  </span>
                ))}
                {d.recomputed ? <strong> = {d.recomputed}</strong> : null}
              </p>
              <p>
                Claimed {moneyStr(d.claim.value) ?? d.claim.value}.{" "}
                {d.matches === null ? "Operands are not all in this record, so the page does not recompute." : d.matches ? "Recomputed here: it matches." : "Recomputed here: it does not match."}
              </p>
              {d.claim.verification ? (
                <p>
                  Gate check: {d.claim.verification.ok ? "passed" : "failed"} ({d.claim.verification.method ?? "no method"})
                  {d.claim.verification.reason ? ` ${d.claim.verification.reason.rule} / ${d.claim.verification.reason.guarantee}` : ""}.
                </p>
              ) : null}
            </div>
          ))
        )}
      </StepBox>

      <StepBox n={3} step={step} title="The gate decides">
        <p>
          {decision ? <Signal state={decision} solid /> : <MonoLabel>{data.decision}</MonoLabel>} <MonoLabel muted>status {data.status}</MonoLabel>
        </p>
        <Reasons reasons={data.reasons} />
        <MonoLabel as="p" muted>
          {data.reviewer ? `reviewer ${data.reviewer}` : "no reviewer yet"}
          {utc(data.decided_at) ? `, decided ${utc(data.decided_at)}` : ""}
          {data.audit.first_seq !== null ? `, audit entries ${data.audit.first_seq} to ${data.audit.last_seq}` : ""}
        </MonoLabel>
      </StepBox>

      <StepBox n={4} step={step} title="G2: a replayed receipt bounces">
        {bounces.length > 0 ? (
          <>
            <p>
              <Signal state="DENY" solid />
            </p>
            <Reasons reasons={bounces} />
          </>
        ) : (
          <p className="t-muted">No replay attempt is recorded against this request yet, so there is no bounce to show.</p>
        )}
      </StepBox>
    </div>
  );
}

export function ReplayProof({ live }: { live: boolean }) {
  const replay = useStory((s) => s.replay);
  const step = useStory((s) => s.step);
  const chapter = useStory((s) => s.chapter);
  const loadReplay = useStory((s) => s.loadReplay);
  // Static / reduced-motion: no scroll steps, show every step as active.
  const shown = live && chapter === 3 ? step : -1;

  if (replay.kind === "idle" || replay.kind === "loading") {
    return (
      <p role="status" className="t-muted">
        Fetching the recorded INV-2048 decision from the gate...
      </p>
    );
  }
  if (replay.kind === "none") {
    return (
      <p role="status">
        No recorded decision yet. The real INV-2048 decision appears here once the gate has produced one; nothing is simulated in its place.
      </p>
    );
  }
  if (replay.kind === "error") {
    return (
      <div role="alert">
        <p>The recorded decision could not be loaded ({replay.message}).</p>
        <button type="button" className="button" onClick={() => void loadReplay()}>
          Try again
        </button>
      </div>
    );
  }
  return <ReplayBody data={replay.data} step={shown} />;
}
