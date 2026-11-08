import React from "react";
import { AbsoluteFill } from "remotion";
import { C, F, sec } from "./theme";
import { Kinetic, Reveal } from "./ui";
import { Backdrop } from "./Backdrop";

export const Close: React.FC = () => (
  <AbsoluteFill>
    <Backdrop pinkGround />
    <AbsoluteFill style={{ padding: "170px 130px" }}>
      <Kinetic text="Prove the action before the system executes it." at={4} size={132} color={C.spruce} stagger={4} style={{ maxWidth: 1650 }} />
      <Reveal at={sec(4.2)} style={{ marginTop: 44 }}><div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 76, letterSpacing: "-0.04em", color: C.frost, background: C.spruce, display: "inline-block", padding: "6px 26px 14px" }}>Proof before permission.</div></Reveal>
      <Reveal at={sec(6)} style={{ marginTop: 40 }}><div style={{ fontFamily: F.mono, fontSize: 64, fontWeight: 500, color: C.spruce }}>ActionProof</div></Reveal>
    </AbsoluteFill>
  </AbsoluteFill>
);
