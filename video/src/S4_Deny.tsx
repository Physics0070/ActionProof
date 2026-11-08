import React from "react";
import { AbsoluteFill } from "remotion";
import { C, F, sec } from "./theme";
import { Reveal, Scene, Signal, Kinetic } from "./ui";
import { GateCard, TermLine } from "./Card";
import { D, money } from "./facts";

export const quoteOf = (s: string) => (s.match(/'(.*)'/)?.[1] ?? s);

/** Beat 2: injected PDF. All text from the demo log (b2). */
export const Injected: React.FC = () => {
  const hidden = quoteOf(D.b2.hidden);
  const inj = (D.b2.card as string[]).find((r) => r.startsWith("amount:"))!.split(" ")[1];
  const why = D.b2.reasons[1].replace(/^reason:\s*/, "");
  return (
    <AbsoluteFill style={{ padding: "60px 100px" }}>
      <Reveal at={2}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.pink, letterSpacing: "0.05em" }}>INJECTED PDF · HIDDEN TEXT</div></Reveal>
      <div style={{ display: "flex", gap: 56, marginTop: 24 }}>
        <div style={{ width: 760 }}>
          <Reveal at={10} dy={30}>
            <div style={{ background: C.frost, color: C.spruce, padding: "26px 32px", boxShadow: "0 18px 40px rgba(0,0,0,0.35)" }}>
              <div style={{ fontFamily: F.mono, fontSize: 26, fontWeight: 500 }}>injected.pdf · page 1</div>
              <div style={{ fontFamily: F.body, fontSize: 34, marginTop: 10 }}>Vendor: Acme Supplies Ltd</div>
              <div style={{ fontFamily: F.body, fontSize: 34 }}>Total: {money(inj)}</div>
              <div style={{ marginTop: 18, fontFamily: F.mono, fontSize: 26, background: C.pink, color: C.spruce, padding: "10px 14px", lineHeight: 1.25 }}>{hidden}</div>
              <div style={{ fontFamily: F.mono, fontSize: 24, marginTop: 8, color: "#416257" }}>hidden: white text, 1 pt</div>
            </div>
          </Reveal>
        </div>
        <div style={{ flex: 1 }}>
          <GateCard rows={D.b2.card as string[]} at={sec(3.5)} size={37} highlight={["amount", "rule"]} />
          <Reveal at={sec(8)} style={{ marginTop: 26 }}><Signal state="DENY" size={64} rule="AP-VER-01" guarantee="G1" /></Reveal>
          <Reveal at={sec(9)} style={{ marginTop: 10 }}><div style={{ fontFamily: F.mono, fontSize: 30, color: C.sage, lineHeight: 1.3 }}>{why}</div></Reveal>
        </div>
      </div>
      <Reveal at={sec(13)} style={{ position: "absolute", left: 100, top: 790 }}>
        <Kinetic text="Document text can describe a value; it can never authorize one." at={sec(13)} size={52} color={C.pink} stagger={3} style={{ maxWidth: 1760 }} />
      </Reveal>
    </AbsoluteFill>
  );
};

const L = (re: RegExp, lines: string[]) => (lines.find((l) => re.test(l)) ?? "").replace(/\s{2,}/g, "  ");
const clean = (s: string) => s.replace(/^reason:\s*/, "");

