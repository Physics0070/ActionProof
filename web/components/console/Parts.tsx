import type { ReactNode } from "react";
import type { ApiError, Schemas } from "@/lib/api";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal } from "@/components/ui/Signal";
import type { Decision } from "@/components/ui/Signal";

export function Loading({ what }: { what: string }) {
  return (
    <div className="c-state" role="status" aria-busy="true">
      <MonoLabel muted>Loading {what}…</MonoLabel>
      <div className="c-skeleton" aria-hidden="true" />
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className="c-state" role="alert">
      <Signal state="DENY" label={error.code} />
      <p>{error.message}</p>
      {onRetry ? (
        <button type="button" className="button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="c-state" role="status">
      <h2 className="t-h3">{title}</h2>
      {children ? <p className="t-muted">{children}</p> : null}
    </div>
  );
}

export function PermissionDenied({ roles, need }: { roles: string[]; need: string }) {
  return (
    <div className="c-state" role="alert">
      <Signal state="DENY" label="forbidden" />
      <h2 className="t-h3">Your role cannot do this</h2>
      <p>
        You are signed in with {roles.length ? `role ${roles.join(", ")}` : "no roles"}. {need}
      </p>
    </div>
  );
}

/** Rule id + guarantee, the form every DENY / REVIEW reason takes (README.md working rules). */
export function ReasonList({ reasons, state }: { reasons: Schemas["ReasonOut"][]; state: Decision }) {
  if (!reasons.length) return <p className="t-muted">No reasons recorded.</p>;
  return (
    <ul className="c-reasons">
      {reasons.map((r, i) => (
        <li key={`${r.rule}-${i}`}>
          <Signal state={state} label={`${r.rule} · ${r.guarantee}`} />
          <span>{r.msg}</span>
        </li>
      ))}
    </ul>
  );
}

function scalar(v: unknown): string | null {
  if (v === null || v === undefined) return "null";
  return typeof v === "object" ? null : String(v);
}

/** Key/value view of an API dict (diff, before-state). Nested values show as JSON. */
export function Dict({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value);
  if (!entries.length) return <p className="t-muted">Empty.</p>;
  return (
    <dl className="c-dict">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt className="mono-label">{k}</dt>
          <dd className="mono-label">{scalar(v) ?? <pre>{JSON.stringify(v, null, 2)}</pre>}</dd>
        </div>
      ))}
    </dl>
  );
}
