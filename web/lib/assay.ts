// The "assay" story: six beats along one route. Pure data and pure functions, no three.js, no React, so the DOM
// beats, the 3D scene and the tests all read the same numbers. Nothing here is a statistic: every figure shown on the
// site is fetched (invariant 7); the only numbers in this file are timeline positions.

export type BeatId = "problem" | "evidence" | "policy" | "strike" | "audit" | "reveal";

export type Beat = { id: BeatId; label: string; title: string };

/** Beat headlines. The first and last follow the brief; the middle four say what the gate really does. */
export const BEATS: readonly Beat[] = [
  { id: "problem", label: "The request", title: "Your AI can act. But can it prove why?" },
  { id: "evidence", label: "Evidence", title: "Every value shows its source, or it does not count." },
  { id: "policy", label: "Authorization", title: "A policy decides. Not a model." },
  { id: "strike", label: "Execution", title: "One receipt. One execution." },
  { id: "audit", label: "Audit", title: "Every decision leaves a link in a chain." },
  { id: "reveal", label: "The gate", title: "Prove the action before the system executes it." },
] as const;

/** Scroll progress (0..1 over the track) at which each beat is centred: six equal sections, track measured from
 *  "top 50%" to "bottom 50%" of the viewport, so beat i is centred exactly at (i + 0.5) / 6. */
export const BEAT_AT: readonly number[] = [0, 1, 2, 3, 4, 5].map((i) => (i + 0.5) / 6);
/** Route parameter (0..1 along the curve) where the packet rests for each beat. */
export const ROUTE_AT: readonly number[] = [0.04, 0.22, 0.4, 0.58, 0.76, 0.97];

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
export const smooth = (a: number, b: number, x: number) => {
  const t = clamp01((x - a) / (b - a));
  return t * t * (3 - 2 * t);
};

/** Which beat is active at scroll progress p (the nearest centre). */
export function beatAt(p: number): number {
  let best = 0;
  let d = Infinity;
  BEAT_AT.forEach((c, i) => {
    const k = Math.abs(p - c);
    if (k < d) {
      d = k;
      best = i;
    }
  });
  return best;
}

/**
 * Scroll progress -> position on the route. The packet DWELLS near each beat centre (the plateau) and travels between
 * them, so the story reads as stations the request has to get through, not a continuous slide.
 */
export function routeAt(p: number): number {
  const x = clamp01(p);
  if (x <= BEAT_AT[0]!) return ROUTE_AT[0]!;
  for (let i = 0; i < BEAT_AT.length - 1; i++) {
    const a = BEAT_AT[i]!;
    const b = BEAT_AT[i + 1]!;
    if (x <= b) return ROUTE_AT[i]! + (ROUTE_AT[i + 1]! - ROUTE_AT[i]!) * smooth(a + (b - a) * 0.22, b - (b - a) * 0.22, x);
  }
  return ROUTE_AT[ROUTE_AT.length - 1]!;
}

/** 0..1 progress INSIDE beat i (how far the visitor has scrolled through that beat's window). */
export function beatProgress(p: number, i: number): number {
  const half = i === 0 ? BEAT_AT[1]! - BEAT_AT[0]! : BEAT_AT[i]! - BEAT_AT[i - 1]!;
  return clamp01((p - (BEAT_AT[i]! - half * 0.5)) / half);
}
