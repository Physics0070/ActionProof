"use client";
// Beat 5. The route ahead of the strike becomes the audit chain: one linked block per audit entry of this request, a
// signed-checkpoint ring every few entries, and a pulse that runs the whole chain (the verifier). The block that
// recorded the replay bounce (when the gate really recorded one) is drawn in the deny colour.
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { beatProgress, smooth } from "@/lib/assay";
import { useStory } from "@/lib/site-story";
import { ROUTE, placeAt, type Pal } from "./common";
import type { SceneModel } from "./model";

const FROM = 0.68;
const CHECK_EVERY = 4;

/** Route parameter of block i: fixed spacing, squeezed only if the chain is long (the last block sits at the packet). */
const at = (i: number, n: number) => FROM + i * Math.min(0.018, 0.3 / Math.max(1, n));

export function Chain({ pal, model }: { pal: Pal; model: SceneModel }) {
  const n = model.chain;
  const blocks = useRef<(THREE.Group | null)[]>([]);
  const checks = useRef<(THREE.Mesh | null)[]>([]);
  const pulse = useRef<THREE.Mesh>(null);
  const edges = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(0.95, 0.95, 0.22)), []);
  const lines = useMemo(
    () => ({
      dim: new THREE.LineBasicMaterial({ color: pal.steel.clone().multiplyScalar(0.6) }),
      lit: new THREE.LineBasicMaterial({ color: pal.bone }),
      deny: new THREE.LineBasicMaterial({ color: pal.deny }),
    }),
    [pal],
  );
  useEffect(
    () => () => {
      edges.dispose();
      Object.values(lines).forEach((m) => m.dispose());
    },
    [edges, lines],
  );
  const link = useMemo(() => new THREE.BufferGeometry().setFromPoints(Array.from({ length: Math.max(2, n) }, (_, i) => ROUTE.getPointAt(Math.min(1, at(i, n))))), [n]);
  const linkLine = useMemo(() => new THREE.Line(link, new THREE.LineBasicMaterial({ color: pal.steel, transparent: true, opacity: 0.6 })), [link, pal]);
  useEffect(
    () => () => {
      link.dispose();
      (linkLine.material as THREE.Material).dispose();
    },
    [link, linkLine],
  );
  const o = useMemo(() => new THREE.Object3D(), []);

  useFrame(() => {
    const track = useStory.getState().track;
    const bp = beatProgress(track, 4);
    const show = track > 0.5;
    const litCount = Math.floor(smooth(0.1, 0.8, bp) * n + 0.0001);
    blocks.current.forEach((g, i) => {
      if (!g) return;
      placeAt(o, Math.min(1, at(i, n)));
      g.position.copy(o.position);
      g.quaternion.copy(o.quaternion);
      const isLit = i < litCount || track > 0.9;
      const hot = i === model.denyIndex && isLit;
      const line = g.children[1] as THREE.LineSegments;
      line.material = hot ? lines.deny : isLit ? lines.lit : lines.dim;
      const k = (isLit ? 1 : 0.7) * (hot ? 1.25 : 1);
      g.scale.setScalar(k);
      g.visible = show;
    });
    checks.current.forEach((m, i) => {
      if (!m) return;
      const bi = Math.min(n - 1, (i + 1) * CHECK_EVERY - 1);
      placeAt(o, Math.min(1, at(bi, n)));
      m.position.copy(o.position);
      m.quaternion.copy(o.quaternion);
      m.visible = show && (bi < litCount || track > 0.9);
    });
    if (pulse.current) {
      const u = smooth(0.82, 1, bp);
      pulse.current.visible = show && u > 0 && u < 1;
      placeAt(o, Math.min(1, at(0, n) + (at(Math.max(0, n - 1), n) - at(0, n)) * u));
      pulse.current.position.copy(o.position);
    }
  });

  const checkCount = Math.floor(n / CHECK_EVERY);
  return (
    <group>
      <primitive object={linkLine} />
      {Array.from({ length: n }, (_, i) => (
        <group
          key={i}
          ref={(g) => {
            blocks.current[i] = g;
          }}
          visible={false}
        >
          <mesh>
            <boxGeometry args={[0.95, 0.95, 0.22]} />
            <meshBasicMaterial color={pal.ground} />
          </mesh>
          <lineSegments geometry={edges} material={lines.dim} />
        </group>
      ))}
      {Array.from({ length: checkCount }, (_, i) => (
        <mesh
          key={`c${i}`}
          ref={(m) => {
            checks.current[i] = m;
          }}
          visible={false}
        >
          <torusGeometry args={[0.95, 0.018, 6, 48]} />
          <meshBasicMaterial color={pal.white} />
        </mesh>
      ))}
      <mesh ref={pulse} visible={false}>
        <sphereGeometry args={[0.14, 12, 12]} />
        <meshBasicMaterial color={pal.white} />
      </mesh>
    </group>
  );
}
