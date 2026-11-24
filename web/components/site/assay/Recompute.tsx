"use client";
// The one part of the beats that runs in the visitor's browser: DERIVED values are recomputed here from the recorded
// operands, so "it matches" is checked on this machine, not asserted by the server.
import { derivations, moneyStr, type Replay } from "@/lib/site-data";

export function Recompute({ claims }: { claims: Replay["claims"] }) {
  return (
    <>
      {derivations(claims).map((d) => (
        <p key={d.claim.name} className="beat-note">
          {d.claim.name}: {d.operands.map((o) => moneyStr(o.value) ?? "?").join(d.fn === "sub" ? " − " : " + ")}
          {d.recomputed ? ` = ${d.recomputed}` : ""}. {d.matches === null ? "" : d.matches ? "Recomputed in your browser: it matches." : "Recomputed in your browser: it does not match."}
        </p>
      ))}
    </>
  );
}
