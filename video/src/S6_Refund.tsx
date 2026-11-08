import React from "react";
import { AbsoluteFill } from "remotion";
import { C, F, sec } from "./theme";
import { Reveal, Scene, Signal, Kinetic, Chip } from "./ui";
import { GateCard } from "./Card";
import { D } from "./facts";

const clean = (s: string) => s.replace(/^reason:\s*/, "");
const Step: React.FC<{ n: number; total?: number }> = ({ n }) => (
  <div style={{ display: "flex", gap: 12 }}>{[1, 2, 3].map((i) => <div key={i} style={{ width: 70, height: 10, background: i === n ? C.pink : C.moss }} />)}</div>
);

export const Refund: React.FC = () => {
  const cards = D.b5.cards as string[][];
  const reasons = D.b5.reasons as string[];
  const shows = D.b5.shows.replace(/^.*?'(.*)'.*$/, "$1");
  const res = (re: RegExp) => (D.results as string[]).find((l) => re.test(l)) ?? "";
  const retryEq = res(/clean 250/).split(": ").pop()!;
  const smallEq = (res(/small clean refund/).match(/\((.*)\)/) ?? [])[1] ?? "";
  const mk = (card: string[], at: number, sig: "DENY" | "ALLOW", ruleTxt: string, g: string, lines: string[], head: string, n: number) => (
    <AbsoluteFill style={{ padding: "64px 100px" }}>
      <Reveal at={2}><div style={{ display: "flex", alignItems: "center", gap: 34 }}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.pink, letterSpacing: "0.05em" }}>SECOND CONNECTOR · REFUND · SAME GATE</div><Step n={n} /></div></Reveal>
      <Kinetic text={head} at={6} size={80} style={{ marginTop: 16, maxWidth: 1700 }} />
      <div style={{ display: "flex", gap: 50, marginTop: 34, alignItems: "flex-start" }}>
        <GateCard rows={card} at={sec(1.2)} size={37} highlight={["refund_to", "amount", "rule"]} />
        <div style={{ flex: 1 }}>
          <Reveal at={sec(2.6)}><Signal state={sig} size={46} rule={ruleTxt} guarantee={g} /></Reveal>
          {lines.map((l, i) => (<Reveal key={i} at={sec(3.2 + i * 0.7)} style={{ marginTop: 16 }}><div style={{ fontFamily: F.mono, fontSize: 28, color: i === 0 ? C.frost : C.sage, lineHeight: 1.28 }}>{l}</div></Reveal>))}
        </div>
      </div>
    </AbsoluteFill>
  );
  return (
    <>
      <Scene from={0} dur={sec(8.3)}>{mk(cards[0], 0, "DENY", "AP-VER-01", "G1", [`REF-311.pdf shows: "${shows}"`, clean(reasons[2]).replace(/^AP-VER-01 \(G1\)\s*/, "")], "An injected destination is refused.", 1)}</Scene>
      <Scene from={sec(8)} dur={sec(6.3)}>{mk(cards[1], 0, "DENY", "AP-CUM-03", "G1", [clean(reasons[4]).replace(/^AP-CUM-03 \(G1\)\s*/, ""), retryEq], "The next clean refund hits the cap.", 2)}</Scene>
      <Scene from={sec(14)} dur={sec(6)} fadeOut={false}>{mk(cards[2], 0, "ALLOW", "", "", ["A small clean refund executes once.", smallEq], "A small one executes once.", 3)}</Scene>
    </>
  );
};
