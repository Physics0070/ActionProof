"use client";
// The route itself: a dim line for the whole way, and a bright line that grows to the packet, so the path the request
// has PROVEN so far is visible. Survey ticks every few metres give the eye a scale and make speed readable.
import { useFrame } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { routeAt } from "@/lib/assay";
import { useStory } from "@/lib/site-story";
import { ROUTE, placeAt, type Pal } from "./common";

const SEG = 320;

export function Route({ pal, light }: { pal: Pal; light: boolean }) {
  const ticks = useRef<THREE.InstancedMesh>(null);
  // Two lines over the same points: the dim whole route and the bright part proven so far (its draw range grows).
  const lines = useMemo(() => {
    const pts = ROUTE.getPoints(SEG);
    return {
      base: new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: pal.line })),
      lit: new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: pal.bone })),
    };
  }, [pal]);
  useEffect(
    () => () => {
      for (const l of [lines.base, lines.lit]) {
        l.geometry.dispose();
        (l.material as THREE.Material).dispose();
      }
    },
    [lines],
  );

  const tickCount = light ? 60 : 120;
  useLayoutEffect(() => {
    const m = ticks.current;
    if (!m) return;
    const o = new THREE.Object3D();
    for (let i = 0; i < tickCount; i++) {
      placeAt(o, (i + 0.5) / tickCount);
      o.updateMatrix();
      m.setMatrixAt(i, o.matrix);
    }
    m.instanceMatrix.needsUpdate = true;
  }, [tickCount]);

  useFrame(() => {
    lines.lit.geometry.setDrawRange(0, Math.max(2, Math.floor(routeAt(useStory.getState().track) * SEG) + 1));
  });

  return (
    <>
      <primitive object={lines.base} />
      <primitive object={lines.lit} />
      <instancedMesh ref={ticks} args={[undefined, undefined, tickCount]} frustumCulled={false}>
        <boxGeometry args={[0.9, 0.012, 0.012]} />
        <meshBasicMaterial color={pal.line} />
      </instancedMesh>
    </>
  );
}
