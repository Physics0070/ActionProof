"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, type FormEvent, type KeyboardEvent } from "react";
import { apiGet, type Schemas } from "@/lib/api";
import { canRead, useAuth } from "@/lib/console-auth";
import { useAsync } from "@/lib/console-async";
import { formatAge, formatUtc, guaranteeOf, shortHash, STATUS_OPTIONS, TOOL_OPTIONS, toDecision } from "@/lib/console-format";
import { useNow } from "@/lib/console-now";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal } from "@/components/ui/Signal";
import { Empty, ErrorState, Loading, PermissionDenied } from "./Parts";

type Item = Schemas["QueueItem"];
const pick = <T extends string>(v: string | null, options: readonly T[]): T | undefined => options.find((o) => o === v);

function Row({ item, now }: { item: Item; now: number | null }) {
  const state = toDecision(item.status);
  const g = guaranteeOf(item.reasons, item.top_rule);
  return (
    <tr>
      <td data-label="Status">
        {state ? <Signal state={state} label={item.status} /> : <MonoLabel>{item.status}</MonoLabel>}
      </td>
      <td data-label="Request">
        <Link href={`/console/requests/${item.request_hash}`} data-row title={item.request_hash} className="mono-label">
          {shortHash(item.request_hash)}
        </Link>
      </td>
      <td data-label="Tool">
        <MonoLabel>{item.tool}</MonoLabel>
      </td>
      <td data-label="Requested by / for">
        <MonoLabel>
          {item.actor} / {item.on_behalf_of}
        </MonoLabel>
      </td>
      <td data-label="Amount">
        <MonoLabel>{item.amount ?? "-"}</MonoLabel>
      </td>
      <td data-label="Rule">
        <MonoLabel>{item.top_rule ? `${item.top_rule}${g ? ` · ${g}` : ""}` : "-"}</MonoLabel>
      </td>
      <td data-label="Age">
        <time dateTime={new Date(item.created_at * 1000).toISOString()} title={formatUtc(item.created_at)} className="mono-label">
          {formatAge(item.created_at, now)}
        </time>
      </td>
    </tr>
  );
}

/** Arrow keys move between the request links of the rows; Enter follows the focused link. */
function rowKeys(e: KeyboardEvent<HTMLTableSectionElement>) {
  const links = Array.from(e.currentTarget.querySelectorAll<HTMLAnchorElement>("a[data-row]"));
  const i = links.indexOf(document.activeElement as HTMLAnchorElement);
  if (i < 0) return;
  const to = e.key === "ArrowDown" ? i + 1 : e.key === "ArrowUp" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? links.length - 1 : null;
  if (to === null) return;
  e.preventDefault();
  links[Math.min(Math.max(to, 0), links.length - 1)]?.focus();
}

export function QueueView() {
  const { state } = useAuth();
  const sp = useSearchParams();
  const router = useRouter();
  const now = useNow();
  const status = pick(sp.get("status"), STATUS_OPTIONS);
  const tool = pick(sp.get("tool"), TOOL_OPTIONS);
  const actor = sp.get("actor") ?? "";
  const cursor = sp.get("cursor") ?? "";

  const load = useCallback(
    (signal: AbortSignal) =>
      apiGet("/api/queue", { query: { status, tool, actor: actor || undefined, cursor: cursor || undefined }, signal }),
    [status, tool, actor, cursor],
  );
  const { data, error, loading, reload } = useAsync(load);

  if (state.status !== "in") return null;
  if (!canRead(state.user)) {
    return <PermissionDenied roles={state.user.roles} need="The queue is for the reviewer and admin roles." />;
  }

  function apply(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const q = new URLSearchParams();
    for (const k of ["status", "tool", "actor"]) {
      const v = String(f.get(k) ?? "").trim();
      if (v) q.set(k, v);
    }
    router.push(q.size ? `/console?${q}` : "/console");
  }

  const next = data?.next_cursor;
  const nextHref = next ? `/console?${new URLSearchParams({ ...(status && { status }), ...(tool && { tool }), ...(actor && { actor }), cursor: next })}` : null;

  return (
    <section aria-labelledby="queue-h">
      <h1 className="t-h2" id="queue-h">
        Review queue
      </h1>
      <form className="c-filters" onSubmit={apply} key={sp.toString()} aria-label="Filter the queue">
        <div className="c-field">
          <label htmlFor="f-status">Status</label>
          <select id="f-status" name="status" defaultValue={status ?? ""}>
            <option value="">All</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="c-field">
          <label htmlFor="f-tool">Tool</label>
          <select id="f-tool" name="tool" defaultValue={tool ?? ""}>
            <option value="">All</option>
            {TOOL_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="c-field">
          <label htmlFor="f-actor">Actor</label>
          <input id="f-actor" name="actor" type="text" defaultValue={actor} autoComplete="off" spellCheck={false} maxLength={64} />
        </div>
        <button type="submit" className="button">
          Apply filters
        </button>
      </form>

      <div aria-busy={loading} className={loading && data ? "c-dim" : undefined}>
        {error ? <ErrorState error={error} onRetry={reload} /> : null}
        {!data && !error ? <Loading what="queue" /> : null}
        {data && data.items.length === 0 ? (
          <Empty title="No requests match">Nothing is {status ?? "queued"} for these filters. Clear a filter or check back later.</Empty>
        ) : null}
        {data && data.items.length > 0 ? (
          <table className="c-table">
            <caption className="visually-hidden">Review requests, newest first. Use the arrow keys to move between rows.</caption>
            <thead>
              <tr>
                {["Status", "Request", "Tool", "Requested by / for", "Amount", "Rule", "Age"].map((h) => (
                  <th key={h} scope="col" className="mono-label">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody onKeyDown={rowKeys}>
              {data.items.map((it) => (
                <Row key={it.request_hash} item={it} now={now} />
              ))}
            </tbody>
          </table>
        ) : null}
      </div>

      <nav className="c-pager" aria-label="Queue pages">
        {cursor ? (
          <Link className="button" href={`/console?${new URLSearchParams({ ...(status && { status }), ...(tool && { tool }), ...(actor && { actor }) })}`}>
            First page
          </Link>
        ) : null}
        {nextHref ? (
          <Link className="button" href={nextHref}>
            Older
          </Link>
        ) : null}
      </nav>
    </section>
  );
}
