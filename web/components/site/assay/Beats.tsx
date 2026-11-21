"use client";
// The six beats as real, readable sections. In the live experience they scroll over the fixed 3D scene; without WebGL
// or with reduced motion they are the same sections on a plain ground. Every figure comes from the recorded decision
// (GET /api/public/replay/inv-2048); with none recorded each beat says so and shows nothing in its place.
import Link from "next/link";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal, type Decision } from "@/components/ui/Signal";
import { BEATS } from "@/lib/assay";
import { REPO_URL } from "@/lib/config";
import { CLAIMS, OUTCOMES, TAINT } from "@/lib/site-copy";
import { derivations, invoiceFacts, money, moneyStr, utc, type Replay } from "@/lib/site-data";
import { useStory } from "@/lib/site-story";
import { Glyph } from "./Glyphs";

const asDecision = (s: string): Decision | null => (s === "ALLOW" || s === "REVIEW" || s === "DENY" ? s : null);

function useData(): { data: Replay | null; note: string | null } {
  const replay = useStory((s) => s.replay);
  if (replay.kind === "ok") return { data: replay.data, note: null };
  if (replay.kind === "none") return { data: null, note: "No decision has been recorded yet, so nothing is shown here. Nothing is simulated in its place." };
  if (replay.kind === "error") return { data: null, note: `The recorded decision could not be loaded (${replay.message}).` };
  return { data: null, note: "Fetching the recorded INV-2048 decision from the gate." };
}

function Frame({ i, children }: { i: number; children: React.ReactNode }) {
  const b = BEATS[i]!;
  return (
    <section id={`beat-${b.id}`} className="beat" data-beat={b.id} aria-labelledby={`beat-${b.id}-h`}>
      <div className="beat-copy">
        <p className="beat-index" aria-hidden="true">
          {String(i + 1).padStart(2, "0")} / {String(BEATS.length).padStart(2, "0")} · {b.label}
        </p>
        <h2 id={`beat-${b.id}-h`} className="beat-title">
          {b.title}
        </h2>
        {children}
      </div>
      <Glyph id={b.id} />
    </section>
  );
}

function Problem() {
  const { data, note } = useData();
  const f = data ? invoiceFacts(data.claims) : null;
  return (
    <Frame i={0}>
      <p className="beat-lede">
        An agent asks to approve invoice INV-2048. A filter that reads the agent&apos;s reply sees nothing wrong, so the write could execute.
      </p>
      <dl className="slips">
        <div>
          <dt>Invoice says</dt>
          <dd>{f ? money(f.inv) : "..."}</dd>
        </div>
        <div>
          <dt>Purchase order says</dt>
          <dd>{f ? money(f.po) : "..."}</dd>
        </div>
        <div data-hot="true">
          <dt>Unexplained</dt>
          <dd>{f ? money(f.gap) : "..."}</dd>
        </div>
      </dl>
      {note ? <p className="beat-note">{note}</p> : null}
    </Frame>
  );
}

