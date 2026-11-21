"use client";
// The request: a point of light that wobbles while it is unproven, settles once its evidence is checked, takes the
// colour of the policy decision, and turns white-hot when the receipt is struck. All of that is driven by the track.
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { routeAt, smooth } from "@/lib/assay";
import { useStory } from "@/lib/site-story";
import { placeAt, type Pal } from "./common";
import type { SceneModel } from "./model";
import { PACKET_FRAG, PACKET_VERT } from "./shaders";

export function Packet({ pal, model }: { pal: Pal; model: SceneModel }) {
  const g = useRef<THREE.Group>(null);
  const spin = useRef<THREE.Group>(null);
  const core = useRef<THREE.ShaderMaterial>(null);
  const halo = useRef<THREE.ShaderMaterial>(null);
  const wire = useRef<THREE.LineBasicMaterial>(null);
  const edges = useMemo(() => new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(0.6, 1)), []);
  useEffect(() => () => edges.dispose(), [edges]);
  const tint = useMemo(() => new THREE.Color(), []);

  useFrame((state) => {
    const st = useStory.getState();
    const t = state.clock.elapsedTime;
    const track = st.track;
    if (g.current) {
      placeAt(g.current, routeAt(track));
      g.current.position.y += Math.sin(t * 1.3) * 0.05; // idle: the packet breathes while nothing is happening
    }
    if (spin.current) spin.current.rotation.set(t * 0.31, t * 0.47, 0);
    // colour: bone while unproven -> the decision's colour once policy has run -> white-hot after the strike
    tint.copy(pal.bone);
    if (model.decision) tint.lerp(pal.sig[model.decision], smooth(0.36, 0.46, track));
    tint.lerp(pal.white, smooth(0.58, 0.66, track));
    const instab = 0.22 * (1 - smooth(0.18, 0.4, track));
    for (const m of [core.current, halo.current]) {
      if (!m) continue;
      m.uniforms.uTime!.value = t;
      m.uniforms.uInstab!.value = instab;
      (m.uniforms.uColor!.value as THREE.Color).copy(tint);
    }
    if (wire.current) wire.current.color.copy(tint);
  });

  const uniforms = (level: number) => ({ uTime: { value: 0 }, uInstab: { value: 0.22 }, uLevel: { value: level }, uColor: { value: new THREE.Color(pal.bone) } });
  return (
    <group ref={g}>
      <group ref={spin}>
        <mesh>
          <icosahedronGeometry args={[0.42, 2]} />
          <shaderMaterial ref={core} vertexShader={PACKET_VERT} fragmentShader={PACKET_FRAG} uniforms={uniforms(1)} transparent depthWrite={false} blending={THREE.AdditiveBlending} />
        </mesh>
        <lineSegments geometry={edges}>
          <lineBasicMaterial ref={wire} color={pal.bone} transparent opacity={0.9} />
        </lineSegments>
      </group>
      <mesh scale={1.7}>
        <icosahedronGeometry args={[0.42, 1]} />
        <shaderMaterial ref={halo} vertexShader={PACKET_VERT} fragmentShader={PACKET_FRAG} uniforms={uniforms(0.16)} transparent depthWrite={false} side={THREE.BackSide} blending={THREE.AdditiveBlending} />
      </mesh>
    </group>
  );
}
