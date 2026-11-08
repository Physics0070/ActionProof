import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { C, F, latch, sec } from "./theme";
import { Reveal, Scene, Signal, Kinetic } from "./ui";
import { D } from "./facts";

const num = (s: string, re: RegExp) => Number((s.match(re) ?? [])[1] ?? 0);

/** hash chain: n linked blocks; after the tamper, the edited seq and every link after it fail */
const Chain: React.FC<{ n: number; bad: number | null; badAt: number }> = ({ n, bad, badAt }) => {
  const f = useCurrentFrame();
  const t = latch(f, badAt, 10);
  const per = 62;
  return (
    <div style={{ display: "flex", alignItems: "center" }}>
      {Array.from({ length: n }, (_, i) => {
        const seq = i + 1;
        const broken = bad !== null && seq >= bad;
        const edited = bad === seq;
        const col = broken && t > 0 ? (edited ? C.deny : C.moss) : C.allow;
        return (
          <React.Fragment key={i}>
            <div style={{ width: per - 22, height: 56, background: edited && t > 0 ? C.deny : C.pine, border: `3px solid ${col}`, color: edited && t > 0 ? C.spruce : col, fontFamily: F.mono, fontSize: 22, fontWeight: 500, display: "flex", alignItems: "center", justifyContent: "center", opacity: latch(f, 6 + i * 1.2, 8) }}>{seq}</div>
            {i < n - 1 && <div style={{ width: 22, height: 4, background: broken && t > 0 && seq >= bad! ? C.moss : C.allow, opacity: latch(f, 8 + i * 1.2, 8) }} />}
          </React.Fragment>
        );
      })}
    </div>
  );
};

export const Audit: React.FC = () => {
  const n = num(D.audit.ok!, /\((\d+) entries/);
  const m = num(D.audit.ok!, /(\d+) checkpoints/);
  const bad = num(D.audit.failed!, /seq (\d+)/);
  return (
    <>
      <Scene from={0} dur={sec(8.3)}>
        <AbsoluteFill style={{ padding: "70px 100px" }}>
          <Reveal at={2}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.pink, letterSpacing: "0.05em" }}>RECEIPTS YOU CAN VERIFY</div></Reveal>
          <Kinetic text="Every decision is a hash-chained, signed entry." at={6} size={80} style={{ marginTop: 16, maxWidth: 1600 }} />
          <div style={{ marginTop: 50 }}><Chain n={n} bad={null} badAt={9999} /></div>
          <Reveal at={sec(2.4)} style={{ marginTop: 50 }}><div style={{ fontFamily: F.mono, fontSize: 34, color: C.sage }}>{D.audit.cmds[0]}</div></Reveal>
          <Reveal at={sec(3.6)} style={{ marginTop: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
              <Signal state="ALLOW" size={56} />
              <div style={{ fontFamily: F.mono, fontSize: 56, color: C.frost, fontWeight: 500 }}>{D.audit.ok}</div>
            </div>
          </Reveal>
        </AbsoluteFill>
      </Scene>
      <Scene from={sec(8)} dur={sec(12)} fadeOut={false}>
        <AbsoluteFill style={{ padding: "70px 100px" }}>
          <Reveal at={2}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.pink, letterSpacing: "0.05em" }}>TAMPER TEST · REAL VERIFIER, A COPY OF THE LOG</div></Reveal>
          <Reveal at={sec(0.6)} style={{ marginTop: 22 }}><div style={{ fontFamily: F.body, fontSize: 44, color: C.frost, maxWidth: 1650, lineHeight: 1.22 }}>{(D.audit.edit ?? "").replace(/^\$\s*\(|\)$/g, "")}</div></Reveal>
          <div style={{ marginTop: 50 }}><Chain n={n} bad={bad} badAt={sec(2.2)} /></div>
          <Reveal at={sec(3.4)} style={{ marginTop: 50 }}><div style={{ fontFamily: F.mono, fontSize: 34, color: C.sage }}>{D.audit.cmds[1]}</div></Reveal>
          <Reveal at={sec(4.6)} style={{ marginTop: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
              <Signal state="DENY" size={56} />
              <div style={{ fontFamily: F.mono, fontSize: 50, color: C.frost, fontWeight: 500 }}>{D.audit.failed}</div>
            </div>
          </Reveal>
          <Reveal at={sec(6.6)} style={{ marginTop: 26 }}><div style={{ fontFamily: F.mono, fontSize: 30, color: C.sage }}>{n} entries · {m} signed checkpoints · edit one row and verification fails at that row</div></Reveal>
        </AbsoluteFill>
      </Scene>
    </>
  );
};
