"use client";
// Beat 3. The policy engine as three notched rings the packet passes through. They idle slowly, and take the colour of
// the REAL decision when the packet is inside (steel while the decision is unknown: the scene does not guess one).
import { useFrame } from "@react-three/fiber";
import { useLayoutEffect, useRef } from "react";
import * as THREE from "three";
import { beatProgress, smooth } from "@/lib/assay";
import { useStory } from "@/lib/site-story";
import { STATION_AT, placeAt, type Pal } from "./common";
import type { SceneModel } from "./model";

const RINGS = [1.7, 2.4, 3.1] as const;
const NOTCHES = 28;

function Ring({ r }: { r: number }) {
  const ticks = useRef<THREE.InstancedMesh>(null);
  useLayoutEffect(() => {
    const m = ticks.current;
    if (!m) return;
    const o = new THREE.Object3D();
    for (let i = 0; i < NOTCHES; i++) {
      const a = (i / NOTCHES) * Math.PI * 2;
      o.position.set(Math.cos(a) * r, Math.sin(a) * r, 0);
      o.rotation.set(0, 0, a);
      o.updateMatrix();
      m.setMatrixAt(i, o.matrix);
    }
    m.instanceMatrix.needsUpdate = true;
  }, [r]);
  return (
    <>
      <mesh>
        <torusGeometry args={[r, 0.012, 6, 140]} />
        <meshBasicMaterial color="#ffffff" />
      </mesh>
      <instancedMesh ref={ticks} args={[undefined, undefined, NOTCHES]} frustumCulled={false}>
        <boxGeometry args={[0.16, 0.014, 0.014]} />
        <meshBasicMaterial color="#ffffff" />
      </instancedMesh>
    </>
  );
}

export function Policy({ pal, model }: { pal: Pal; model: SceneModel }) {
  const root = useRef<THREE.Group>(null);
  const rings = useRef<(THREE.Group | null)[]>([]);
  const tmp = useRef(new THREE.Color());

  useFrame((state) => {
    const st = useStory.getState();
    if (root.current) placeAt(root.current, STATION_AT.policy);
    const bp = beatProgress(st.track, 2);
    const on = smooth(0.1, 0.3, bp) * (1 - 0.6 * smooth(0.5, 0.62, st.track)); // recedes after its beat, stays for the reveal
    const c = tmp.current.copy(pal.line);
    if (model.decision) c.lerp(pal.sig[model.decision], smooth(0.35, 0.65, bp));
    else c.lerp(pal.steel, smooth(0.35, 0.65, bp));
    rings.current.forEach((g, i) => {
      if (!g) return;
      g.rotation.z = state.clock.elapsedTime * (0.12 + i * 0.07) * (i % 2 ? -1 : 1) + bp * (i + 1) * 1.2;
      g.scale.setScalar(Math.max(0.001, on) * (1 + (1 - on) * 0.5));
      g.traverse((o) => {
        const m = (o as THREE.Mesh).material as THREE.MeshBasicMaterial | undefined;
        if (m && "color" in m) m.color.copy(c);
      });
    });
  });

  return (
    <group ref={root}>
      {RINGS.map((r, i) => (
        <group
          key={r}
          ref={(g) => {
            rings.current[i] = g;
          }}
        >
          <Ring r={r} />
        </group>
      ))}
    </group>
  );
}
