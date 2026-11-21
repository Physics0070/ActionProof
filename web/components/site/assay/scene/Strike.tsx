"use client";
// Beat 4, the signature moment. A die drops on the packet and strikes a hallmark (the receipt); the latch behind it
// closes (single use); and, only if the gate really recorded a replay attempt against this request, a ghost copy of the
// receipt comes back, hits the closed latch and bounces in the deny colour.
// The hallmark pattern is drawn from the request hash, so it is the same every time for the same request.
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { beatProgress, smooth } from "@/lib/assay";
import { useStory } from "@/lib/site-story";
import { STATION_AT, placeAt, type Pal } from "./common";
import type { SceneModel } from "./model";
import { RING_FRAG, RING_VERT } from "./shaders";

function hallmark(hash: string, bone: THREE.Color): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const x = c.getContext("2d")!;
  x.clearRect(0, 0, 64, 64);
  x.strokeStyle = `#${bone.getHexString()}`;
  x.fillStyle = x.strokeStyle;
  x.lineWidth = 3;
  x.strokeRect(2, 2, 60, 60);
  for (let i = 0; i < 64; i++) {
    const nib = parseInt(hash[i % hash.length] ?? "0", 16) || 0;
    if ((nib >> (i % 4)) & 1) x.fillRect(8 + (i % 8) * 6, 8 + Math.floor(i / 8) * 6, 5, 5);
  }
  const t = new THREE.CanvasTexture(c);
  t.magFilter = THREE.NearestFilter;
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function Strike({ pal, model }: { pal: Pal; model: SceneModel }) {
  const root = useRef<THREE.Group>(null);
  const die = useRef<THREE.Group>(null);
  const bar = useRef<THREE.Mesh>(null);
  const ghost = useRef<THREE.Group>(null);
  const ghostMat = useRef<THREE.LineBasicMaterial>(null);
  const mark = useRef<THREE.MeshBasicMaterial>(null);
  const ring = useRef<THREE.ShaderMaterial>(null);
  const bounce = useRef<THREE.ShaderMaterial>(null);
  const tex = useMemo(() => hallmark(model.requestHash, pal.white), [model.requestHash, pal.white]);
  useEffect(() => () => tex.dispose(), [tex]);
  const ghostEdges = useMemo(() => new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(0.6, 1)), []);
  const dieEdges = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(0.95, 0.55, 0.95)), []);
  useEffect(() => () => {
    ghostEdges.dispose();
    dieEdges.dispose();
  }, [ghostEdges, dieEdges]);

  useFrame(() => {
    const track = useStory.getState().track;
    const r = root.current;
    if (!r) return;
    r.visible = track > 0.42;
    if (!r.visible) return;
    placeAt(r, STATION_AT.strike);
    const bp = beatProgress(track, 3);
    const fall = Math.pow(smooth(0.28, 0.5, bp), 3); // accelerates, then stops dead: a strike, not a float
    const lift = smooth(0.62, 0.82, bp);
    if (die.current) die.current.position.y = 2.8 - (2.8 - 0.78) * fall + (2.8 - 0.78) * lift * fall;
    if (mark.current) mark.current.opacity = smooth(0.5, 0.56, bp);
    if (ring.current) ring.current.uniforms.uT!.value = Math.min(1, Math.max(0, (bp - 0.5) / 0.3));
    if (bar.current) bar.current.position.y = 1.4 - 1.35 * smooth(0.55, 0.66, bp);
    if (ghost.current) {
      const out = smooth(0.82, 0.95, bp);
      const into = smooth(0.7, 0.82, bp);
      ghost.current.position.z = 5 - 3.95 * into + 3.9 * out;
      ghost.current.visible = model.bounce && bp > 0.68 && bp < 0.97;
      if (ghostMat.current) ghostMat.current.opacity = smooth(0.68, 0.74, bp) * (1 - smooth(0.93, 0.97, bp));
    }
    if (bounce.current) bounce.current.uniforms.uT!.value = model.bounce ? Math.min(1, Math.max(0, (bp - 0.82) / 0.14)) : 1;
  });

  const ringU = (c: THREE.Color) => ({ uColor: { value: c }, uT: { value: 1 } });
  return (
    <group ref={root} visible={false}>
      <group ref={die} position={[0, 2.8, 0]}>
        <mesh>
          <boxGeometry args={[0.95, 0.55, 0.95]} />
          <meshBasicMaterial color={pal.ground} />
        </mesh>
        <lineSegments geometry={dieEdges}>
          <lineBasicMaterial color={pal.bone} />
        </lineSegments>
      </group>
      <mesh position={[0, 1.02, 0]}>
        <planeGeometry args={[0.6, 0.6]} />
        <meshBasicMaterial ref={mark} map={tex} transparent opacity={0} depthWrite={false} />
      </mesh>
      <mesh>
        <planeGeometry args={[4.4, 4.4]} />
        <shaderMaterial ref={ring} vertexShader={RING_VERT} fragmentShader={RING_FRAG} uniforms={ringU(pal.white)} transparent depthWrite={false} blending={THREE.AdditiveBlending} />
      </mesh>
      {/* the latch: two posts and a bar that closes behind the packet (single use) */}
      {[-1.7, 1.7].map((x) => (
        <mesh key={x} position={[x, 0, 0.9]}>
          <boxGeometry args={[0.1, 2.8, 0.1]} />
          <meshBasicMaterial color={pal.line} />
        </mesh>
      ))}
      <mesh ref={bar} position={[0, 1.4, 0.9]}>
        <boxGeometry args={[3.4, 0.1, 0.1]} />
        <meshBasicMaterial color={pal.bone} />
      </mesh>
      <mesh position={[0, 0, 0.95]}>
        <planeGeometry args={[4.4, 4.4]} />
        <shaderMaterial ref={bounce} vertexShader={RING_VERT} fragmentShader={RING_FRAG} uniforms={ringU(pal.deny)} transparent depthWrite={false} blending={THREE.AdditiveBlending} />
      </mesh>
      <group ref={ghost} position={[0, 0, 5]} visible={false}>
        <lineSegments geometry={ghostEdges}>
          <lineBasicMaterial ref={ghostMat} color={pal.deny} transparent opacity={0} />
        </lineSegments>
      </group>
    </group>
  );
}
