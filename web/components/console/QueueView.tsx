"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, type FormEvent, type KeyboardEvent } from "react";
import { apiGet, type Schemas } from "@/lib/api";
import { canRead, useAuth } from "@/lib/console-auth";
import { useAsync } from "@/lib/console-async";
import { formatAge, formatUtc, guaranteeOf, headline, STATUS_OPTIONS, TOOL_OPTIONS, toDecision } from "@/lib/console-format";
import { useNow } from "@/lib/console-now";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal } from "@/components/ui/Signal";
import { Empty, ErrorState, Loading, PermissionDenied } from "./Parts";

type Item = Schemas["QueueItem"];
const pick = <T extends string>(v: string | null, options: readonly T[]): T | undefined => options.find((o) => o === v);

function QueueCard({ item, now }: { item: Item; now: number | null }) {
  const state = toDecision(item.status);
  const g = guaranteeOf(item.reasons, item.top_rule);
  const text = headline(item.tool, item.amount);
  const pending = item.status === "pending";
  return (
    <li className="q-card" data-status={item.status}>
      <div className="q-main">
        <h2 className="q-head">{text}</h2>
        {item.reasons[0] ? (
          <p className="q-why" title={item.top_rule ? `${item.top_rule}${g ? ` · ${g}` : ""}` : undefined}>
            {item.reasons[0].msg}
          </p>
        ) : null}
        <p className="q-meta mono-label">
          Asked by {item.actor} for {item.on_behalf_of} ·{" "}
          <time dateTime={new Date(item.created_at * 1000).toISOString()} title={formatUtc(item.created_at)}>
            {formatAge(item.created_at, now)} ago
          </time>
        </p>
      </div>
      <div className="q-side">
        {state ? <Signal state={state} label={item.status === state ? undefined : item.status} /> : <MonoLabel>{item.status}</MonoLabel>}
        <Link href={`/console/requests/${item.request_hash}`} data-row title={item.request_hash} className={pending ? "button button-primary" : "button"} aria-label={`${pending ? "Review" : "Open"}: ${text}`}>
          {pending ? "Review" : "Open"}
        </Link>
      </div>
    </li>
  );
}

/** Arrow keys move between the request links of the rows; Enter follows the focused link. */
function rowKeys(e: KeyboardEvent<HTMLUListElement>) {
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
        Review requests
      </h1>
      <details className="q-filters" open={Boolean(status || tool || actor)}>
        <summary>Filter{status || tool || actor ? " (on)" : ""}</summary>
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
      </details>

      <div aria-busy={loading} className={loading && data ? "c-dim" : undefined}>
        {error ? <ErrorState error={error} onRetry={reload} /> : null}
        {!data && !error ? <Loading what="queue" /> : null}
        {data && data.items.length === 0 ? (
          <Empty title="No requests match">Nothing is {status ?? "queued"} for these filters. Clear a filter or check back later.</Empty>
        ) : null}
        {data && data.items.length > 0 ? (
          <ul className="q-list" aria-label="Review requests, newest first. Use the arrow keys to move between them." onKeyDown={rowKeys}>
            {data.items.map((it) => (
              <QueueCard key={it.request_hash} item={it} now={now} />
            ))}
          </ul>
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
