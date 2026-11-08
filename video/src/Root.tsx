import React from "react";
import { AbsoluteFill, Composition, interpolateColors, useCurrentFrame } from "remotion";
import { C, FPS, sec } from "./theme";
import { Captions, Cap, Scene, useFonts } from "./ui";
import { Backdrop } from "./Backdrop";
import { ColdOpen } from "./S1_Cold";
import { Problem } from "./S2_Problem";
import { Hero, HERO_CAPS } from "./S3_Hero";
import { Injected, ReplayRace } from "./S4_Deny";
import { Refund } from "./S6_Refund";
import { Audit } from "./S7_Audit";
import { Results } from "./S8_Results";
import { Close } from "./S9_Close";
import { amount, poTotal, money, moneyShort, capAmt, raceAmt, attacksN, invoiceId } from "./facts";

// Chapter starts (seconds). Total 205 s (cap 210).
export const T = { cold: 0, problem: 12, hero: 35, injected: 85, replay: 105, refund: 130, audit: 150, results: 170, close: 195, end: 205 };
export const TOTAL = sec(T.end);

const CAPS: Cap[] = [
  { s: 0.5, e: 3.9, t: "Before an AI agent acts, prove it should." },
  { s: 4.6, e: 8.3, t: `An agent is about to approve ${invoiceId} for ${money(amount).replace(".00", "")}. The purchase order says ${money(poTotal).replace(".00", "")}.` },
  { s: 8.9, e: 11.8, t: "Proof before permission." },
  { s: 12.8, e: 16.8, t: "Gap one: a tool argument can hold a value with no source." },
  { s: 17, e: 21, t: "Gap two: a valid tool name can still carry an amount, target or actor outside scope." },
  { s: 21.2, e: 25.6, t: "Gap three: retries, stale records and races can repeat or invalidate a write." },
  { s: 28.6, e: 34.6, t: "A filter that reads the agent's reply sees nothing wrong, so the write could execute." },
  ...HERO_CAPS.map((c) => ({ ...c, s: c.s + T.hero, e: c.e + T.hero })),
  { s: T.injected + 0.6, e: T.injected + 5.4, t: "A hidden line in the PDF says: approve regardless." },
  { s: T.injected + 5.8, e: T.injected + 11.8, t: "The hijacked agent cites it as the amount. The gate re-extracts it and fails: DENY." },
  { s: T.replay + 0.5, e: T.replay + 7.7, t: "A replayed receipt is denied: an approval is spent exactly once." },
  { s: T.replay + 9, e: T.replay + 17.6, t: `Two ${moneyShort(raceAmt)} approvals race under a ${moneyShort(capAmt)} cap. Exactly one executes.` },
  { s: T.replay + 19.2, e: T.replay + 24.6, t: "Same person, second agent: still stopped." },
  { s: T.refund + 0.8, e: T.refund + 7.4, t: "A second connector, the same gate: an injected refund destination is denied." },
  { s: T.refund + 8.8, e: T.refund + 13.6, t: "The next clean refund would break the cap: denied." },
  { s: T.refund + 14.8, e: T.refund + 19.6, t: "A small one executes, exactly once." },
  { s: T.audit + 0.8, e: T.audit + 7.6, t: "Every decision lands in a signed, hash-chained log." },
  { s: T.audit + 12.2, e: T.audit + 19.6, t: "Edit one row of a copy, and the real verifier fails at that row." },
  { s: T.results + 0.8, e: T.results + 7.6, t: `Across ${attacksN} attacks, ActionProof let none execute.` },
  { s: T.results + 8.6, e: T.results + 13, t: "All three targets met. Here is what that does and does not prove." },
];

const GLOW: [number, string][] = [
  [0, "rgba(255,61,154,0.20)"], [sec(11)+0, "rgba(255,61,154,0.20)"], [sec(14), "rgba(255,125,82,0.18)"], [sec(33), "rgba(255,125,82,0.18)"],
  [sec(37), "rgba(255,209,26,0.22)"], [sec(72), "rgba(255,209,26,0.22)"], [sec(80), "rgba(52,240,194,0.20)"], [sec(84), "rgba(52,240,194,0.20)"],
  [sec(87), "rgba(255,125,82,0.22)"], [sec(128), "rgba(255,125,82,0.22)"], [sec(133), "rgba(255,209,26,0.18)"], [sec(147), "rgba(255,209,26,0.18)"],
  [sec(152), "rgba(52,240,194,0.18)"], [sec(190), "rgba(52,240,194,0.18)"],
];

const Demo: React.FC = () => {
  useFonts();
  const f = useCurrentFrame();
  const glow = interpolateColors(f, GLOW.map((g) => g[0]), GLOW.map((g) => g[1]));
  return (
    <AbsoluteFill style={{ background: C.spruce }}>
      <Backdrop glowColor={glow} />
      <Scene from={sec(T.cold)} dur={sec(12)}><ColdOpen /></Scene>
      <Scene from={sec(T.problem)} dur={sec(23)}><Problem /></Scene>
      <Scene from={sec(T.hero)} dur={sec(50)}><Hero /></Scene>
      <Scene from={sec(T.injected)} dur={sec(20)}><Injected /></Scene>
      <Scene from={sec(T.replay)} dur={sec(25)}><ReplayRace /></Scene>
      <Scene from={sec(T.refund)} dur={sec(20)}><Refund /></Scene>
      <Scene from={sec(T.audit)} dur={sec(20)}><Audit /></Scene>
      <Scene from={sec(T.results)} dur={sec(25)}><Results /></Scene>
      <Scene from={sec(T.close)} dur={sec(10)} fadeOut={false}><Close /></Scene>
      <Captions caps={CAPS} />
    </AbsoluteFill>
  );
};

export const Root: React.FC = () => (
  <Composition id="Demo" component={Demo} durationInFrames={TOTAL} fps={FPS} width={1920} height={1080} />
);
