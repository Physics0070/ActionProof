// Server component: the six beats as real, readable sections (no hydration cost). In the live experience they scroll over the fixed 3D scene; without WebGL
// or with reduced motion they are the same sections on a plain ground. Every figure comes from the recorded decision
// (GET /api/public/replay/inv-2048); with none recorded each beat says so and shows nothing in its place.
import Link from "next/link";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal, type Decision } from "@/components/ui/Signal";
import { BEATS } from "@/lib/assay";
import { REPO_URL } from "@/lib/config";
import { CLAIMS, OUTCOMES, TAINT } from "@/lib/site-copy";
import { invoiceFacts, money, moneyStr, utc, type Replay } from "@/lib/site-data";
import { Glyph } from "./Glyphs";
import { Recompute } from "./Recompute";

const asDecision = (s: string): Decision | null => (s === "ALLOW" || s === "REVIEW" || s === "DENY" ? s : null);

type Data = { data: Replay | null; note: string | null };
// The server fetched the recorded decision while rendering (app/(site)/page.tsx); null means it was unavailable.
const dataOf = (replay: Replay | null): Data =>
  replay ? { data: replay, note: null } : { data: null, note: "The recorded INV-2048 decision is not available right now, so nothing is shown here. Nothing is simulated in its place." };

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

function Problem({ data, note }: Data) {
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

function Evidence({ data, note }: Data) {
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
      {data ? <Recompute claims={data.claims} /> : null}
      {note ? <p className="beat-note">{note}</p> : null}
    </Frame>
  );
}

function Policy({ data, note }: Data) {
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

function Strike({ data, note }: Data) {
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
        If the process dies after the tool ran, the gate keeps the reservation, the idempotency key and the record&apos;s quarantine until it is reconciled. An outbox worker can resolve it only from a signed provider lookup, and it never sends the call again.
      </p>
      {note ? <p className="beat-note">{note}</p> : null}
    </Frame>
  );
}

function Audit({ data, note }: Data) {
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

export function Beats({ replay }: { replay: Replay | null }) {
  const d = dataOf(replay);
  return (
    <div id="assay-track" data-chapter="1">
      <Problem {...d} />
      <Evidence {...d} />
      <Policy {...d} />
      <Strike {...d} />
      <Audit {...d} />
      <Reveal />
    </div>
  );
}
