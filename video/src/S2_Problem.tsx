import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { C, F, SIG, latch, sec } from "./theme";
import { Reveal, Scene, Signal } from "./ui";

const GAPS = [
  { gap: "Evidence gap", head: "Unverified arguments", body: "A tool argument can hold a value with no source field and no document citation behind it." },
  { gap: "Policy gap", head: "Policy bypass", body: "A valid tool name can still carry an amount, target or actor outside the caller's scope." },
  { gap: "Execution gap", head: "Unsafe state change", body: "Retries, stale records and check-then-commit races can repeat or invalidate an approved write." },
];

export const Problem: React.FC = () => {
  const f = useCurrentFrame();
  const filt = latch(f, sec(16.5), 14);
  return (
    <AbsoluteFill style={{ padding: "64px 130px" }}>
      <Reveal at={2}><div style={{ fontFamily: F.mono, fontSize: 32, color: C.pink, letterSpacing: "0.05em" }}>THE PROBLEM · THREE GAPS</div></Reveal>
      <div style={{ marginTop: 26, display: "flex", flexDirection: "column", gap: 26 }}>
        {GAPS.map((g, i) => (
          <Reveal key={g.gap} at={sec(0.7 + i * 4.2)} dx={-40} dy={0}>
            <div style={{ display: "grid", gridTemplateColumns: "470px 1fr", columnGap: 40, alignItems: "baseline", borderLeft: `8px solid ${C.pink}`, paddingLeft: 28 }}>
              <div>
                <div style={{ fontFamily: F.mono, fontSize: 28, color: C.sage }}>{String(i + 1).padStart(2, "0")} · {g.gap}</div>
                <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 56, letterSpacing: "-0.03em", lineHeight: 1, color: C.frost, marginTop: 6 }}>{g.head}</div>
              </div>
              <div style={{ fontFamily: F.body, fontSize: 44, lineHeight: 1.22, color: C.frost }}>{g.body}</div>
            </div>
          </Reveal>
        ))}
      </div>
      <div style={{ position: "absolute", left: 130, right: 130, top: 700, opacity: filt, transform: `translateY(${(1 - filt) * 30}px)` }}>
        <div style={{ background: C.pine, border: `2px solid ${C.moss}`, padding: "20px 34px", display: "flex", alignItems: "center", gap: 30 }}>
          <div style={{ fontFamily: F.mono, fontSize: 30, color: C.sage, width: 330, lineHeight: 1.2 }}>An output filter<br />reads the reply:</div>
          <div style={{ fontFamily: F.body, fontSize: 40, color: C.frost, flex: 1 }}>"Invoice approved, all checks passed."</div>
          <div style={{ fontFamily: F.mono, fontSize: 34, color: C.allow, display: "flex", alignItems: "center", gap: 14, whiteSpace: "nowrap" }}>
            <div style={{ width: 24, height: 24, borderRadius: "50%", background: C.allow }} />sees nothing wrong
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
