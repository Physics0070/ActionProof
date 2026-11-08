"use client";
// The one 3D scene (next/dynamic, ssr:false). Procedural only: lines, boxes, one shader. No textures, no models.
// A request packet (carrying one chip per real claim) travels a corridor toward a bulkhead door. Everything reads the
// single driver (lib/site-story.ts) with getState() in useFrame and is advanced from the one GSAP ticker.
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import gsap from "gsap";
import { Component, useEffect, useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import { DOOR_Z, RING_Z, frame } from "@/lib/gate-timeline";
import { useStory } from "@/lib/site-story";

type Decision = "ALLOW" | "REVIEW" | "DENY";

function token(name: string, fallback: string): THREE.Color {
  const v = typeof document === "undefined" ? "" : getComputedStyle(document.body).getPropertyValue(name).trim();
  return new THREE.Color(v || fallback);
}
type Palette = { edge: THREE.Color; leaf: THREE.Color; ground: THREE.Color; line: THREE.Color; accent: THREE.Color; steel: THREE.Color; sig: Record<Decision, THREE.Color> };
function usePalette(): Palette {
  return useMemo(
    () => ({
      edge: token("--carbon-muted", "#a4c9be"),
      leaf: token("--carbon-line", "#2d6157").lerp(token("--carbon-raised", "#11403a"), 0.3),
      ground: token("--carbon", "#0a2b26"),
      line: token("--carbon-line", "#2d6157"),
      accent: token("--c-accent", "#ff3d9a"),
      steel: token("--carbon-raised", "#11403a"),
      sig: { ALLOW: token("--sig-allow-lamp", "#34f0c2"), REVIEW: token("--sig-review-lamp", "#ffd11a"), DENY: token("--sig-deny-lamp", "#ff7d52") },
    }),
    [],
  );
}

const HALO_VERT = /* glsl */ `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const HALO_FRAG = /* glsl */ `
  uniform vec3 uColor; uniform float uLevel; varying vec2 vUv;
  void main() { float d = distance(vUv, vec2(0.5)) * 2.0; float a = pow(max(0.0, 1.0 - d), 1.6) * uLevel; gl_FragColor = vec4(uColor, a); }`;

function Corridor({ pal, light }: { pal: Palette; light: boolean }) {
  const geo = useMemo(() => {
    const pts: number[] = [];
    const w = 2.6, h = 1.8;
    const n = light ? 20 : 28;
    for (let i = 0; i < n; i++) {
      const z = 44 - i * 2.4;
      const c: [number, number][] = [[-w, -h], [w, -h], [w, h], [-w, h]];
      for (let k = 0; k < 4; k++) {
        const a = c[k]!, b = c[(k + 1) % 4]!;
        pts.push(a[0], a[1], z, b[0], b[1], z);
      }
    }
    for (const [x, y] of [[-w, -h], [w, -h], [w, h], [-w, h]] as const) pts.push(x, y, 44, x, y, 44 - n * 2.4);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    return g;
  }, [light]);
  return (
    <>
      <lineSegments geometry={geo}>
        <lineBasicMaterial color={pal.line} />
      </lineSegments>
      <gridHelper args={[90, 36, pal.line, pal.line]} position={[0, -1.8, -6]} />
    </>
  );
}

function Door({ pal }: { pal: Palette }) {
  const left = useRef<THREE.Group>(null);
  const right = useRef<THREE.Group>(null);
  const bolts = useRef<THREE.Group>(null);
  const halo = useRef<THREE.ShaderMaterial>(null);
  const lamp = useRef<THREE.PointLight>(null);
  const seam = useRef<THREE.MeshBasicMaterial>(null);
  const uniforms = useMemo(() => ({ uColor: { value: new THREE.Color() }, uLevel: { value: 0 } }), []);
  const tmp = useMemo(() => new THREE.Color(), []);
  useFrame((state) => {
    const s = useStory.getState();
    const f = frame(s.gate, s.verified);
    const live = s.chapter >= 2;
    const door = live ? f.door : 0;
    const rep = s.replay.kind === "ok" ? s.replay.data : null;
    const dec = (rep?.decision as Decision | undefined) ?? "REVIEW";
    const fin: Decision = rep?.status === "executed" ? "ALLOW" : rep?.status === "rejected" ? "DENY" : dec;
    tmp.copy(pal.sig[dec in pal.sig ? dec : "REVIEW"]).lerp(pal.sig[fin], live && f.light === 2 ? 1 : 0);
    const t = state.clock.elapsedTime;
    const idle = 0.5 + 0.5 * Math.sin(t * 1.6);
    const level = live ? f.lightLevel * (0.85 + 0.15 * idle) : 0;
    if (left.current) left.current.position.x = -0.78 - door * 1.15;
    if (right.current) right.current.position.x = 0.78 + door * 1.15;
    if (bolts.current) bolts.current.scale.x = 1 - Math.min(1, door * 4) * 0.9;
    const hu = halo.current?.uniforms;
    if (hu) {
      (hu.uColor!.value as THREE.Color).copy(tmp);
      hu.uLevel!.value = level;
    }
    if (lamp.current) {
      lamp.current.color.copy(tmp);
      lamp.current.intensity = level * 60 * (live ? 1 : 0);
    }
    if (seam.current) seam.current.color.copy(pal.accent).multiplyScalar(door < 0.02 ? 0.45 + 0.25 * idle : 0.1);
  });
  const frameMat = <meshStandardMaterial color={pal.line} metalness={0.55} roughness={0.5} />;
  return (
    <group position={[0, 0, DOOR_Z]}>
      <mesh position={[0, 0, -0.6]}>
        <planeGeometry args={[7, 5.5]} />
        <shaderMaterial ref={halo} uniforms={uniforms} vertexShader={HALO_VERT} fragmentShader={HALO_FRAG} transparent depthWrite={false} blending={THREE.AdditiveBlending} />
      </mesh>
      <pointLight ref={lamp} position={[0, 0, -1.2]} distance={14} decay={2} intensity={0} />
      {/* bezel */}
      <mesh position={[0, 2.05, 0]}><boxGeometry args={[4.6, 0.35, 0.5]} />{frameMat}</mesh>
      <mesh position={[0, -2.05, 0]}><boxGeometry args={[4.6, 0.35, 0.5]} />{frameMat}</mesh>
      <mesh position={[-2.15, 0, 0]}><boxGeometry args={[0.35, 4.2, 0.5]} />{frameMat}</mesh>
      <mesh position={[2.15, 0, 0]}><boxGeometry args={[0.35, 4.2, 0.5]} />{frameMat}</mesh>
      {/* leaves */}
      <group ref={left} position={[-0.78, 0, 0]}>
        <mesh><boxGeometry args={[1.56, 3.75, 0.3]} /><meshStandardMaterial color={pal.leaf} metalness={0.4} roughness={0.55} /></mesh>
        <lineSegments><edgesGeometry args={[new THREE.BoxGeometry(1.56, 3.75, 0.3)]} /><lineBasicMaterial color={pal.edge} /></lineSegments>
      </group>
      <group ref={right} position={[0.78, 0, 0]}>
        <mesh><boxGeometry args={[1.56, 3.75, 0.3]} /><meshStandardMaterial color={pal.leaf} metalness={0.4} roughness={0.55} /></mesh>
        <lineSegments><edgesGeometry args={[new THREE.BoxGeometry(1.56, 3.75, 0.3)]} /><lineBasicMaterial color={pal.edge} /></lineSegments>
      </group>
      {/* the seam glows in the packet colour while the door is shut */}
      <mesh position={[0, 0, 0.17]}>
        <planeGeometry args={[0.06, 3.75]} />
        <meshBasicMaterial ref={seam} toneMapped={false} />
      </mesh>
      {/* latch bolts: they retract (and stop hard) when the door opens */}
      <group ref={bolts}>
        {[-1.2, 0, 1.2].map((y) => (
          <mesh key={y} position={[0, y, 0.2]}>
            <boxGeometry args={[0.9, 0.12, 0.1]} />
            <meshBasicMaterial color={pal.accent} toneMapped={false} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

function Rings({ pal }: { pal: Palette }) {
  const mats = useRef<(THREE.MeshBasicMaterial | null)[]>([]);
  const groups = useRef<(THREE.Mesh | null)[]>([]);
  const tmp = useMemo(() => new THREE.Color(), []);
  useFrame((state) => {
    const s = useStory.getState();
    const f = frame(s.gate, s.verified);
    const live = s.chapter >= 2;
    RING_Z.forEach((_, i) => {
      const b = live ? Math.max(0, 1 - Math.abs(f.packetZ - RING_Z[i]!) / 4) : 0;
      mats.current[i]?.color.copy(pal.line).lerp(tmp.copy(pal.accent), b);
      const m = groups.current[i];
      if (m) {
        m.scale.setScalar(1 + 0.025 * Math.sin(state.clock.elapsedTime * 1.3 + i));
        m.visible = state.camera.position.z - RING_Z[i]! > 3;
      }
    });
  });
  return (
    <>
      {RING_Z.map((z, i) => (
        <mesh key={z} position={[0, 0, z]} rotation={[0, 0, Math.PI / 4]} ref={(m) => void (groups.current[i] = m)}>
          <ringGeometry args={[2.5, 2.56, 4]} />
          <meshBasicMaterial ref={(m) => void (mats.current[i] = m)} toneMapped={false} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </>
  );
}

function Packet({ pal, chips }: { pal: Palette; chips: number }) {
  const group = useRef<THREE.Group>(null);
  const chipRefs = useRef<(THREE.Mesh | null)[]>([]);
  const trail = useRef<THREE.Points>(null);
  const trailGeo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(70 * 3), 3));
    return g;
  }, []);
  useFrame((state) => {
    const s = useStory.getState();
    const t = state.clock.elapsedTime;
    const live = s.chapter >= 2;
    const f = frame(s.gate, s.verified);
    const z = live ? f.packetZ : 33 - ((t * 2.4) % 15);
    const vis = live ? f.packetVisible : 1;
    if (group.current) {
      group.current.position.set(0, 0.1 + 0.07 * Math.sin(t * 2), z);
      group.current.scale.setScalar(Math.max(0.001, vis));
      group.current.rotation.y = t * 0.9;
    }
    chipRefs.current.forEach((m, i) => {
      if (!m) return;
      const a = t * 1.1 + (i / Math.max(1, chips)) * Math.PI * 2;
      m.position.set(Math.cos(a) * 0.62, Math.sin(a) * 0.62, 0);
      m.rotation.z = a;
    });
    const pos = trailGeo.getAttribute("position") as THREE.BufferAttribute;
    for (let i = 0; i < 70; i++) pos.setXYZ(i, Math.sin(i * 12.9) * 0.18 * (i / 70), Math.cos(i * 7.7) * 0.18 * (i / 70), z + 0.4 + i * 0.07);
    pos.needsUpdate = true;
    if (trail.current) trail.current.visible = vis > 0.05;
  });
  return (
    <>
      <group ref={group}>
        <mesh>
          <icosahedronGeometry args={[0.24, 1]} />
          <meshBasicMaterial color={pal.accent} toneMapped={false} />
        </mesh>
        <mesh>
          <icosahedronGeometry args={[0.36, 1]} />
          <meshBasicMaterial color={pal.accent} wireframe transparent opacity={0.5} toneMapped={false} />
        </mesh>
        {Array.from({ length: chips }).map((_, i) => (
          <mesh key={i} ref={(m) => void (chipRefs.current[i] = m)}>
            <boxGeometry args={[0.16, 0.1, 0.02]} />
            <meshBasicMaterial color="#eef8f3" toneMapped={false} />
          </mesh>
        ))}
      </group>
      <points ref={trail} geometry={trailGeo}>
        <pointsMaterial color={pal.accent} size={0.07} sizeAttenuation transparent opacity={0.7} depthWrite={false} />
      </points>
    </>
  );
}

/** The receipt copy: it returns at the closed door and bounces in the DENY colour. */
function Ghost({ pal }: { pal: Palette }) {
  const mesh = useRef<THREE.Mesh>(null);
  const mat = useRef<THREE.MeshBasicMaterial>(null);
  const shock = useRef<THREE.Mesh>(null);
  const shockMat = useRef<THREE.MeshBasicMaterial>(null);
  useFrame((state) => {
    const s = useStory.getState();
    const f = frame(s.gate, s.verified);
    const live = s.chapter >= 2 && s.gate > 0.8;
    if (mesh.current) {
      mesh.current.visible = live;
      mesh.current.position.set(0, 0.1, f.ghostZ);
      mesh.current.rotation.y = state.clock.elapsedTime * 1.4;
    }
    if (mat.current) mat.current.color.copy(f.ghostZ < 2.5 ? pal.sig.DENY : pal.accent);
    const k = s.gate > 0.9 ? Math.min(1, (s.gate - 0.9) * 8) : 0;
    if (shock.current) {
      shock.current.visible = live && k > 0;
      shock.current.scale.setScalar(0.4 + k * 2.2);
    }
    if (shockMat.current) shockMat.current.opacity = (1 - k) * 0.9 * (f.flash > 0 ? 1 : 0);
  });
  return (
    <>
      <mesh ref={mesh} visible={false}>
        <octahedronGeometry args={[0.3, 0]} />
        <meshBasicMaterial ref={mat} wireframe toneMapped={false} />
      </mesh>
      <mesh ref={shock} position={[0, 0, 0.6]} visible={false}>
        <ringGeometry args={[0.9, 1, 4]} />
        <meshBasicMaterial ref={shockMat} color={pal.sig.DENY} transparent toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
    </>
  );
}

/** Audit chain: one block per recorded entry; the entry that recorded the replay is DENY. */
function Chain({ pal, count, denyIndex }: { pal: Palette; count: number; denyIndex: number }) {
  const refs = useRef<(THREE.Mesh | null)[]>([]);
  useFrame(() => {
    const s = useStory.getState();
    const f = frame(s.gate, s.verified);
    const live = s.chapter >= 2;
    refs.current.forEach((m, i) => {
      if (!m) return;
      const on = live && f.chain * count > i;
      m.scale.setScalar(on ? 1 : 0.001);
    });
  });
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <mesh key={i} ref={(m) => void (refs.current[i] = m)} position={[-2.1, -1.62, 9 - i * 0.75]}>
          <boxGeometry args={[0.34, 0.16, 0.5]} />
          <meshBasicMaterial color={i === denyIndex ? pal.sig.DENY : pal.sig.ALLOW} toneMapped={false} />
        </mesh>
      ))}
    </>
  );
}

function Rig({ children }: { children: ReactNode }) {
  const wide = useThree((s) => s.size.width >= 720);
  const ready = useRef(false);
  const group = useRef<THREE.Group>(null);
  useFrame((state) => {
    const s = useStory.getState();
    const t = state.clock.elapsedTime;
    const live = s.chapter >= 2;
    const z = live ? frame(s.gate, s.verified).camZ : 40 - s.hero * 3;
    state.camera.position.set(Math.sin(t * 0.25) * 0.25, 0.35 + Math.sin(t * 0.31) * 0.05, z);
    state.camera.lookAt(0, 0.1, -6);
    if (group.current) {
      const tx = wide ? (live ? 2.4 : 3.8) : 0;
      group.current.position.x += (tx - group.current.position.x) * 0.08;
      group.current.position.y = wide ? 0 : live ? 3.4 : 2.2;
    }
    if (!ready.current) {
      ready.current = true;
      window.dispatchEvent(new Event("gate-ready"));
    }
  });
  return <group ref={group} position={wide ? [3.8, 0, 0] : [0, 3.4, 0]}>{children}</group>;
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
  const data = replay.kind === "ok" ? replay.data : null;
  const chips = Math.min(12, data?.claims.length ?? 6);
  const first = data?.audit.first_seq ?? 1;
  const count = data && data.audit.last_seq !== null && data.audit.first_seq !== null ? Math.min(24, data.audit.last_seq - data.audit.first_seq + 1) : 0;
  const bounce = data?.replay_attempts[0]?.seq;
  return (
    <>
      <TickerBridge active={active} />
      <fog attach="fog" args={[pal.ground, 18, 60]} />
      <ambientLight intensity={0.9} />
      <directionalLight position={[2, 4, 8]} intensity={1.6} />
      <Rig>
        <Corridor pal={pal} light={light} />
        <Rings pal={pal} />
        <Door pal={pal} />
        <Packet pal={pal} chips={chips} />
        <Ghost pal={pal} />
        {count > 0 ? <Chain pal={pal} count={count} denyIndex={bounce !== undefined ? bounce - first : -1} /> : null}
      </Rig>
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

export default function GateScene({ active, light }: { active: React.RefObject<boolean>; light: boolean }) {
  return (
    <SceneBoundary onFail={() => useStory.setState((s) => ({ caps: { ...s.caps, webgl: false } }))}>
      <Canvas frameloop="never" dpr={light ? 1 : [1, 1.75]} camera={{ fov: light ? 52 : 40, position: [0, 0.3, 40], near: 0.1, far: 90 }} gl={{ antialias: !light, alpha: true, powerPreference: "high-performance" }} aria-hidden="true">
        <Inner active={active} light={light} />
      </Canvas>
    </SceneBoundary>
  );
}
