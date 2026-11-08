"use client";
import type { Schemas } from "@/lib/api";
import { parseSource } from "@/lib/console-format";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal } from "@/components/ui/Signal";

type Claim = Schemas["ClaimView"];

function Where({ c }: { c: Claim }) {
  if (c.derivation) {
    return (
      <MonoLabel>
        derived: {c.derivation.fn as string}({(c.derivation.inputs as string[] | undefined)?.join(", ")})
      </MonoLabel>
    );
  }
  const s = parseSource(c.source);
  if (!s.doc) return <MonoLabel muted>no source cited</MonoLabel>;
  if (s.pointer !== undefined) {
    return (
      <MonoLabel>
        {s.doc} · pointer {s.pointer}
      </MonoLabel>
    );
  }
  return (
    <MonoLabel>
      {s.doc} · page {s.page} · bbox [{s.bbox?.join(", ")}]
    </MonoLabel>
  );
}

function Verification({ v }: { v: Claim["verification"] }) {
  if (!v) return <MonoLabel muted>not verified (no result recorded)</MonoLabel>;
  if (v.ok) return <Signal state="ALLOW" label={`verified${v.method ? ` · ${v.method}` : ""}`} />;
  return (
    <span className="c-verfail">
      <Signal state="DENY" label={v.reason ? `${v.reason.rule} · ${v.reason.guarantee}` : "failed"} />
      {v.method ? <MonoLabel muted>method {v.method}</MonoLabel> : null}
      {v.reason ? <span>{v.reason.msg}</span> : null}
    </span>
  );
}

function Row({ c, active, onActive }: { c: Claim; active: boolean; onActive: (n: string | null) => void }) {
  const untrusted = !c.evidence || c.taint;
  return (
    <li
      className="c-claim"
      data-active={active}
      tabIndex={0}
      aria-label={`Argument ${c.name}, ${c.claim}`}
      onMouseEnter={() => onActive(c.name)}
      onMouseLeave={() => onActive(null)}
      onFocus={() => onActive(c.name)}
      onBlur={() => onActive(null)}
    >
      <div className="c-claimhead">
        <MonoLabel>{c.name}</MonoLabel>
        <span className="c-badge mono-label" data-claim={c.claim}>
          {c.claim}
        </span>
        {c.taint ? <span className="c-badge mono-label" data-claim="TAINT">tainted: {c.taint}</span> : null}
      </div>
      <p className={untrusted ? "c-value c-untrusted" : "c-value"}>
        <span className="mono-label">{c.value}</span>
        {untrusted ? <span className="mono-label c-notev"> · not evidence</span> : null}
      </p>
      <Where c={c} />
      <Verification v={c.verification} />
    </li>
  );
}

export function Claims({ claims, active, onActive }: { claims: Claim[]; active: string | null; onActive: (n: string | null) => void }) {
  return (
    <ul className="c-claims">
      {claims.map((c) => (
        <Row key={c.name} c={c} active={active === c.name} onActive={onActive} />
      ))}
    </ul>
  );
}
