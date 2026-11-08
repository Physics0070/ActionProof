import { Easing, interpolate } from "remotion";
// Airlock palette and type: web/DESIGN.md
export const C = {
  spruce: "#0a2b26", pine: "#11403a", moss: "#2d6157", frost: "#eef8f3", sage: "#a4c9be",
  mint: "#e7f2ec", pink: "#ff3d9a",
  allow: "#34f0c2", review: "#ffd11a", deny: "#ff7d52",
};
export const F = {
  display: "'Bricolage Grotesque', 'Archivo', sans-serif",
  body: "'Archivo', sans-serif",
  mono: "'IBM Plex Mono', monospace",
};
export const FPS = 30;
export const sec = (s: number) => Math.round(s * FPS);
/** the one motion verb: latch. A bolt slides, then stops hard. cubic-bezier(0.2,0,0,1), no bounce. */
export const latchEase = Easing.bezier(0.2, 0, 0, 1);
export const latch = (frame: number, startF: number, durF = 14) =>
  interpolate(frame, [startF, startF + durF], [0, 1], { easing: latchEase, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
export const SIG = {
  ALLOW: { color: C.allow, word: "ALLOW", shape: "circle" },
  REVIEW: { color: C.review, word: "REVIEW", shape: "triangle" },
  DENY: { color: C.deny, word: "DENY", shape: "square" },
} as const;
export type SigKey = keyof typeof SIG;
