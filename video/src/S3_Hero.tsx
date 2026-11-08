import React from "react";
import { AbsoluteFill } from "remotion";
import { C, F, sec } from "./theme";
import { Reveal, Scene, Signal, Chip } from "./ui";
import { GateCard } from "./Card";
import { Footage, Cam } from "./Footage";
import { D, amount, poTotal, variance, money, ruleId, rule } from "./facts";
import { CLIPS } from "./clips";

// local seconds inside the hero chapter (50 s)
export const HERO_CAPS = [
  { s: 0.6, e: 5.4, t: "The agent calls the tool. The gate intercepts it first: default deny." },
  { s: 7, e: 21.4, t: "Verify: re-extract the cited value, recompute the derived one. The model never does the arithmetic." },
  { s: 22.6, e: 26.8, t: "Authorize: a policy rule sends it to a human. REVIEW." },
  { s: 28.4, e: 36, t: "A different person opens the request and sees the evidence, not the agent's summary." },
  { s: 41.2, e: 44.8, t: "Approve. The write executes once." },
  { s: 45.6, e: 49.6, t: "Requested by agent-7 for user-123. Approved by a different person." },
];

const fmt = (s: string) => Number(s).toLocaleString("en-US", { minimumFractionDigits: 2 });
const span = (D.b1.span as string).match(/bbox=\[(.*)\]/)?.[1].replace(/'/g, "") ?? "";
const page = (D.b1.span as string).match(/page=(\d+)/)?.[1] ?? "1";

const StepRow: React.FC<{ n: number; head: string; lines: string[]; at: number }> = ({ n, head, lines, at }) => (
  <Reveal at={at} dx={-30} dy={0} style={{ borderLeft: `6px solid ${C.pink}`, paddingLeft: 24, marginBottom: 20 }}>
    <div style={{ display: "flex", alignItems: "baseline", gap: 18 }}>
      <span style={{ fontFamily: F.mono, fontSize: 30, color: C.pink }}>{n}</span>
      <span style={{ fontFamily: F.display, fontWeight: 800, fontSize: 58, letterSpacing: "-0.03em", color: C.frost }}>{head}</span>
    </div>
    {lines.map((l, i) => (<div key={i} style={{ fontFamily: F.mono, fontSize: 29, color: i % 2 ? C.sage : C.frost, lineHeight: 1.3, marginTop: 4 }}>{l}</div>))}
  </Reveal>
);

export const Hero: React.FC = () => (
  <>
    {/* A: the gate scene, real site recording (Intercept, then Verify with the equation) */}
    <Scene from={0} dur={sec(6.2)}>
      <Footage src={CLIPS.gate.src} from={CLIPS.gate.intercept} label="the real site · scroll into the gate" cam={[{ t: 0, cx: 960, cy: 540, z: 1 }, { t: 3.4, cx: 960, cy: 540, z: 1 }, { t: 4.6, cx: 560, cy: 620, z: 1.5 }]} />
    </Scene>
    {/* B: the five steps with the real card */}
    <Scene from={sec(6)} dur={sec(16.4)}>
      <AbsoluteFill style={{ padding: "56px 90px" }}>
        <div style={{ display: "flex", gap: 60 }}>
          <div>
            <Reveal at={2}><div style={{ fontFamily: F.mono, fontSize: 28, color: C.sage, marginBottom: 14 }}>agent → payments_approve_invoice(INV-2048)</div></Reveal>
            <GateCard rows={D.b1.card as string[]} at={sec(0.4)} size={40} highlight={["amount", "variance", "rule"]} />
            <Reveal at={sec(9.5)} style={{ marginTop: 22 }}><Signal state="REVIEW" size={60} rule={ruleId} guarantee="G1" /></Reveal>
          </div>
          <div style={{ flex: 1, paddingTop: 6 }}>
            <StepRow n={1} head="Intercept" at={sec(1)} lines={["An MCP proxy in front of every tool. Default deny."]} />
            <StepRow n={2} head="Verify" at={sec(2.6)} lines={[`re-extract ${money(amount)} at page ${page}, box [${span}]`, `recompute ${fmt(amount)} − ${fmt(poTotal)} = ${fmt(variance)}`, "allowlisted pure function, never the model"]} />
            <StepRow n={3} head="Authorize" at={sec(7.4)} lines={[`rule ${rule} ⇒ REVIEW`]} />
            <StepRow n={4} head="Receipt and commit" at={sec(10.6)} lines={["signed one-use receipt, minted only after a human decides"]} />
          </div>
        </div>
      </AbsoluteFill>
    </Scene>
    {/* C: the door at REVIEW */}
    <Scene from={sec(22.2)} dur={sec(5.6)}>
      <Footage src={CLIPS.gate.src} from={CLIPS.gate.review} label="the real site · REVIEW pending" cam={[{ t: 0, cx: 960, cy: 540, z: 1 }]} />
    </Scene>
    {/* D: the real console, four cuts on action */}
    <Scene from={sec(27.6)} dur={sec(5.3)}>
      <Footage src={CLIPS.console.src} from={2.0} label="the real console · rev-alice signs in" cam={[{ t: 0, cx: 960, cy: 540, z: 1 }]} />
    </Scene>
    <Scene from={sec(32.6)} dur={sec(6.8)}>
      <Footage src={CLIPS.console.src} from={13.0} label={`source span highlighted · invoice.pdf p.${page}`} cam={[{ t: 0, cx: 960, cy: 540, z: 1 }, { t: 3.4, cx: 960, cy: 540, z: 1 }, { t: 4.8, cx: 1180, cy: 540, z: 1.7 }]} />
    </Scene>
    <Scene from={sec(39.1)} dur={sec(7.8)}>
      <Footage src={CLIPS.console.src} from={25.0} label="reason, Approve, Confirm" cam={[{ t: 0, cx: 960, cy: 900, z: 1.3 }]} />
    </Scene>
    <Scene from={sec(46.6)} dur={sec(3.4)} fadeOut={false}>
      <Footage src={CLIPS.console.src} from={34.0} label="the real console · after Confirm" cam={[{ t: 0, cx: 560, cy: 1000, z: 2.4 }]} />
      <Reveal at={sec(0.5)} dx={40} dy={0} style={{ position: "absolute", right: 250, top: 150, background: C.spruce, border: `2px solid ${C.moss}`, padding: "18px 30px" }}>
        <Signal state="ALLOW" size={60} />
        <div style={{ fontFamily: F.mono, fontSize: 34, color: C.frost, marginTop: 8 }}>{String((D as any).request?.status ?? "executed")} once · {String((D as any).request?.reviewer ?? "")}</div>
      </Reveal>
    </Scene>
  </>
);
