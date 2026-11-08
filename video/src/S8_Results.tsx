import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { C, F, SigKey, latch, sec } from "./theme";
import { Reveal, Scene, Signal, Kinetic } from "./ui";
import { D } from "./facts";

const NAMES: Record<string, string> = { no_gate: "No gate", schema_only: "Schema only", llm_judge: "LLM judge", policy_gateway: "Policy gateway", actionproof: "ActionProof" };
const E = D.eval;
const fmtMs = (x: number) => `${Math.round(x)} ms`;
const pct = (a: number, b: number) => `${((100 * a) / b).toFixed(1)}%`;

const Bars: React.FC = () => {
  const f = useCurrentFrame();
  const W = 980;
  return (
    <div style={{ marginTop: 36, display: "flex", flexDirection: "column", gap: 20 }}>
      {E.arms.map((a, i) => {
        const t = latch(f, sec(1.2) + i * 8, 28);
        const me = a.key === "actionproof";
        const w = Math.max(me ? 0 : 6, (a.executed / a.n) * W * t);
        return (
          <div key={a.key} style={{ display: "grid", gridTemplateColumns: "330px 1fr", alignItems: "center", opacity: latch(f, sec(0.8) + i * 8, 10) }}>
            <div style={{ fontFamily: me ? F.display : F.body, fontWeight: me ? 800 : 600, fontSize: me ? 50 : 44, color: me ? C.pink : C.frost }}>{NAMES[a.key]}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
              <div style={{ width: w, height: 46, background: me ? C.allow : C.deny }} />
              <div style={{ fontFamily: F.mono, fontSize: 44, fontWeight: 500, color: me ? C.allow : C.frost, whiteSpace: "nowrap" }}>{Math.round(a.executed * t)} / {a.n}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

const Stat: React.FC<{ at: number; label: string; big: string; sub: string; state: SigKey }> = ({ at, label, big, sub, state }) => (
  <Reveal at={at} dy={36} style={{ flex: 1, background: C.pine, border: `2px solid ${C.moss}`, padding: "26px 34px" }}>
    <div style={{ fontFamily: F.mono, fontSize: 28, color: C.sage, letterSpacing: "0.03em" }}>{label}</div>
    <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 112, letterSpacing: "-0.04em", color: C.frost, lineHeight: 1.05, marginTop: 6 }}>{big}</div>
    <div style={{ fontFamily: F.body, fontSize: 36, color: C.frost, marginTop: 4, lineHeight: 1.2 }}>{sub}</div>
    <div style={{ marginTop: 14 }}><Signal state={state} size={36} /></div>
  </Reveal>
);

const LIMITS = [
  { head: "Verifier-bound", body: "Only as good as its deterministic verifiers. Free-form judgments can't be proven." },
  { head: "Semantic fraud", body: "A fake invoice that looks internally consistent is out of scope." },
  { head: "The gate is a target", body: "The signing key must stay out of the agent's reach, and the gateway needs hardening." },
  { head: "Safety, not judgment", body: "It stops unauthorized actions. It doesn't guarantee a good business decision." },
];

export const Results: React.FC = () => {
  const ap = E.arms[4];
  const att = E.arms[0].n;
  return (
    <>
      <Scene from={0} dur={sec(8.3)}>
        <AbsoluteFill style={{ padding: "60px 110px" }}>
          <Reveal at={2}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.pink, letterSpacing: "0.05em" }}>MEASURED · eval/results.json · {att} ATTACKS</div></Reveal>
          <Kinetic text="Attacks that executed." at={6} size={84} style={{ marginTop: 14 }} />
          <Bars />
        </AbsoluteFill>
      </Scene>
      <Scene from={sec(8)} dur={sec(5.3)}>
        <AbsoluteFill style={{ padding: "60px 110px" }}>
          <Reveal at={2}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.pink, letterSpacing: "0.05em" }}>ACTIONPROOF AGAINST ITS THREE TARGETS</div></Reveal>
          <div style={{ display: "flex", gap: 34, marginTop: 40 }}>
            <Stat at={sec(0.5)} label="Held-out attacks executed" big={`${E.heldOutExecuted} / ${E.heldOutN}`} sub={`target: ${E.targets.held_out_successes_max}`} state={E.met.held_out_successes ? "ALLOW" : "DENY"} />
            <Stat at={sec(1.2)} label="False blocks on benign" big={`${ap.falseBlocks} / ${ap.benignN}`} sub={`${pct(ap.falseBlocks, ap.benignN)} · target under ${(E.targets.false_block_rate_max * 100).toFixed(0)}%`} state={E.met.false_block_rate ? "ALLOW" : "DENY"} />
            <Stat at={sec(1.9)} label="Added p95 latency" big={fmtMs(ap.addedP95)} sub={`target: under ${E.targets.added_p95_ms_max} ms`} state={E.met.added_p95_ms ? "ALLOW" : "DENY"} />
          </div>
        </AbsoluteFill>
      </Scene>
      <Scene from={sec(13)} dur={sec(4.3)}>
        <AbsoluteFill style={{ padding: "70px 110px" }}>
          <Reveal at={2}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.review, letterSpacing: "0.05em", display: "flex", alignItems: "center", gap: 16 }}><Signal state="REVIEW" size={36} />READ THIS WITH THE NUMBERS</div></Reveal>
          <Kinetic text="The held-out set is a second handwritten set. It is not independent." at={6} size={78} style={{ marginTop: 20, maxWidth: 1600 }} />
          <Reveal at={sec(1.8)} style={{ marginTop: 34 }}><div style={{ fontFamily: F.body, fontSize: 48, color: C.frost, lineHeight: 1.2, maxWidth: 1550 }}>The independent generator was blocked, so there is no independently generated attack set.</div></Reveal>
          <Reveal at={sec(2.6)} style={{ marginTop: 22 }}><div style={{ fontFamily: F.mono, fontSize: 28, color: C.sage }}>results.json: {E.heldOutSet} · generated: {E.generatedStatus}</div></Reveal>
        </AbsoluteFill>
      </Scene>
      <Scene from={sec(17)} dur={sec(8)} fadeOut={false}>
        <AbsoluteFill style={{ padding: "56px 110px" }}>
          <Reveal at={2}><div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 84, letterSpacing: "-0.04em", color: C.frost }}>What ActionProof does <span style={{ color: C.pink }}>not</span> claim</div></Reveal>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 28, marginTop: 36 }}>
            {LIMITS.map((l, i) => (
              <Reveal key={l.head} at={sec(0.5 + i * 0.7)} dy={30} style={{ background: C.pine, borderLeft: `8px solid ${C.pink}`, padding: "26px 32px" }}>
                <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 62, letterSpacing: "-0.03em", color: C.frost }}>{l.head}</div>
                <div style={{ fontFamily: F.body, fontSize: 42, color: C.frost, lineHeight: 1.2, marginTop: 8 }}>{l.body}</div>
              </Reveal>
            ))}
          </div>
        </AbsoluteFill>
      </Scene>
    </>
  );
};
