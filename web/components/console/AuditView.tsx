"use client";
import Link from "next/link";
import { useCallback, useState } from "react";
import { ApiError, apiGet, type Schemas } from "@/lib/api";
import { canRead, useAuth } from "@/lib/console-auth";
import { useAsync } from "@/lib/console-async";
import { formatUtc, shortHash, toDecision } from "@/lib/console-format";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal } from "@/components/ui/Signal";
import { Dict, Empty, ErrorState, Loading, PermissionDenied } from "./Parts";

type Verify = Schemas["AuditVerify"];
type Check = { step: "idle" } | { step: "running" } | { step: "done"; v: Verify } | { step: "failed"; error: ApiError };

function VerifyChain({ onResult }: { onResult: (ok: boolean | null) => void }) {
  const [check, setCheck] = useState<Check>({ step: "idle" });
  async function run() {
    if (check.step === "running") return;
    setCheck({ step: "running" });
    onResult(null);
    try {
      const v = await apiGet("/api/audit/verify");
      setCheck({ step: "done", v });
      onResult(v.ok);
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


type Entry = Schemas["AuditEntry"];

/** The log as a chain: blocks in sequence order, each linked to the one before it. The link is the hash chain; it is only
 *  drawn as "verified" after the server's verifier says so. A gap in the sequence numbers of this page is marked, never hidden. */
function ChainStrip({ items, selected, onSelect, verified }: { items: Entry[]; selected: number | null; onSelect: (seq: number) => void; verified: boolean | null }) {
  const asc = [...items].sort((a, b) => a.seq - b.seq);
  return (
    <section className="x-chain" aria-labelledby="chain-h" data-verified={verified === null ? "unknown" : verified ? "yes" : "no"}>
      <h2 className="t-h3" id="chain-h">
        The chain
      </h2>
      <p className="t-muted x-note">
        {verified === true
          ? "The server re-computed every hash and signed checkpoint: the links below hold."
          : verified === false
            ? "The verifier reported a break. See the result above; the links below are not trustworthy."
            : "Each block is linked to the previous entry by its hash. Run Verify chain to have the server prove it."}
      </p>
      <ol className="x-strip">
        {asc.map((e, i) => {
          const prev = asc[i - 1];
          const dec = toDecision(e.decision);
          return (
            <li key={e.seq} className="x-cell">
              {prev ? (
                <span className="x-link" data-gap={e.seq - prev.seq > 1} aria-hidden="true" title={e.seq - prev.seq > 1 ? `entries ${prev.seq + 1} to ${e.seq - 1} are not in this page` : "linked by hash"} />
              ) : null}
              <button type="button" className="x-block" data-sel={selected === e.seq} data-dec={dec ?? "none"} aria-pressed={selected === e.seq} onClick={() => onSelect(e.seq)} aria-label={`Entry ${e.seq}, ${e.kind}${e.decision ? `, ${e.decision}` : ""}`}>
                <span className="x-seq">{e.seq}</span>
                <span className="mono-label">{e.kind}</span>
                <span className="mono-label x-hash">{shortHash(e.entry_hash)}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function EntryDetail({ e }: { e: Entry }) {
  const dec = toDecision(e.decision);
  return (
    <section className="x-detail" aria-labelledby="entry-h" aria-live="polite">
      <h2 className="t-h3" id="entry-h">
        Entry {e.seq}
      </h2>
      <p className="c-meta">
        {dec ? <Signal state={dec} label={e.decision === dec ? undefined : (e.decision ?? undefined)} /> : <MonoLabel>{e.decision ?? "no decision"}</MonoLabel>}
        <MonoLabel muted>{formatUtc(e.ts)}</MonoLabel>
        <MonoLabel>{e.kind}</MonoLabel>
      </p>
      {e.rules.length ? (
        <ul className="x-rules">
          {e.rules.map((r, i) => (
            <li key={i}>
              <MonoLabel>
                {r.rule} · {r.guarantee}
              </MonoLabel>{" "}
              {r.msg}
            </li>
          ))}
        </ul>
      ) : null}
      <dl className="x-facts">
        <div>
          <dt>entry hash</dt>
          <dd className="mono-label">{e.entry_hash}</dd>
        </div>
        {e.request_hash ? (
          <div>
            <dt>request</dt>
            <dd>
              <Link href={`/console/requests/${e.request_hash}`} className="mono-label">
                {e.request_hash}
              </Link>
            </dd>
          </div>
        ) : null}
        {e.record_id ? (
          <div>
            <dt>record</dt>
            <dd className="mono-label">{e.record_id}</dd>
          </div>
        ) : null}
        {e.actor ? (
          <div>
            <dt>actor</dt>
            <dd>
              {e.actor}
              {e.on_behalf_of ? ` for ${e.on_behalf_of}` : ""}
            </dd>
          </div>
        ) : null}
      </dl>
      {e.detail && Object.keys(e.detail).length ? <Dict value={e.detail} /> : null}
    </section>
  );
}

export function AuditView() {
  const [selected, setSelected] = useState<number | null>(null);
  const [verified, setVerified] = useState<boolean | null>(null);
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
      <VerifyChain onResult={setVerified} />
      {error ? <ErrorState error={error} onRetry={reload} /> : null}
      {!data && !error ? <Loading what="audit entries" /> : null}
      {data && data.items.length === 0 ? <Empty title="No audit entries yet" /> : null}
      {data && data.items.length > 0 ? (
        <>
          <ChainStrip items={data.items} selected={selected} onSelect={setSelected} verified={verified} />
          {data.items.find((e) => e.seq === selected) ? <EntryDetail e={data.items.find((e) => e.seq === selected)!} /> : null}
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
        </>
      ) : null}
    </section>
  );
}