/** Beats 3 and 4 */
export const ReplayRace: React.FC = () => {
  const r3 = D.b3.reasons;
  const b4 = D.b4.lines as string[];
  const cap = (L(/committed for/, b4).match(/cap ([\d.]+)/) ?? [])[1];
  const committed = (L(/committed for/, b4).match(/: ([\d.]+)/) ?? [])[1];
  const rot = L(/agent-7 spends/, b4);
  const rotReason = clean(b4.filter((l) => l.startsWith("reason:"))[1]);
  const raceReason = clean(b4.filter((l) => l.startsWith("reason:"))[0]);
  return (
    <>
      <Scene from={0} dur={sec(8.3)}>
        <AbsoluteFill style={{ padding: "70px 110px" }}>
          <Reveal at={2}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.pink, letterSpacing: "0.05em" }}>REPLAY · G2</div></Reveal>
          <Kinetic text="An approval is spent exactly once." at={6} size={92} style={{ marginTop: 18, maxWidth: 1500 }} />
          <Reveal at={sec(2.2)} style={{ marginTop: 40 }}><div style={{ fontFamily: F.mono, fontSize: 34, color: C.sage }}>the same signed receipt, replayed at commit:</div></Reveal>
          <Reveal at={sec(3.4)} style={{ marginTop: 20 }}><Signal state="DENY" size={72} rule="AP-REP-05" guarantee="G2" /></Reveal>
          <Reveal at={sec(4)} style={{ marginTop: 14 }}><div style={{ fontFamily: F.mono, fontSize: 36, color: C.frost }}>{clean(r3[0]).replace(/^AP-REP-05 \(G2\)\s*/, "")}</div></Reveal>
          <Reveal at={sec(5.3)} style={{ marginTop: 26 }}><div style={{ fontFamily: F.mono, fontSize: 30, color: C.sage, lineHeight: 1.3, maxWidth: 1650 }}>{D.b3.audited}</div></Reveal>
        </AbsoluteFill>
      </Scene>
      <Scene from={sec(8)} dur={sec(10.3)}>
        <AbsoluteFill style={{ padding: "70px 110px" }}>
          <Reveal at={2}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.pink, letterSpacing: "0.05em" }}>RACE · COMMIT TIME</div></Reveal>
          <Kinetic text={`Two concurrent $4,900 approvals. One $5,000 cap.`} at={6} size={86} style={{ marginTop: 18, maxWidth: 1600 }} />
          <div style={{ display: "flex", gap: 50, marginTop: 40 }}>
            <Reveal at={sec(2.5)} dx={-30} dy={0} style={{ flex: 1, background: C.pine, border: `2px solid ${C.moss}`, padding: "28px 36px" }}>
              <div style={{ fontFamily: F.mono, fontSize: 34, color: C.sage }}>approval A</div>
              <div style={{ marginTop: 10 }}><Signal state="ALLOW" size={64} /></div>
              <div style={{ fontFamily: F.mono, fontSize: 32, color: C.frost, marginTop: 10 }}>EXECUTED</div>
            </Reveal>
            <Reveal at={sec(4)} dx={30} dy={0} style={{ flex: 1, background: C.pine, border: `2px solid ${C.moss}`, padding: "28px 36px" }}>
              <div style={{ fontFamily: F.mono, fontSize: 34, color: C.sage }}>approval B</div>
              <div style={{ marginTop: 10 }}><Signal state="DENY" size={64} rule="AP-CUM-03" guarantee="G1" /></div>
              <div style={{ fontFamily: F.mono, fontSize: 30, color: C.frost, marginTop: 10, lineHeight: 1.25 }}>{raceReason.replace(/^AP-CUM-03 \(G1\)\s*/, "")}</div>
            </Reveal>
          </div>
          <Reveal at={sec(6.5)} style={{ marginTop: 30 }}><div style={{ fontFamily: F.mono, fontSize: 36, color: C.frost }}>exactly one executes · committed {committed} · cap {cap}</div></Reveal>
        </AbsoluteFill>
      </Scene>
      <Scene from={sec(18)} dur={sec(7)}>
        <AbsoluteFill style={{ padding: "70px 110px" }}>
          <Reveal at={2}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.pink, letterSpacing: "0.05em" }}>SAME PERSON, SECOND AGENT</div></Reveal>
          <Kinetic text="A second agent can't dodge the cap." at={6} size={92} style={{ marginTop: 18, maxWidth: 1500 }} />
          <Reveal at={sec(2)} style={{ marginTop: 36 }}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.sage, lineHeight: 1.3, maxWidth: 1700 }}>{L(/actor rotation/, b4)}</div></Reveal>
          <Reveal at={sec(3.2)} style={{ marginTop: 22 }}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.frost, lineHeight: 1.3, maxWidth: 1700 }}>{rot}</div></Reveal>
          <Reveal at={sec(4.4)} style={{ marginTop: 26 }}><Signal state="DENY" size={64} rule="AP-CUM-03" guarantee="G1" /></Reveal>
          <Reveal at={sec(4.8)} style={{ marginTop: 10 }}><div style={{ fontFamily: F.mono, fontSize: 30, color: C.sage }}>{rotReason.replace(/^AP-CUM-03 \(G1\)\s*/, "")}</div></Reveal>
        </AbsoluteFill>
      </Scene>
    </>
  );
};
