// What the 3D scene draws, derived from the REAL recorded decision (GET /api/public/replay/inv-2048) when there is
// one. With no recorded decision the scene shows a neutral illustration and says so (`live: false`); it never
// invents a verdict, a denial or an audit range.
import type { Replay } from "@/lib/site-data";
import { decisionOf, type Decision } from "./common";

export type ClaimNode = { name: string; kind: "DIRECT" | "DERIVED" | "ASSERTED"; ok: boolean | null; inputs: string[] };

export type SceneModel = {
  /** True when every figure below comes from a fetched decision. False = illustration only. */
  live: boolean;
  claims: ClaimNode[];
  decision: Decision | null;
  requestHash: string;
  /** Audit entries of this request (the chain length drawn). */
  chain: number;
  /** Index of the entry that recorded the replay bounce, or -1. */
  denyIndex: number;
  /** A replay attempt is recorded against this request (the ghost bounces off the closed latch). */
  bounce: boolean;
};

const ILLUSTRATION: ClaimNode[] = [
  { name: "invoice.total", kind: "DIRECT", ok: null, inputs: [] },
  { name: "po.total", kind: "DIRECT", ok: null, inputs: [] },
  { name: "variance", kind: "DERIVED", ok: null, inputs: ["invoice.total", "po.total"] },
  { name: "note", kind: "ASSERTED", ok: null, inputs: [] },
];

export function modelFrom(data: Replay | null): SceneModel {
  if (!data) {
    return { live: false, claims: ILLUSTRATION, decision: null, requestHash: "a5e1c9d27b0f3846a5e1c9d27b0f3846a5e1c9d27b0f3846a5e1c9d27b0f3846", chain: 8, denyIndex: -1, bounce: false };
  }
  const claims: ClaimNode[] = data.claims.slice(0, 9).map((c) => {
    const raw = c.derivation?.["inputs"];
    return {
      name: c.name,
      kind: c.claim,
      ok: c.verification ? c.verification.ok : null,
      inputs: Array.isArray(raw) ? raw.map(String) : [],
    };
  });
  const { first_seq: a, last_seq: b } = data.audit;
  const chain = a !== null && b !== null ? Math.min(24, Math.max(1, b - a + 1)) : 0;
  const bounce = data.replay_attempts[0];
  return {
    live: true,
    claims,
    decision: decisionOf(data.decision),
    requestHash: data.request_hash,
    chain,
    denyIndex: bounce && a !== null ? Math.min(chain - 1, Math.max(0, bounce.seq - a)) : -1,
    bounce: bounce !== undefined,
  };
}
