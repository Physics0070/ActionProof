import React from "react";
import { AbsoluteFill } from "remotion";
import { C, F, sec } from "./theme";
import { Kinetic, Reveal, Scene } from "./ui";
import { amount, poTotal, variance, money, invoiceId } from "./facts";

const Slip: React.FC<{ label: string; id: string; rows: [string, string][]; total: string; at: number; tilt: number; pink?: boolean }> = ({ label, id, rows, total, at, tilt, pink }) => (
  <Reveal at={at} dy={40} style={{ width: 560, background: pink ? C.pink : C.frost, color: C.spruce, padding: "30px 38px", transform: undefined, boxShadow: "0 18px 40px rgba(0,0,0,0.35)" }}>
    <div style={{ fontFamily: F.mono, fontSize: 28, letterSpacing: "0.04em", fontWeight: 500 }}>{label}</div>
    <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 64, letterSpacing: "-0.03em", marginTop: 4 }}>{id}</div>
    {rows.map(([k, v]) => (<div key={k} style={{ fontFamily: F.body, fontSize: 30, marginTop: 6, display: "flex", justifyContent: "space-between" }}><span>{k}</span><span>{v}</span></div>))}
    <div style={{ marginTop: 14, borderTop: `3px solid ${C.spruce}`, paddingTop: 10, fontFamily: F.display, fontWeight: 800, fontSize: 84, letterSpacing: "-0.04em" }}>{total}</div>
  </Reveal>
);

export const ColdOpen: React.FC = () => (
  <>
    <Scene from={0} dur={sec(4.2)}>
      <AbsoluteFill style={{ padding: "230px 150px" }}>
        <Kinetic text="Before an AI agent acts," at={6} size={128} />
        <Kinetic text="prove it should." at={30} size={128} color={C.pink} style={{ marginTop: 10 }} />
      </AbsoluteFill>
    </Scene>
    <Scene from={sec(4)} dur={sec(4.7)}>
      <AbsoluteFill style={{ padding: "90px 120px" }}>
        <Reveal at={2}><div style={{ fontFamily: F.mono, fontSize: 34, color: C.sage, letterSpacing: "0.04em" }}>ABOUT TO EXECUTE</div></Reveal>
        <Kinetic text={`Approve invoice ${invoiceId} for ${money(amount).replace(".00", "")}.`} at={4} size={96} style={{ marginTop: 14, maxWidth: 1500 }} />
        <div style={{ display: "flex", gap: 40, marginTop: 56 }}>
          <Slip label="INVOICE" id={invoiceId} rows={[["Vendor", "Acme Supplies Ltd"]]} total={money(amount)} at={26} tilt={-1.5} />
          <Slip label="PURCHASE ORDER" id="PO-2048" rows={[["Vendor", "Acme Supplies Ltd"]]} total={money(poTotal)} at={40} tilt={1} />
          <Reveal at={56} dy={40} style={{ alignSelf: "center" }}>
            <div style={{ background: C.pink, color: C.spruce, padding: "18px 34px", fontFamily: F.display, fontWeight: 800, fontSize: 110, letterSpacing: "-0.04em" }}>{money(variance)}</div>
            <div style={{ fontFamily: F.mono, fontSize: 30, color: C.pink, marginTop: 10 }}>unexplained</div>
          </Reveal>
        </div>
      </AbsoluteFill>
    </Scene>
    <Scene from={sec(8.5)} dur={sec(3.5)} fadeOut={false}>
      <AbsoluteFill style={{ padding: "250px 150px" }}>
        <Kinetic text="Proof before permission." at={4} size={170} color={C.pink} stagger={7} />
        <Reveal at={50}><div style={{ fontFamily: F.body, fontSize: 44, color: C.frost, marginTop: 44, maxWidth: 1500, lineHeight: 1.3 }}>No value can authorize a write unless its derivation re-checks <b style={{ color: C.pink }}>(G1)</b>, and no approval can be replayed <b style={{ color: C.pink }}>(G2)</b>.</div></Reveal>
      </AbsoluteFill>
    </Scene>
  </>
);
