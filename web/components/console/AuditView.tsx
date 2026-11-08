"use client";
import Link from "next/link";
import { useCallback, useState } from "react";
import { ApiError, apiGet, type Schemas } from "@/lib/api";
import { canRead, useAuth } from "@/lib/console-auth";
import { useAsync } from "@/lib/console-async";
import { formatUtc, shortHash, toDecision } from "@/lib/console-format";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal } from "@/components/ui/Signal";
import { Empty, ErrorState, Loading, PermissionDenied } from "./Parts";

type Verify = Schemas["AuditVerify"];
type Check = { step: "idle" } | { step: "running" } | { step: "done"; v: Verify } | { step: "failed"; error: ApiError };

function VerifyChain() {
  const [check, setCheck] = useState<Check>({ step: "idle" });
  async function run() {
    if (check.step === "running") return;
    setCheck({ step: "running" });
    try {
      setCheck({ step: "done", v: await apiGet("/api/audit/verify") });
    } catch (e) {
      setCheck({ step: "failed", error: e instanceof ApiError ? e : new ApiError(0, "network", "Cannot reach the console API.") });
    }
  }
  return (
    <div className="a-verify">
      <button type="button" className="button button-primary a-button" onClick={() => void run()} disabled={check.step === "running"}>
        {check.step === "running" ? "Verifying…" : "Verify chain"}
      </button>
      <div role="status" aria-live="polite" className="a-result">
        {check.step === "idle" ? <p className="t-muted">Re-computes every hash in the log and its signed checkpoints.</p> : null}
        {check.step === "done" && check.v.ok ? (
          <p>
            <Signal state="ALLOW" label="chain verified" /> {check.v.entries} entries and {check.v.checkpoints} checkpoints check out. Nothing was changed after it was written.
          </p>
        ) : null}
        {check.step === "done" && !check.v.ok ? (
          <p>
            <Signal state="DENY" label="chain broken" /> {check.v.error ?? "Verification failed."}
          </p>
        ) : null}
        {check.step === "failed" ? (
          <p role="alert">
            <Signal state="DENY" label={check.error.code} /> {check.error.message}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function AuditView() {
  const { state } = useAuth();
  const load = useCallback((signal: AbortSignal) => apiGet("/api/audit", { signal }), []);
  const { data, error, reload } = useAsync(load);

  if (state.status !== "in") return null;
  if (!canRead(state.user)) return <PermissionDenied roles={state.user.roles} need="The audit log is for the reviewer and admin roles." />;

  return (
    <section aria-labelledby="audit-h">
      <h1 className="t-h2" id="audit-h">
        Audit log
      </h1>
      <VerifyChain />
      {error ? <ErrorState error={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading what="audit entries" /> : null}
      {data && data.items.length === 0 ? <Empty title="No audit entries yet" /> : null}
      {data && data.items.length > 0 ? (
        <table className="c-table">
          <caption className="visually-hidden">Most recent audit entries, newest first</caption>
          <thead>
            <tr>
              {["Seq", "Time", "Kind", "Decision", "Rules", "Request", "Actor", "Entry hash"].map((h) => (
                <th key={h} scope="col" className="mono-label">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.items.map((e) => {
              const dec = toDecision(e.decision);
              return (
                <tr key={e.seq}>
                  <td data-label="Seq">
                    <MonoLabel>{e.seq}</MonoLabel>
                  </td>
                  <td data-label="Time">
                    <MonoLabel>{formatUtc(e.ts)}</MonoLabel>
                  </td>
                  <td data-label="Kind">
                    <MonoLabel>{e.kind}</MonoLabel>
                  </td>
                  <td data-label="Decision">{dec ? <Signal state={dec} label={e.decision === dec ? undefined : (e.decision ?? undefined)} /> : <MonoLabel>{e.decision ?? "-"}</MonoLabel>}</td>
                  <td data-label="Rules">
                    <MonoLabel>{e.rules.length ? e.rules.map((r) => `${r.rule} · ${r.guarantee}`).join(", ") : "-"}</MonoLabel>
                  </td>
                  <td data-label="Request">
                    {e.request_hash ? (
                      <Link href={`/console/requests/${e.request_hash}`} title={e.request_hash} className="mono-label">
                        {shortHash(e.request_hash)}
                      </Link>
                    ) : (
                      <MonoLabel>-</MonoLabel>
                    )}
                  </td>
                  <td data-label="Actor">
                    <MonoLabel>{e.actor ? `${e.actor}${e.on_behalf_of ? ` / ${e.on_behalf_of}` : ""}` : "-"}</MonoLabel>
                  </td>
                  <td data-label="Entry hash">
                    <span title={e.entry_hash}>
                      <MonoLabel>{shortHash(e.entry_hash)}</MonoLabel>
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
