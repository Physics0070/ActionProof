import React from "react";
import { AbsoluteFill, Sequence, delayRender, continueRender, staticFile, useCurrentFrame, interpolate } from "remotion";
import { C, F, FPS, SIG, SigKey, latch, latchEase } from "./theme";

// ---- fonts (same files the site self-hosts)
export const useFonts = () => {
  const [h] = React.useState(() => delayRender("fonts"));
  React.useEffect(() => {
    const defs: [string, string, string][] = [
      ["Bricolage Grotesque", "fonts/bricolage.woff2", "700 800"],
      ["Archivo", "fonts/archivo.woff2", "400 600"],
      ["IBM Plex Mono", "fonts/plexmono-400.woff2", "400"],
      ["IBM Plex Mono", "fonts/plexmono-500.woff2", "500"],
    ];
    Promise.all(defs.map(([fam, url, w]) => new FontFace(fam, `url(${staticFile(url)})`, { weight: w }).load().then((f) => document.fonts.add(f))))
      .then(() => continueRender(h)).catch(() => continueRender(h));
  }, [h]);
};

// ---- a scene wrapper: latches in, latches out (fade + 24px travel; no linear snaps)
export const Scene: React.FC<{ from: number; dur: number; children: React.ReactNode; fadeOut?: boolean }> = ({ from, dur, children, fadeOut = true }) => (
  <Sequence from={from} durationInFrames={dur} layout="none">
    <SceneInner dur={dur} fadeOut={fadeOut}>{children}</SceneInner>
  </Sequence>
);
const SceneInner: React.FC<{ dur: number; children: React.ReactNode; fadeOut: boolean }> = ({ dur, children, fadeOut }) => {
  const f = useCurrentFrame();
  const inn = latch(f, 0, 12);
  const out = fadeOut ? 1 - latch(f, dur - 10, 10) : 1;
  return <AbsoluteFill style={{ opacity: Math.min(inn, out) }}>{children}</AbsoluteFill>;
};

// ---- Reveal: slides up a short distance, clipped by opacity only (transform + opacity)
export const Reveal: React.FC<{ at: number; dur?: number; dy?: number; dx?: number; children: React.ReactNode; style?: React.CSSProperties }> = ({ at, dur = 14, dy = 28, dx = 0, children, style }) => {
  const f = useCurrentFrame();
  const t = latch(f, at, dur);
  return <div style={{ opacity: t, transform: `translate(${(1 - t) * dx}px, ${(1 - t) * dy}px)`, ...style }}>{children}</div>;
};

// ---- kinetic text: words latch in with stagger, each from below inside a mask
export const Kinetic: React.FC<{ text: string; at: number; size: number; color?: string; weight?: number; stagger?: number; style?: React.CSSProperties; lineHeight?: number }> = ({ text, at, size, color = C.frost, weight = 800, stagger = 4, style, lineHeight = 0.98 }) => {
  const f = useCurrentFrame();
  return (
    <div style={{ fontFamily: F.display, fontSize: size, fontWeight: weight, color, letterSpacing: "-0.04em", lineHeight, display: "flex", flexWrap: "wrap", columnGap: size * 0.26, ...style }}>
      {text.split(" ").map((w, i) => {
        const t = latch(f, at + i * stagger, 16);
        return (
          <span key={i} style={{ display: "inline-block", overflow: "hidden", paddingBottom: size * 0.12, marginBottom: -size * 0.12 }}>
            <span style={{ display: "inline-block", transform: `translateY(${(1 - t) * 105}%)`, opacity: t > 0 ? 1 : 0 }}>{w}</span>
          </span>
        );
      })}
    </div>
  );
};

// ---- signal mark: colour + shape + word (never colour alone)
export const Signal: React.FC<{ state: SigKey; size?: number; guarantee?: string; rule?: string }> = ({ state, size = 44, guarantee, rule }) => {
  const s = SIG[state];
  const m = size * 0.62;
  const shape = s.shape === "circle" ? <div style={{ width: m, height: m, borderRadius: "50%", background: s.color }} />
    : s.shape === "square" ? <div style={{ width: m, height: m, background: s.color }} />
    : <div style={{ width: 0, height: 0, borderLeft: `${m * 0.62}px solid transparent`, borderRight: `${m * 0.62}px solid transparent`, borderBottom: `${m * 1.05}px solid ${s.color}` }} />;
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: size * 0.3, fontFamily: F.mono, fontWeight: 500, fontSize: size, color: s.color, letterSpacing: "0.02em" }}>
      {shape}<span>{s.word}</span>
      {(rule || guarantee) && <span style={{ color: C.frost, opacity: 0.9 }}>{rule}{guarantee ? ` (${guarantee})` : ""}</span>}
    </div>
  );
};

// ---- captions: bottom band, always on top, safe margins. 46px, <= 2 lines.
export type Cap = { s: number; e: number; t: string };
export const Captions: React.FC<{ caps: Cap[] }> = ({ caps }) => {
  const f = useCurrentFrame();
  const c = caps.find((x) => f >= x.s * FPS && f < x.e * FPS);
  if (!c) return null;
  const a = latch(f, c.s * FPS, 8) * (1 - latch(f, c.e * FPS - 6, 6));
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 170, display: "flex", alignItems: "center", justifyContent: "center", pointerEvents: "none",
      background: "linear-gradient(to top, rgba(10,43,38,0.96) 55%, rgba(10,43,38,0))", opacity: a }}>
      <div style={{ fontFamily: F.body, fontWeight: 600, fontSize: 46, lineHeight: 1.22, color: C.frost, textAlign: "center", maxWidth: 1560, paddingBottom: 14 }}>{c.t}</div>
    </div>
  );
};

export const Chip: React.FC<{ children: React.ReactNode; bg?: string; fg?: string; size?: number }> = ({ children, bg = C.pink, fg = C.spruce, size = 34 }) => (
  <span style={{ background: bg, color: fg, fontFamily: F.mono, fontWeight: 500, fontSize: size, padding: `${size * 0.2}px ${size * 0.5}px`, letterSpacing: "0.02em" }}>{children}</span>
);

export const fmtMoney = (s: string) => "$" + Number(s).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export { interpolate, latchEase };
