"use client";
// Beat 2. One node per claim of the recorded request, in the three kinds the gate distinguishes:
//   DIRECT   a solid node pinned to a document sheet by a stem (the value was re-read at its cited span)
//   DERIVED  a ringed node wired to the nodes it was computed from (the gate recomputes it; the model never does)
//   ASSERTED a hollow node on a dashed line that ends in nothing (a claim with no source)
// A claim whose verification FAILED is drawn in the deny colour. Nodes light up one after another as beat 2 plays.
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { beatProgress, smooth } from "@/lib/assay";
import { useStory } from "@/lib/site-story";
import { STATION_AT, placeAt, type Pal } from "./common";
import type { ClaimNode, SceneModel } from "./model";

function layout(n: number): THREE.Vector3[] {
  return Array.from({ length: n }, (_, i) => {
    const a = (n === 1 ? 0 : i / (n - 1) - 0.5) * 2.3;
    return new THREE.Vector3(Math.sin(a) * 3.6, ((i % 3) - 1) * 0.8, 1.2 - Math.cos(a) * 1.5);
  });
}

function colourOf(c: ClaimNode, pal: Pal): THREE.Color {
  if (c.ok === false) return pal.deny;
  return c.kind === "ASSERTED" ? pal.steel : pal.bone;
}

function Node({ c, at, pal, reg }: { c: ClaimNode; at: THREE.Vector3; pal: Pal; reg: (g: THREE.Group | null) => void }) {
  const col = colourOf(c, pal);
  const sheet = useMemo(() => new THREE.EdgesGeometry(new THREE.PlaneGeometry(0.8, 1.05)), []);
  const stem = useMemo(() => new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 0, -1.1)]), []);
  const tail = useMemo(() => {
    const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, 0, 0), new THREE.Vector3(0.9, 0.5, -2.4)]);
    return g;
  }, []);
  const dashed = useMemo(() => {
    const l = new THREE.Line(tail, new THREE.LineDashedMaterial({ color: pal.steel, dashSize: 0.12, gapSize: 0.1 }));
    l.computeLineDistances();
    return l;
  }, [tail, pal.steel]);
  useEffect(
    () => () => {
      sheet.dispose();
      stem.dispose();
      tail.dispose();
      dashed.material instanceof THREE.Material && dashed.material.dispose();
    },
    [sheet, stem, tail, dashed],
  );
  return (
    <group ref={reg} position={at} scale={0.001}>
      {c.kind === "DIRECT" ? (
        <>
          <mesh>
            <octahedronGeometry args={[0.26]} />
            <meshBasicMaterial color={col} />
          </mesh>
          <lineSegments geometry={sheet} position={[0, 0, -1.1]}>
            <lineBasicMaterial color={pal.line} />
          </lineSegments>
          <line>
            <primitive object={stem} attach="geometry" />
            <lineBasicMaterial color={col} />
          </line>
        </>
      ) : null}
      {c.kind === "DERIVED" ? (
        <>
          <mesh>
            <octahedronGeometry args={[0.24]} />
            <meshBasicMaterial color={col} wireframe />
          </mesh>
          <mesh>
            <torusGeometry args={[0.42, 0.012, 6, 48]} />
            <meshBasicMaterial color={col} />
          </mesh>
        </>
      ) : null}
      {c.kind === "ASSERTED" ? (
        <>
          <mesh>
            <icosahedronGeometry args={[0.27, 0]} />
            <meshBasicMaterial color={col} wireframe transparent opacity={0.7} />
          </mesh>
          <primitive object={dashed} />
        </>
      ) : null}
    </group>
  );
}

export function Evidence({ pal, model }: { pal: Pal; model: SceneModel }) {
  const root = useRef<THREE.Group>(null);
  const nodes = useRef<(THREE.Group | null)[]>([]);
  const at = useMemo(() => layout(model.claims.length), [model.claims.length]);
  const wires = useMemo(() => {
    const idx = new Map(model.claims.map((c, i) => [c.name, i]));
    const pts: THREE.Vector3[] = [];
    model.claims.forEach((c, i) => {
      if (c.kind !== "DERIVED") return;
      for (const name of c.inputs) {
        const j = idx.get(name);
        if (j !== undefined) pts.push(at[i]!, at[j]!);
      }
    });
    return new THREE.BufferGeometry().setFromPoints(pts);
  }, [model.claims, at]);
  useEffect(() => () => wires.dispose(), [wires]);

  useFrame((state) => {
    const st = useStory.getState();
    if (root.current) placeAt(root.current, STATION_AT.evidence);
    const bp = beatProgress(st.track, 1);
    const near = smooth(0.0, 0.2, st.track) * (1 - 0.65 * smooth(0.5, 0.62, st.track)); // recedes after the policy beat, never vanishes (the reveal shows it all)
    nodes.current.forEach((g, i) => {
      if (!g) return;
      const lit = smooth(0.12 + i * 0.07, 0.3 + i * 0.07, bp);
      const k = Math.max(0.001, lit * (0.35 + 0.65 * near));
      g.scale.setScalar(k);
      g.rotation.y = state.clock.elapsedTime * 0.4 + i;
    });
  });

  return (
    <group ref={root}>
      {model.claims.map((c, i) => (
        <Node
          key={c.name}
          c={c}
          at={at[i]!}
          pal={pal}
          reg={(g) => {
            nodes.current[i] = g;
          }}
        />
      ))}
      <lineSegments geometry={wires}>
        <lineBasicMaterial color={pal.bone} transparent opacity={0.55} />
      </lineSegments>
    </group>
  );
}
