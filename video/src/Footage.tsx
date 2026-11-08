import React from "react";
import { AbsoluteFill, OffthreadVideo, staticFile, useCurrentFrame, interpolate } from "remotion";
import { C, F, FPS, latchEase } from "./theme";

export type Cam = { t: number; cx: number; cy: number; z: number };   // t seconds (local), source-pixel centre, zoom
const K = 1580 / 1920;                                                // frame is 1580x888 over a 1920x1080 recording
const FW = 1580, FH = 888;

/** Real recording, framed above the caption band, with a latch-eased camera (zoom + pan in source pixels). */
export const Footage: React.FC<{ src: string; from: number; cam?: Cam[]; label?: string }> = ({ src, from, cam = [{ t: 0, cx: 960, cy: 540, z: 1 }], label }) => {
  const f = useCurrentFrame();
  const t = f / FPS;
  const ts = cam.map((c) => c.t);
  const ease = { easing: latchEase, extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const };
  // segment-wise latch ease between keyframes
  let i = Math.max(0, ts.findIndex((x) => x > t) - 1); if (t >= ts[ts.length - 1]) i = ts.length - 1;
  const a = cam[i], b = cam[Math.min(i + 1, cam.length - 1)];
  const u = a === b ? 0 : interpolate(t, [a.t, b.t], [0, 1], ease);
  const cx = a.cx + (b.cx - a.cx) * u, cy = a.cy + (b.cy - a.cy) * u, z = a.z + (b.z - a.z) * u;
  const s = K * z;
  const tx = Math.min(0, Math.max(FW - 1920 * s, FW / 2 - cx * s));
  const ty = Math.min(0, Math.max(FH - 1080 * s, FH / 2 - cy * s));
  return (
    <div style={{ position: "absolute", left: 170, top: 22, width: FW, height: FH, overflow: "hidden", background: C.spruce, border: `2px solid ${C.moss}` }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 1080, transformOrigin: "0 0", transform: `translate(${tx}px, ${ty}px) scale(${s})` }}>
        <OffthreadVideo src={staticFile(src)} startFrom={Math.round(from * FPS)} muted style={{ width: 1920, height: 1080 }} />
      </div>
      {label && <div style={{ position: "absolute", right: 18, top: 16, fontFamily: F.mono, fontWeight: 500, fontSize: 26, background: C.pink, color: C.spruce, padding: "6px 16px" }}>{label}</div>}
    </div>
  );
};
