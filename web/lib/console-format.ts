import type { Decision } from "@/components/ui/Signal";
import type { Schemas } from "./api";
import { cents, derivations, money, moneyStr } from "./site-data";

/** Mirrors PAGE_ZOOM in src/actionproof/console.py: the page PNG is rendered at this scale of PDF points. */
export const PAGE_ZOOM = 2;
/** Mirrors DecisionBody.reason (min_length / max_length) in console.py; the server enforces it too. */
export const REASON_MIN = 8;
export const REASON_MAX = 500;
export const HASH_RE = /^[0-9a-f]{64}$/;

export const STATUS_OPTIONS = ["pending", "approved", "rejected", "executed", "denied"] as const;
export const TOOL_OPTIONS = ["payments.approve_invoice", "payments.refund_payment"] as const;

export const shortHash = (h: string) => h.slice(0, 12);

/** Status/decision word -> signal; null when the word is not a decision (shown as plain text). */
export function toDecision(word: string | null | undefined): Decision | null {
  switch ((word ?? "").toUpperCase()) {
    case "ALLOW":
    case "EXECUTED":
    case "APPROVED":
      return "ALLOW";
    case "REVIEW":
    case "PENDING":
      return "REVIEW";
    case "DENY":
    case "DENIED":
    case "REJECTED":
      return "DENY";
    default:
      return null;
  }
}

export const formatUtc = (epoch: number) => `${new Date(epoch * 1000).toISOString().replace("T", " ").slice(0, 19)} UTC`;

export function formatAge(epoch: number, nowMs: number | null): string {
  if (nowMs === null) return formatUtc(epoch);
  const s = Math.max(0, Math.floor(nowMs / 1000) - epoch);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export type Bbox = [number, number, number, number];
export type Source = { doc?: string; page?: number; bbox?: Bbox; pointer?: string };

export function parseSource(src: Schemas["ClaimView"]["source"]): Source {
  if (!src) return {};
  const bb = src.bbox;
  const bbox =
    Array.isArray(bb) && bb.length === 4 && bb.every((n) => Number.isFinite(Number(n))) ? (bb.map(Number) as Bbox) : undefined;
  return {
    doc: typeof src.doc === "string" ? src.doc : undefined,
    page: typeof src.page === "number" ? src.page : undefined,
    bbox,
    pointer: typeof src.pointer === "string" ? src.pointer : undefined,
  };
}

export const guaranteeOf = (reasons: Schemas["ReasonOut"][], rule: string | null) =>
  rule ? reasons.find((r) => r.rule === rule)?.guarantee : undefined;


/** Plain-language headline for a queue item or request ("Approve invoice INV-2048 for $4,800.00"). */
export function headline(tool: string, amount: string | null | undefined, record?: string | null): string {
  const amt = moneyStr(amount ?? null) ?? (amount ? String(amount) : null);
  const rec = record ? record.replace(/^[a-z]+:/i, "") : null;
  if (tool === "payments.approve_invoice") return `Approve invoice${rec ? ` ${rec}` : ""}${amt ? ` for ${amt}` : ""}`;
  if (tool === "payments.refund_payment") return `Refund ${amt ?? "a payment"} to a customer card`;
  return `${tool}${amt ? ` for ${amt}` : ""}`;
}

const SAYS: Record<string, string> = { "invoice.total": "the invoice", "po.total": "the purchase order" };

/** One plain sentence for why a request paused, recomputed from the claims; falls back to the first policy reason. */
export function whyPaused(claims: Schemas["ClaimView"][], reasons: Schemas["ReasonOut"][]): string {
  for (const d of derivations(claims)) {
    const [a, b] = d.operands;
    if (d.fn === "sub" && a && b) {
      const x = cents(a.value);
      const y = cents(b.value);
      if (x !== null && y !== null && x !== y) {
        const gap = x > y ? x - y : y - x;
        return `${SAYS[a.name] ?? a.name} is ${money(gap)} ${x > y ? "above" : "below"} ${SAYS[b.name] ?? b.name}`;
      }
    }
  }
  return reasons[0]?.msg ?? "the gate recorded no reason";
}
