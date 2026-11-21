"use client";
// The one 3D scene of the home page (next/dynamic, ssr:false). Procedural only: lines, boxes, three small shaders.
// Everything reads the single driver (lib/site-story.ts) with getState() inside useFrame, and the frame loop is advanced
// from the one GSAP ticker only while the story is on screen. The data it draws comes from the recorded decision.
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import gsap from "gsap";
import { Component, useEffect, useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import { routeAt, smooth } from "@/lib/assay";
import { useStory } from "@/lib/site-story";
import { Chain } from "./scene/Chain";
import { Dust } from "./scene/Dust";
import { Evidence } from "./scene/Evidence";
import { Packet } from "./scene/Packet";
import { Policy } from "./scene/Policy";
import { Route } from "./scene/Route";
import { Strike } from "./scene/Strike";
import { ROUTE, usePalette } from "./scene/common";
import { modelFrom } from "./scene/model";

const UP = new THREE.Vector3(0, 1, 0);
const OVERVIEW_POS = new THREE.Vector3(30, 40, 38);
const OVERVIEW_LOOK = new THREE.Vector3(0, 0, -12);

/** Chase camera behind the packet, with a little pointer parallax; pulls back to a plan view for the reveal. */
function Rig() {
  const pos = useRef(new THREE.Vector3(-5, 2, 40));
  const look = useRef(new THREE.Vector3(-5, 0, 30));
  const sent = useRef(false);
  const lastW = useRef(0);
  const want = useMemo(() => ({ p: new THREE.Vector3(), l: new THREE.Vector3(), a: new THREE.Vector3(), b: new THREE.Vector3(), tan: new THREE.Vector3(), right: new THREE.Vector3() }), []);

  useFrame((state, dt) => {
    const { camera, size, pointer, scene } = state;
    // Shift the picture to the right on wide screens so the left column of text has the dark side of the frame.
    if (lastW.current !== size.width) {
      lastW.current = size.width;
      const cam = camera as THREE.PerspectiveCamera;
      cam.setViewOffset(size.width, size.height, size.width >= 900 ? -size.width * 0.17 : 0, 0, size.width, size.height);
      cam.updateProjectionMatrix();
    }
    const s = useStory.getState();
    const t = routeAt(s.track);
    const k = 1 - Math.exp(-dt * 4.5);
    ROUTE.getPointAt(Math.max(0, t - 0.12), want.a);
    ROUTE.getPointAt(Math.min(1, t + 0.012), want.b);
    // before the track starts (the hero), sit further back and ease in as the hero scrolls away
    const back = (1 - s.hero) * 5 * (1 - smooth(0, 0.05, s.track));
    // a three-quarter view from the side and above, so the camera never flies through the stations it is showing
    ROUTE.getTangentAt(Math.max(0, t - 0.12), want.tan);
    want.right.crossVectors(want.tan, UP).normalize();
    want.p.copy(want.a).addScaledVector(want.right, 3.4 + pointer.x * 0.6).addScaledVector(UP, 2.6 + pointer.y * 0.35);
    want.p.set(want.p.x, want.p.y, want.p.z + back);
    want.l.copy(want.b);
    const w = smooth(0.89, 0.99, s.track);
    want.p.lerp(OVERVIEW_POS, w);
    want.l.lerp(OVERVIEW_LOOK, w);
    pos.current.lerp(want.p, k);
    look.current.lerp(want.l, k);
    if (scene.fog instanceof THREE.Fog) scene.fog.far = 78 + 260 * w; // the reveal must show the whole route, not fog it out
    camera.position.copy(pos.current);
    camera.lookAt(look.current);
    if (!sent.current) {
      sent.current = true;
      window.dispatchEvent(new Event("assay-ready"));
    }
  });
  return null;
}

function TickerBridge({ active }: { active: React.RefObject<boolean> }) {
  const advance = useThree((s) => s.advance);
  useEffect(() => {
    const fn = (time: number) => {
      if (active.current && !document.hidden) advance(time * 1000);
    };
    gsap.ticker.add(fn);
    return () => {
      gsap.ticker.remove(fn);
    };
  }, [advance, active]);
  return null;
}

class SceneBoundary extends Component<{ onFail: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onFail();
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

function Inner({ active, light }: { active: React.RefObject<boolean>; light: boolean }) {
  const pal = usePalette();
  const replay = useStory((s) => s.replay);
  const model = useMemo(() => modelFrom(replay.kind === "ok" ? replay.data : null), [replay]);
  return (
    <>
      <TickerBridge active={active} />
      <fog attach="fog" args={[pal.ground, 22, 78]} />
      <Rig />
      <Dust pal={pal} light={light} />
      <Route pal={pal} light={light} />
      <Evidence pal={pal} model={model} />
      <Policy pal={pal} model={model} />
      <Strike pal={pal} model={model} />
      <Chain pal={pal} model={model} />
      <Packet pal={pal} model={model} />
    </>
  );
}

// r3f 9.8.2 (the latest) still builds a THREE.Clock internally, which three 0.187 flags as deprecated. We cannot pass
// our own clock, so that single warning is dropped while the canvas is created, then console.warn is restored.
function quietClockWarning() {
  const warn = console.warn;
  console.warn = (...a: unknown[]) => {
    if (typeof a[0] === "string" && a[0].includes("THREE.Clock")) return;
    warn(...a);
  };
  window.setTimeout(() => {
    console.warn = warn;
  }, 3000);
}

if (typeof window !== "undefined") quietClockWarning();

export default function AssayScene({ active, light }: { active: React.RefObject<boolean>; light: boolean }) {
  return (
    <SceneBoundary onFail={() => useStory.setState((s) => ({ caps: { ...s.caps, webgl: false } }))}>
      <Canvas frameloop="never" dpr={light ? 1 : [1, 1.6]} camera={{ fov: light ? 56 : 42, position: [-5, 2, 40], near: 0.1, far: 140 }} gl={{ antialias: !light, alpha: true, powerPreference: "high-performance" }} aria-hidden="true">
        <Inner active={active} light={light} />
      </Canvas>
    </SceneBoundary>
  );
}
