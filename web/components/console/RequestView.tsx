"use client";
import Link from "next/link";
import { useCallback, useState } from "react";
import { ApiError, apiGet } from "@/lib/api";
import { canDecide, canRead, useAuth } from "@/lib/console-auth";
import { useAsync } from "@/lib/console-async";
import { formatUtc, HASH_RE, toDecision } from "@/lib/console-format";
import { Card } from "@/components/ui/Card";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal } from "@/components/ui/Signal";
import { Claims } from "./Claims";
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

  return (
    <article aria-labelledby="req-h">
      <p>
        <Link href="/console">← Queue</Link>
      </p>
      <h1 className="t-h3" id="req-h">
        {d.tool} <MonoLabel muted>{d.record_id}</MonoLabel>
      </h1>
      <p className="c-label">{label}</p>
      <p className="c-meta">
        {status ? <Signal state={status} label={d.status} /> : <MonoLabel>{d.status}</MonoLabel>}
        <MonoLabel muted>{formatUtc(d.created_at)}</MonoLabel>
        {d.decided_at ? <MonoLabel muted>decided {formatUtc(d.decided_at)}</MonoLabel> : null}
      </p>
      <p>
        <MonoLabel muted>request hash</MonoLabel> <span className="mono-label c-wrap">{d.request_hash}</span>
      </p>

      <div className="c-split">
        <div>
          <h2 className="t-h3">Authority arguments</h2>
          <p className="t-muted">Hover or focus an argument to find its source span on the page.</p>
          <Claims claims={d.claims} active={active} onActive={setActive} />
        </div>
        <div>
          <h2 className="t-h3">Source pages</h2>
          <SourcePages hash={d.request_hash} claims={d.claims} active={active} onActive={setActive} />
        </div>
      </div>

      <section aria-labelledby="why-h" className="c-section">
        <h2 className="t-h3" id="why-h">
          Why it paused
        </h2>
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
      </section>

      <div className="c-split c-section">
        <section aria-labelledby="diff-h">
          <h2 className="t-h3" id="diff-h">
            Dry-run diff
          </h2>
          {d.diff ? <Dict value={d.diff} /> : <p className="t-muted">No dry-run diff stored.</p>}
        </section>
        <section aria-labelledby="before-h">
          <h2 className="t-h3" id="before-h">
            Record before
          </h2>
          {d.before ? <Dict value={d.before} /> : <p className="t-muted">No before-state stored.</p>}
        </section>
      </div>

      {d.card ? (
        <section aria-labelledby="card-h" className="c-section">
          <h2 className="t-h3" id="card-h">
            Card
          </h2>
          <Card>
            <pre className="c-card mono-label" tabIndex={0} aria-label="Intercept card text">
              {d.card}
            </pre>
          </Card>
        </section>
      ) : null}

      <div className="c-section">
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
        {decided && !submitted ? (
          <p role="status">
            <MonoLabel>This request is {d.status}; no further decision can be made.</MonoLabel>
          </p>
        ) : null}
      </div>
      {error ? <ErrorState error={error} onRetry={reload} /> : null}
    </article>
  );
}
