import React from "react";
import { useCurrentFrame } from "remotion";
import { C, F, latch } from "./theme";

const tone = (row: string): string => {
  if (/FAILED|\bDENY\b/.test(row)) return C.deny;
  if (/ASSERTED|\bREVIEW\b/.test(row)) return C.review;
  if (/\bALLOW\b|\bok\]/.test(row)) return C.allow;
  return C.frost;
};
const glyph = (row: string) => (/\bDENY\b/.test(row) ? "■ " : /\bREVIEW\b/.test(row) ? "▲ " : /\bALLOW\b/.test(row) ? "● " : "");

/** The gate's intercept card: the real rows from the demo output, re-framed with the same ASCII box. */
export const GateCard: React.FC<{ rows: string[]; at: number; size?: number; highlight?: string[] }> = ({ rows, at, size = 40, highlight = [] }) => {
  const f = useCurrentFrame();
  const w = Math.max(...rows.map((r) => r.length));
  const bar = "+" + "-".repeat(w + 2) + "+";
  const lines = [bar, ...rows.map((r) => r), bar];
  return (
    <div style={{ fontFamily: F.mono, fontWeight: 500, fontSize: size, lineHeight: 1.32, background: C.pine, border: `2px solid ${C.moss}`, padding: `${size * 0.5}px ${size * 0.7}px`, display: "inline-block", whiteSpace: "pre" }}>
      {lines.map((l, i) => {
        const t = latch(f, at + i * 5, 10);
        const isEdge = i === 0 || i === lines.length - 1;
        const text = isEdge ? l : "| " + l.padEnd(w) + " |";
        const hl = highlight.some((h) => l.startsWith(h));
        const isDecision = !isEdge && l.startsWith("decision:");
        return (
          <div key={i} style={{ opacity: t, transform: `translateX(${(1 - t) * -24}px)`, color: isEdge ? C.moss : i === 1 ? C.sage : isDecision ? tone(l) : C.frost, background: hl ? "rgba(255,61,154,0.22)" : "transparent", fontWeight: isDecision ? 500 : 400 }}>
          {isDecision ? "| " + (glyph(l) + l).padEnd(w) + " |" : text}
          </div>
        );
      })}
    </div>
  );
};

/** One line of terminal output, coloured by its guarantee/decision words. */
export const TermLine: React.FC<{ text: string; at: number; size?: number; color?: string; type?: boolean }> = ({ text, at, size = 36, color, type = false }) => {
  const f = useCurrentFrame();
  const t = latch(f, at, 10);
  const shown = type ? text.slice(0, Math.max(0, Math.floor((f - at) * 2.4))) : text;
  const c = color ?? (/DENY|FAILED/.test(text) ? C.deny : /REVIEW/.test(text) ? C.review : /ALLOW|EXECUTED|OK/.test(text) ? C.allow : C.frost);
  return <div style={{ fontFamily: F.mono, fontWeight: 400, fontSize: size, lineHeight: 1.3, color: c, opacity: t, transform: `translateX(${(1 - t) * -20}px)`, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{shown}</div>;
};
