"use client";
// The one 3D scene (loaded with next/dynamic, ssr:false). Procedural only: points + a shader, no textures/models.
// Signals are emissive light: each lamp is also a shape (circle, triangle, square) and has its word in the DOM legend.
// Driven by lib/site-story.ts: progress/chapter/step are read with getState() inside useFrame (no re-renders), and
// the render loop is advanced from the single GSAP ticker (frameloop="never").
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import gsap from "gsap";
import { Component, useEffect, useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import { useStory } from "@/lib/site-story";

type Decision = "ALLOW" | "REVIEW" | "DENY";
const GATE_X = 1.6;

function token(name: string, fallback: string): THREE.Color {
  const v = typeof document === "undefined" ? "" : getComputedStyle(document.body).getPropertyValue(name).trim();
  return new THREE.Color(v || fallback);
}

const POINT_VERT = /* glsl */ `
  uniform float uTime; uniform float uP; uniform float uSize; uniform float uGate;
  attribute float aSeed;
  varying float vPast;
  void main() {
    float a = uTime * 0.12;
    vec3 p = position;
    p.xz = mat2(cos(a), -sin(a), sin(a), cos(a)) * p.xz;
    p.x += uP * 3.4 * (0.35 + aSeed * 0.65) - 1.3;
    p.xy += 0.025 * vec3(sin(uTime * 0.7 + aSeed * 40.0), cos(uTime * 0.5 + aSeed * 31.0), 0.0).xy;
    float past = step(uGate, p.x);
    p.x = mix(p.x, uGate + (p.x - uGate) * 0.12, past);
    vPast = past;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = uSize / -mv.z;
    gl_Position = projectionMatrix * mv;
  }`;
const POINT_FRAG = /* glsl */ `
  uniform vec3 uDim; uniform vec3 uBright;
  varying float vPast;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    if (dot(c, c) > 0.25) discard;
    gl_FragColor = vec4(mix(uDim, uBright, vPast), mix(0.55, 1.0, vPast));
  }`;

function setU(u: Record<string, THREE.IUniform>, key: string, v: number) {
  const x = u[key];
  if (x) x.value = v;
}

function Particles({ count }: { count: number }) {
  const mat = useRef<THREE.ShaderMaterial>(null);
  const { geo, uniforms } = useMemo(() => {
    const pos = new Float32Array(count * 3);
    const seed = new Float32Array(count);
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < count; i++) {
      const y = 1 - (i / (count - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      pos.set([Math.cos(i * golden) * r, y, Math.sin(i * golden) * r], i * 3);
      seed[i] = (i * 0.61803398875) % 1;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
    const ink = token("--carbon-muted", "#a9a7b4");
    const text = token("--carbon-text", "#f6f8f7");
    return {
      geo: g,
      uniforms: {
        uTime: { value: 0 },
        uP: { value: 0 },
        uSize: { value: 5 },
        uGate: { value: GATE_X },
        uDim: { value: ink.multiplyScalar(0.7) },
        uBright: { value: text },
      },
    };
  }, [count]);
  const dpr = useThree((s) => s.viewport.dpr);
  useFrame((state) => {
    const u = mat.current?.uniforms;
    if (!u) return;
    setU(u, "uTime", state.clock.elapsedTime);
    setU(u, "uP", useStory.getState().progress);
    setU(u, "uSize", 18 * dpr);
  });
  return (
    <points geometry={geo}>
      <shaderMaterial ref={mat} uniforms={uniforms} vertexShader={POINT_VERT} fragmentShader={POINT_FRAG} transparent depthWrite={false} />
    </points>
  );
}

const HALO_FRAG = /* glsl */ `
  uniform vec3 uColor; uniform float uLevel; varying vec2 vUv;
  void main() { float d = distance(vUv, vec2(0.5)) * 2.0; float a = pow(max(0.0, 1.0 - d), 2.0) * uLevel * 0.7; gl_FragColor = vec4(uColor, a); }`;
const HALO_VERT = /* glsl */ `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

/** One signal lamp: a shape plus a halo. Level moves at constant speed and stops hard (motion verb: latch). */
function Lamp({ shape, y, color }: { shape: Decision; y: number; color: THREE.Color }) {
  const body = useRef<THREE.MeshBasicMaterial>(null);
  const halo = useRef<THREE.ShaderMaterial>(null);
  const level = useRef(0.18);
  const dim = useMemo(() => new THREE.Color("#3a3846"), []);
  const haloUniforms = useMemo(() => ({ uColor: { value: color }, uLevel: { value: 0 } }), [color]);
  useFrame((state, dt) => {
    const s = useStory.getState();
    const rep = s.replay.kind === "ok" ? s.replay.data : null;
    let target = 0.18 + 0.05 * Math.sin(state.clock.elapsedTime * 1.4);
    if (rep && s.chapter === 3) {
      if (s.step >= 2 && rep.decision === shape) target = 1;
      if (s.step >= 3 && shape === "DENY" && rep.replay_attempts.length > 0) target = 1;
    }
    level.current += THREE.MathUtils.clamp(target - level.current, -dt * 6, dt * 6);
    body.current?.color.copy(dim).lerp(color, level.current);
    if (halo.current) setU(halo.current.uniforms, "uLevel", level.current);
  });
  return (
    <group position={[GATE_X, y, 0.05]}>
      <mesh rotation={shape === "REVIEW" ? [0, 0, Math.PI / 2] : [0, 0, 0]}>
        {shape === "ALLOW" ? <circleGeometry args={[0.17, 48]} /> : null}
        {shape === "REVIEW" ? <circleGeometry args={[0.22, 3]} /> : null}
        {shape === "DENY" ? <planeGeometry args={[0.3, 0.3]} /> : null}
        <meshBasicMaterial ref={body} toneMapped={false} />
      </mesh>
      <mesh position={[0, 0, -0.01]}>
        <planeGeometry args={[1.5, 1.5]} />
        <shaderMaterial ref={halo} uniforms={haloUniforms} vertexShader={HALO_VERT} fragmentShader={HALO_FRAG} transparent depthWrite={false} blending={THREE.AdditiveBlending} />
      </mesh>
    </group>
  );
}

/** The gate: a bar, and a bolt that travels down and stops once the decision is made (the gate moves only then). */
function Gate() {
  const bolt = useRef<THREE.Mesh>(null);
  const travel = useRef(0);
  const line = useMemo(() => token("--carbon-line", "#3a3846"), []);
  const accent = useMemo(() => token("--c-accent", "#f5a524"), []);
  useFrame((_, dt) => {
    const s = useStory.getState();
    const decided = s.chapter === 3 && s.step >= 2 && s.replay.kind === "ok";
    travel.current += THREE.MathUtils.clamp((decided ? 1 : 0) - travel.current, -dt * 4, dt * 4);
    if (bolt.current) bolt.current.position.y = 1.35 - travel.current * 0.5;
  });
  return (
    <group position={[GATE_X, 0, 0]}>
      <mesh>
        <boxGeometry args={[0.04, 3.2, 0.04]} />
        <meshBasicMaterial color={line} />
      </mesh>
      <mesh ref={bolt} position={[0, 1.35, 0]}>
        <boxGeometry args={[0.16, 0.16, 0.16]} />
        <meshBasicMaterial color={accent} />
      </mesh>
    </group>
  );
}

function Rig({ children }: { children: ReactNode }) {
  const group = useRef<THREE.Group>(null);
  const narrow = useThree((s) => s.size.width < 720);
  useFrame((state) => {
    const p = useStory.getState().progress;
    state.camera.position.z = 7.2 - p * 1.2;
    state.camera.position.x = Math.sin(p * Math.PI) * 0.35;
    state.camera.lookAt(0.2, 0, 0);
    if (group.current) group.current.rotation.y = -0.25 + p * 0.5;
  });
  return (
    <group ref={group} position={narrow ? [-0.9, 1.1, 0] : [0.6, 0, 0]} scale={narrow ? 0.62 : 1}>
      {children}
    </group>
  );
}

/** Advances the R3F loop from the single GSAP ticker; paused while the stage is off screen or the tab is hidden. */
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

export default function StoryScene({ active, light }: { active: React.RefObject<boolean>; light: boolean }) {
  const colors = useMemo(
    () => ({
      ALLOW: token("--sig-allow-lamp", "#3ddc84"),
      REVIEW: token("--sig-review-lamp", "#f5a524"),
      DENY: token("--sig-deny-lamp", "#ff5a4a"),
    }),
    [],
  );
  return (
    <SceneBoundary onFail={() => useStory.setState((s) => ({ caps: { ...s.caps, webgl: false } }))}>
      <Canvas
        frameloop="never"
        dpr={light ? 1 : [1, 1.75]}
        camera={{ fov: 38, position: [0, 0, 7.2] }}
        gl={{ antialias: false, powerPreference: "high-performance", alpha: true }}
        aria-hidden="true"
      >
        <TickerBridge active={active} />
        <Rig>
          <Particles count={light ? 900 : 2600} />
          <Gate />
          <Lamp shape="ALLOW" y={0.75} color={colors.ALLOW} />
          <Lamp shape="REVIEW" y={0} color={colors.REVIEW} />
          <Lamp shape="DENY" y={-0.75} color={colors.DENY} />
        </Rig>
      </Canvas>
    </SceneBoundary>
  );
}