function Evidence() {
  const { data, note } = useData();
  const ders = data ? derivations(data.claims) : [];
  return (
    <Frame i={1}>
      <p className="beat-lede">The gate asks where each value came from. Only some kinds of claim may authorize a write.</p>
      <dl className="kinds">
        {CLAIMS.map((c) => (
          <div key={c.kind} data-kind={c.kind}>
            <dt>{c.kind}</dt>
            <dd>{c.body}</dd>
          </div>
        ))}
      </dl>
      <p className="beat-note">{TAINT}</p>
      {data ? (
        <table className="claim-table">
          <caption>The {data.claims.length} claims of the recorded INV-2048 request</caption>
          <thead>
            <tr>
              <th scope="col">Claim</th>
              <th scope="col">Kind</th>
              <th scope="col">Value</th>
              <th scope="col">Gate check</th>
            </tr>
          </thead>
          <tbody>
            {data.claims.map((c) => (
              <tr key={c.name}>
                <th scope="row">{c.name}</th>
                <td data-kind={c.claim}>{c.claim}</td>
                <td>{moneyStr(c.value) ?? c.value}</td>
                <td>{c.verification ? `${c.verification.ok ? "passed" : "failed"}${c.verification.method ? ` (${c.verification.method})` : ""}` : "not an evidence claim"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {ders.map((d) => (
        <p key={d.claim.name} className="beat-note">
          {d.claim.name}: {d.operands.map((o) => moneyStr(o.value) ?? "?").join(d.fn === "sub" ? " − " : " + ")}
          {d.recomputed ? ` = ${d.recomputed}` : ""}. {d.matches === null ? "" : d.matches ? "Recomputed in your browser: it matches." : "Recomputed in your browser: it does not match."}
        </p>
      ))}
      {note ? <p className="beat-note">{note}</p> : null}
    </Frame>
  );
}

function Policy() {
  const { data, note } = useData();
  const dec = data ? asDecision(data.decision) : null;
  return (
    <Frame i={2}>
      <p className="beat-lede">The verified request goes to OPA. It answers ALLOW, REVIEW or DENY, and every reason names its rule and the guarantee it protects.</p>
      {dec ? <Signal state={dec} solid /> : null}
      {data ? (
        <ul className="reasons">
          {data.reasons.map((r, k) => (
            <li key={k}>
              <MonoLabel>
                {r.rule} / {r.guarantee}
              </MonoLabel>
              <span>{r.msg}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="beat-note">{OUTCOMES}</p>
      {note ? <p className="beat-note">{note}</p> : null}
    </Frame>
  );
}

function Strike() {
  const { data, note } = useData();
  const fin = data ? asDecision(data.status === "executed" ? "ALLOW" : data.status === "rejected" ? "DENY" : data.decision) : null;
  const bounce = data?.replay_attempts[0];
  return (
    <Frame i={3}>
      <p className="beat-lede">The decision becomes a signed receipt that works once. Commit re-checks the record and the caps in one transaction, then calls the tool once.</p>
      {data ? (
        <p className="beat-fact">
          {fin ? <Signal state={fin} solid label={data.status} /> : <MonoLabel>{data.status}</MonoLabel>}{" "}
          <span className="mono">{data.reviewer ? `reviewer ${data.reviewer}` : "no reviewer yet"}{utc(data.decided_at) ? ` · ${utc(data.decided_at)}` : ""}</span>
        </p>
      ) : null}
      {bounce ? (
        <p className="beat-fact beat-bounce">
          <Signal state="DENY" solid label="replayed receipt" />{" "}
          <span className="mono">
            {bounce.reasons.map((r) => `${r.rule} / ${r.guarantee}`).join(", ")} · audit entry {bounce.seq}
          </span>
        </p>
      ) : data ? (
        <p className="beat-note">No replay attempt is recorded against this request yet, so no bounce is drawn.</p>
      ) : null}
      <p className="beat-note">
        If the process dies after the tool ran, the gate keeps the reservation, the idempotency key and the record&apos;s quarantine until a person reconciles it. It does not retry by itself, and there is no outbox yet.
      </p>
      {note ? <p className="beat-note">{note}</p> : null}
    </Frame>
  );
}

function Audit() {
  const { data, note } = useData();
  const a = data?.audit;
  return (
    <Frame i={4}>
      <p className="beat-lede">
        Each decision is an entry in a hash-chained log. Checkpoints are signed, and the verifier needs only the database and a public key.
      </p>
      {data && a && a.first_seq !== null && a.last_seq !== null ? (
        <p className="beat-fact mono">
          INV-2048 left audit entries {a.first_seq} to {a.last_seq} · request {data.request_hash.slice(0, 16)}
        </p>
      ) : null}
      <p className="beat-note">A local anchor can reveal a deleted tail. A file on the same machine is not tamper-proof storage: copy it off the host.</p>
      {note ? <p className="beat-note">{note}</p> : null}
    </Frame>
  );
}

function Reveal() {
  return (
    <Frame i={5}>
      <p className="beat-lede">Open the review console to see the decision a person sees, or read how the gate was measured against four baselines.</p>
      <p className="cta-row">
        <Link className="button button-primary" href="/console">
          See a real decision
        </Link>
        <Link className="quiet-link" href="/evaluation">
          How it is measured
        </Link>
        {REPO_URL ? (
          <a className="quiet-link" href={REPO_URL} rel="noopener">
            Read the code
          </a>
        ) : null}
      </p>
    </Frame>
  );
}

export function Beats() {
  return (
    <div id="assay-track" data-chapter="1">
      <Problem />
      <Evidence />
      <Policy />
      <Strike />
      <Audit />
      <Reveal />
    </div>
  );
}
