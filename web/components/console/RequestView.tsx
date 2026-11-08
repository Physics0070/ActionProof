"use client";
import Link from "next/link";
import { useCallback, useState } from "react";
import { ApiError, apiGet } from "@/lib/api";
import { canDecide, canRead, useAuth } from "@/lib/console-auth";
import { useAsync } from "@/lib/console-async";
import { formatUtc, HASH_RE, headline, toDecision, whyPaused } from "@/lib/console-format";
import { Card } from "@/components/ui/Card";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal } from "@/components/ui/Signal";
import { Claims, KeyValues } from "./Claims";
import { DecisionForm } from "./DecisionForm";
import { Dict, ErrorState, Loading, PermissionDenied, ReasonList } from "./Parts";
import { SourcePages } from "./SourcePages";

const NOT_FOUND = new ApiError(404, "not_found", "No review exists for this request hash.");

export function RequestView({ hash }: { hash: string }) {
  const { state } = useAuth();
  const [active, setActive] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const valid = HASH_RE.test(hash);
  const load = useCallback(
    (signal: AbortSignal) => (valid ? apiGet("/api/requests/{request_hash}", { path: { request_hash: hash }, signal }) : Promise.reject(NOT_FOUND)),
    [hash, valid],
  );
  const { data: d, error, reload } = useAsync(load);

  if (state.status !== "in") return null;
  const user = state.user;
  if (!canRead(user)) return <PermissionDenied roles={user.roles} need="Request details are for the reviewer and admin roles." />;
  if (error && !d) return <ErrorState error={error} onRetry={error.status === 404 ? undefined : reload} />;
  if (!d) return <Loading what="request" />;

  const status = toDecision(d.status);
  const decided = d.status !== "pending";
  const verb = d.status === "rejected" ? "rejected" : "approved";
  const label =
    d.reviewer && decided && d.status !== "denied" ? `${d.label} · ${verb} by ${d.reviewer}${verb === "approved" ? " (different person)" : ""}` : d.label;
  const amount = d.claims.find((c) => c.name === "amount")?.value ?? d.claims.find((c) => c.name === "invoice.total")?.value;
  const title = headline(d.tool, amount, d.record_id);
  const cited = d.claims.filter((c) => c.claim !== "ASSERTED" && !c.taint);
  const checked = cited.filter((c) => c.verification?.ok).length;
  const notEvidence = d.claims.length - cited.length;

  return (
    <article aria-labelledby="req-h" className="r-page">
      <p>
        <Link href="/console" className="r-back">
          ← All requests
        </Link>
      </p>
      <h1 className="r-title" id="req-h">
        {title.split(/([A-Z]{2,}-\d+)/).map((part, i) => (i % 2 ? <span key={i} className="nobr">{part}</span> : part))}
      </h1>
      <p className="c-label">{label}</p>
      <p className="c-meta">
        {status ? <Signal state={status} label={d.status} /> : <MonoLabel>{d.status}</MonoLabel>}
        <MonoLabel muted>{formatUtc(d.created_at)}</MonoLabel>
        {d.decided_at ? <MonoLabel muted>decided {formatUtc(d.decided_at)}</MonoLabel> : null}
      </p>

      <section className="r-verdict" aria-label="Verdict">
        <p className="r-why">
          <strong>Why this paused:</strong> {whyPaused(d.claims, d.policy_reasons)}.
        </p>
        <p>
          Checked: {checked} of {cited.length} cited values re-verified against their sources.
          {notEvidence > 0 ? ` ${notEvidence} model-only or document-text ${notEvidence === 1 ? "value was" : "values were"} not counted as evidence.` : ""}
        </p>
        <p>{decided ? `This request is ${d.status}; no further decision can be made.` : "Approve runs the write once. Reject closes it without running anything."}</p>
      </section>

      <div className="c-split">
        <div>
          <h2 className="t-h3">Values that matter</h2>
          <KeyValues claims={d.claims} active={active} onActive={setActive} />
        </div>
        <div>
          <h2 className="t-h3">Source page</h2>
          <SourcePages hash={d.request_hash} claims={d.claims} active={active} onActive={setActive} />
        </div>
      </div>

      <div className="r-more">
        <details>
          <summary>Evidence: every argument and how it was checked</summary>
          <p className="t-muted">Hover or focus an argument to find its source span on the page.</p>
          <Claims claims={d.claims} active={active} onActive={setActive} />
        </details>
        <details>
          <summary>Policy reasons</summary>
          <ReasonList reasons={d.policy_reasons} state="REVIEW" />
          {d.outcome_reasons.length ? (
            <>
              <h3 className="mono-label">Latest outcome</h3>
              <ReasonList reasons={d.outcome_reasons} state="DENY" />
            </>
          ) : null}
          {d.taint_flags.length ? (
            <p>
              <MonoLabel>Tainted arguments: {d.taint_flags.join(", ")}. Document text is shown, never trusted.</MonoLabel>
            </p>
          ) : null}
        </details>
        <details>
          <summary>Technical details</summary>
          <p>
            <MonoLabel muted>request hash</MonoLabel> <span className="mono-label c-wrap">{d.request_hash}</span>
          </p>
          <div className="c-split">
            <section aria-labelledby="diff-h">
              <h2 className="mono-label" id="diff-h">
                Dry-run diff
              </h2>
              {d.diff ? <Dict value={d.diff} /> : <p className="t-muted">No dry-run diff stored.</p>}
            </section>
            <section aria-labelledby="before-h">
              <h2 className="mono-label" id="before-h">
                Record before
              </h2>
              {d.before ? <Dict value={d.before} /> : <p className="t-muted">No before-state stored.</p>}
            </section>
          </div>
          {d.card ? (
            <Card>
              <pre className="c-card mono-label" tabIndex={0} aria-label="Intercept card text">
                {d.card}
              </pre>
            </Card>
          ) : null}
        </details>
      </div>

      {(!decided || submitted) && canDecide(user) ? (
        <DecisionForm
          hash={d.request_hash}
          onDecided={() => {
            setSubmitted(true);
            reload();
          }}
        />
      ) : null}
      {!decided && !canDecide(user) ? <PermissionDenied roles={user.roles} need="Only the reviewer role can approve or reject; admin cannot decide." /> : null}
      {error ? <ErrorState error={error} onRetry={reload} /> : null}
    </article>
  );
}
