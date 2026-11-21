"use client";
// The unproven world: a drifting dust cloud hugging the route. It is thick at the start and thins as proofs complete.
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { smooth } from "@/lib/assay";
import { useStory } from "@/lib/site-story";
import { ROUTE, type Pal } from "./common";
import { DUST_FRAG, DUST_VERT } from "./shaders";

export function Dust({ pal, light }: { pal: Pal; light: boolean }) {
  const count = light ? 900 : 2600;
  const mat = useRef<THREE.ShaderMaterial>(null);
  const geo = useMemo(() => {
    const pos = new Float32Array(count * 3);
    const seed = new Float32Array(count);
    const p = new THREE.Vector3();
    // deterministic scatter (no Math.random in render: same cloud every visit, stable under StrictMode)
    let s = 7;
    const rnd = () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646;
    for (let i = 0; i < count; i++) {
      ROUTE.getPointAt(i % 3 === 0 ? rnd() * 0.22 : rnd(), p); // a third of the dust crowds the start: the unproven world
      const r = 1.6 + rnd() * 14;
      const a = rnd() * Math.PI * 2;
      pos[i * 3] = p.x + Math.cos(a) * r;
      pos[i * 3 + 1] = p.y + (rnd() - 0.5) * r * 0.8;
      pos[i * 3 + 2] = p.z + Math.sin(a) * r;
      seed[i] = rnd();
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
    return g;
  }, [count]);
  useEffect(() => () => geo.dispose(), [geo]);

  useFrame((state) => {
    const m = mat.current;
    if (!m) return;
    m.uniforms.uTime!.value = state.clock.elapsedTime;
    m.uniforms.uClarity!.value = smooth(0.1, 0.85, useStory.getState().track);
  });

  return (
    <points geometry={geo} frustumCulled={false}>
      <shaderMaterial
        ref={mat}
        vertexShader={DUST_VERT}
        fragmentShader={DUST_FRAG}
        uniforms={{ uTime: { value: 0 }, uClarity: { value: 0 }, uSize: { value: light ? 2.8 : 2.2 }, uColor: { value: pal.steel } }}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}
