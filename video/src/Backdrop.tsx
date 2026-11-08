import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { C } from "./theme";

// Procedural airlock corridor: spruce ground, nested station rings drifting toward the door, a warm light behind it.
// Pure frame-driven SVG: no random, no flicker. `pink` makes the full-bleed pink ground used for the closing.
export const Backdrop: React.FC<{ glowColor?: string; speed?: number; pinkGround?: boolean }> = ({ glowColor = "rgba(255,61,154,0.18)", speed = 1, pinkGround = false }) => {
  const f = useCurrentFrame();
  const N = 11;
  const phase = ((f * 0.012 * speed) % 1 + 1) % 1;
  const cx = 1420, cy = 470;
  const rings = Array.from({ length: N }, (_, i) => {
    const t = (i + phase) / N;           // 0 far .. 1 near
    const k = Math.pow(t, 2.2);
    const w = 160 + k * 2600, h = 100 + k * 1500;
    return { w, h, o: Math.min(1, t * 3) * (1 - t) * 1.6 };
  });
  const ground = pinkGround ? C.pink : C.spruce;
  const line = pinkGround ? "rgba(10,43,38,0.28)" : C.moss;
  return (
    <AbsoluteFill style={{ background: ground }}>
      {!pinkGround && (
        <AbsoluteFill style={{ background: `radial-gradient(ellipse 900px 620px at ${cx}px ${cy}px, ${glowColor}, rgba(0,0,0,0) 70%)` }} />
      )}
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {rings.map((r, i) => (
          <rect key={i} x={cx - r.w / 2} y={cy - r.h / 2} width={r.w} height={r.h} fill="none" stroke={line} strokeWidth={2} opacity={r.o * 0.9} />
        ))}
        {/* floor lines converge on the door */}
        {Array.from({ length: 9 }, (_, i) => {
          const y = cy + 120 + Math.pow((i + phase) / 9, 2.4) * 640;
          return <line key={i} x1={0} x2={1920} y1={y} y2={y} stroke={line} strokeWidth={1.5} opacity={0.5 * (1 - (i + phase) / 9)} />;
        })}
        {/* door seam */}
        {!pinkGround && <rect x={cx - 70} y={cy - 110} width={140} height={220} fill="none" stroke={C.sage} strokeWidth={2} opacity={0.35} />}
      </svg>
    </AbsoluteFill>
  );
};
