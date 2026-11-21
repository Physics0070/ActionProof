"use client";
// What the reviewer is authorizing, and what already happened to it. Every line is a field of the request detail the
// backend returned (tool, record, actor, on_behalf_of, dry-run diff, before-state, decision times); nothing is derived
// from anything else and nothing is invented. A field that is absent is shown as absent.
import type { Schemas } from "@/lib/api";
import { formatUtc } from "@/lib/console-format";
import { moneyStr } from "@/lib/site-data";
import { MonoLabel } from "@/components/ui/MonoLabel";

type Detail = Schemas["RequestDetail"];

const TOOL_LABEL: Record<string, string> = {
  "payments.approve_invoice": "Approve an invoice for payment",
  "payments.refund_payment": "Refund a payment",
};

const show = (v: unknown): string => {
  if (typeof v === "string") return moneyStr(v) ?? v;
  if (v === null || v === undefined) return "not recorded";
  return JSON.stringify(v);
};

/** "open->approved" -> ["open", "approved"]; anything else -> null. */
function transition(v: unknown): [string, string] | null {
  if (typeof v !== "string") return null;
  const [a, b, ...rest] = v.split("->");
  return a && b && rest.length === 0 ? [a, b] : null;
}

export function ApprovalPanel({ d }: { d: Detail }) {
  const diff = d.diff ?? {};
  const t = transition(diff["status"]);
  const rows = Object.entries(diff).filter(([k]) => k !== "status" && k !== "record_id");
  const beforeData = d.before && typeof d.before["data"] === "object" && d.before["data"] !== null ? (d.before["data"] as Record<string, unknown>) : null;
  const version = d.before ? d.before["version"] : undefined;
  return (
    <section className="a-panel" aria-labelledby="approving-h">
      <h2 className="t-h3" id="approving-h">
        Exactly what you are approving
      </h2>
      <dl className="a-grid">
        <div>
          <dt>Action</dt>
          <dd>{TOOL_LABEL[d.tool] ?? d.tool}</dd>
        </div>
        <div>
          <dt>Target</dt>
          <dd className="mono-label">{d.record_id}</dd>
        </div>
        <div>
          <dt>Requested by</dt>
          <dd>
            {d.actor} <span className="t-muted">for {d.on_behalf_of}</span>
          </dd>
        </div>
        {t ? (
          <div>
            <dt>Change</dt>
            <dd className="a-change">
              <span>{t[0]}</span>
              <span aria-label="becomes">→</span>
              <strong>{t[1]}</strong>
            </dd>
          </div>
        ) : null}
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k.replace(/_/g, " ")}</dt>
            <dd className="mono-label">{show(v)}</dd>
          </div>
        ))}
        {beforeData ? (
          <div>
            <dt>Record now</dt>
            <dd className="mono-label">
              {Object.entries(beforeData)
                .filter(([, v]) => typeof v === "string" || typeof v === "number")
                .map(([k, v]) => `${k}: ${show(v)}`)
                .join(" · ")}
              {version !== undefined ? ` · version ${show(version)}` : ""}
            </dd>
          </div>
        ) : null}
      </dl>
      {d.diff ? <p className="t-muted a-note">This is the gate&apos;s dry-run of the write. Approving runs exactly this once, and only if the record has not changed since.</p> : <p className="t-muted a-note">No dry-run is stored for this request, so the change cannot be previewed here.</p>}
    </section>
  );
}

export function History({ d }: { d: Detail }) {
  const decided = d.status !== "pending";
  const events: { at: number | null; text: string }[] = [
    { at: d.created_at, text: `${d.actor} asked for it on behalf of ${d.on_behalf_of}` },
    { at: d.created_at, text: d.policy_reasons.length ? `Paused for review: ${d.policy_reasons.map((r) => `${r.rule} / ${r.guarantee}`).join(", ")}` : "Paused for review" },
  ];
  if (decided) {
    events.push({
      at: d.decided_at,
      text: d.reviewer ? `${d.reviewer} ${d.status === "rejected" ? "rejected" : "approved"} it; status ${d.status}` : `Closed with status ${d.status}`,
    });
  }
  return (
    <section className="a-panel" aria-labelledby="history-h">
      <h2 className="t-h3" id="history-h">
        History
      </h2>
      <ol className="a-history">
        {events.map((e, i) => (
          <li key={i}>
            <MonoLabel muted>{e.at ? formatUtc(e.at) : "time not recorded"}</MonoLabel>
            <span>{e.text}</span>
          </li>
        ))}
        {!decided ? (
          <li data-open="true">
            <MonoLabel muted>now</MonoLabel>
            <span>Waiting for a reviewer who is a different person from the requester</span>
          </li>
        ) : null}
      </ol>
      <p className="t-muted a-note">The request detail the console API returns has no reviewer comments, so none are listed here.</p>
    </section>
  );
}
