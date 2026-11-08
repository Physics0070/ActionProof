// Public-site data helpers. Everything numeric on the site comes from GET /api/public/eval and
// GET /api/public/replay/inv-2048 (CLAUDE.md invariant 7). Money is handled as integer cents parsed from 2dp
// decimal strings (invariant 4: no floats).
import type { Schemas } from "./api";

export type Replay = Schemas["PublicReplay"];
export type Claim = Schemas["ClaimView"];
export type Reason = Schemas["ReasonOut"];

const MONEY = /^-?\d+\.\d{2}$/;

/** "4800.00" -> 480000n; anything that is not a 2dp decimal string -> null. */
export function cents(s: string | null | undefined): bigint | null {
  if (s == null || !MONEY.test(s)) return null;
  const neg = s.startsWith("-");
  const [w = "0", f = "0"] = s.replace("-", "").split(".");
  const v = BigInt(w) * 100n + BigInt(f);
  return neg ? -v : v;
}

/** 480000n -> "$4,800.00" */
export function money(c: bigint): string {
  const neg = c < 0n;
  const a = neg ? -c : c;
  const whole = (a / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = (a % 100n).toString().padStart(2, "0");
  return `${neg ? "-" : ""}$${whole}.${frac}`;
}

export function moneyStr(s: string | null | undefined): string | null {
  const c = cents(s);
  return c === null ? null : money(c);
}

export function utc(epochSeconds: number | null | undefined): string | null {
  if (epochSeconds == null) return null;
  return `${new Date(epochSeconds * 1000).toISOString().replace("T", " ").slice(0, 19)} UTC`;
}

export type Operand = { name: string; value: string | null };
export type Derivation = {
  claim: Claim;
  fn: string;
  operands: Operand[];
  /** Recomputed in the browser from the resolved operands (display only; the gate's own check is `claim.verification`). */
  recomputed: string | null;
  matches: boolean | null;
};

/** Resolve each DERIVED claim's inputs against the other claims of the same request and recompute for display. */
export function derivations(claims: Claim[]): Derivation[] {
  const byName = new Map(claims.map((c) => [c.name, c]));
  const out: Derivation[] = [];
  for (const claim of claims) {
    if (claim.claim !== "DERIVED" || !claim.derivation) continue;
    const fn = String(claim.derivation["fn"] ?? "");
    const raw = claim.derivation["inputs"];
    const inputs = Array.isArray(raw) ? raw.map(String) : [];
    const operands = inputs.map((name) => ({ name, value: byName.get(name)?.value ?? null }));
    const vals = operands.map((o) => cents(o.value));
    let recomputed: string | null = null;
    if (vals.length > 0 && vals.every((v): v is bigint => v !== null)) {
      if (fn === "sub" && vals.length === 2) recomputed = money((vals[0] ?? 0n) - (vals[1] ?? 0n));
      else if (fn === "add" || fn === "sum") recomputed = money(vals.reduce((a, b) => a + b, 0n));
    }
    const claimed = moneyStr(claim.value);
    out.push({ claim, fn, operands, recomputed, matches: recomputed !== null && claimed !== null ? recomputed === claimed : null });
  }
  return out;
}

export const OPERATORS: Record<string, string> = { sub: "−", add: "+", sum: "+" };

// ---------------------------------------------------------------------------------------------- eval payload

export type SetCount = { n: number; success: number };
export type Sets = { handwritten: SetCount; handwritten2: SetCount; generated: SetCount };
export type Arm = {
  status: string;
  attacks?: { by_class: Record<string, Sets>; by_set: Sets; total: SetCount; generated_status?: string };
  benign?: { n: number; false_blocks: number; false_block_rate: number };
  latency_ms?: { p50: number; p95: number; added_p50: number; added_p95: number };
};
export type EvalResults = {
  commit?: { sha: string; dirty?: boolean };
  generated_at?: number;
  arms: Record<string, Arm>;
  capabilities: Record<string, Record<string, string>>;
  targets?: { held_out_successes_max: number; false_block_rate_max: number; added_p95_ms_max: number };
  targets_met?: {
    held_out_set?: string;
    held_out_n?: number;
    held_out_successes?: number | null;
    false_block_rate?: boolean | null;
    added_p95_ms?: boolean | null;
    all?: boolean;
  };
};

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** The OpenAPI schema types `results` as a free dict; this is the one place its shape (eval/run.py) is assumed. */
export function readEval(results: unknown): EvalResults | null {
  if (!isObj(results) || !isObj(results.arms) || !isObj(results.capabilities)) return null;
  return results as unknown as EvalResults;
}

export function pct(part: number, whole: number): string {
  if (whole <= 0) return "n/a";
  return `${Math.round((part / whole) * 1000) / 10}%`;
}

export function ms(v: number): string {
  return v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${v.toFixed(1)} ms`;
}

/** The slide-2 example, read from the recorded request: invoice, purchase order and the unexplained difference, in cents. */
export function invoiceFacts(claims: Claim[]): { inv: bigint; po: bigint; gap: bigint } | null {
  const by = new Map(claims.map((c) => [c.name, c.value]));
  const inv = cents(by.get("invoice.total") ?? by.get("amount"));
  const gap = cents(by.get("variance"));
  const poRaw = cents(by.get("po.total"));
  const po = poRaw ?? (inv !== null && gap !== null ? inv - gap : null);
  return inv !== null && gap !== null && po !== null ? { inv, po, gap } : null;
}
