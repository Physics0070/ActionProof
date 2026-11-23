// Shared scene constants: the one route every beat sits on, the palette read from the page's CSS tokens, and helpers
// to stand an object on the route (local -Z is the direction of travel, +Y is up, +X is to the right).
import { useMemo } from "react";
import * as THREE from "three";
import type { BeatId } from "@/lib/assay";

export type Decision = "ALLOW" | "REVIEW" | "DENY";

/** A lazy S through the dark, from the viewer into the distance. World units are roughly metres. */
export const ROUTE = new THREE.CatmullRomCurve3(
  [
    new THREE.Vector3(-5, 0, 34),
    new THREE.Vector3(-2.5, 0.4, 20),
    new THREE.Vector3(3, 0.9, 8),
    new THREE.Vector3(2.5, 0.3, -4),
    new THREE.Vector3(-3, 1.1, -16),
    new THREE.Vector3(-2, 0.5, -28),
    new THREE.Vector3(3.5, 1.4, -42),
    new THREE.Vector3(1, 0.6, -58),
  ],
  false,
  "catmullrom",
  0.5,
);

export type Pal = {
  ground: THREE.Color;
  bone: THREE.Color;
  steel: THREE.Color;
  line: THREE.Color;
  white: THREE.Color;
  deny: THREE.Color;
  review: THREE.Color;
  allow: THREE.Color;
  sig: Record<Decision, THREE.Color>;
};

function token(root: Element, name: string, fallback: string): THREE.Color {
  const v = getComputedStyle(root).getPropertyValue(name).trim();
  return new THREE.Color(v || fallback);
}

/** Palette from the `.assay` tokens (one source of truth: assay.css). Falls back to the same literals. */
export function usePalette(): Pal {
  return useMemo(() => {
    const root = document.querySelector(".assay") ?? document.body;
    const deny = token(root, "--as-deny", "#ee5a3c");
    const review = token(root, "--as-review", "#f2b544");
    const allow = token(root, "--as-allow", "#4fd1b0");
    return {
      ground: token(root, "--as-ground", "#0a0908"),
      bone: token(root, "--as-bone", "#efe8da"),
      steel: token(root, "--as-steel", "#a39a8c"),
      line: token(root, "--as-line", "#2e2721"),
      white: new THREE.Color("#ffffff"),
      deny,
      review,
      allow,
      sig: { ALLOW: allow, REVIEW: review, DENY: deny },
    };
  }, []);
}

const UP = new THREE.Vector3(0, 1, 0);
const m4 = new THREE.Matrix4();
const p = new THREE.Vector3();
const q = new THREE.Vector3();

/** Stand `o` on the route at parameter t, local -Z along the travel direction. */
export function placeAt(o: THREE.Object3D, t: number): void {
  const k = Math.min(1, Math.max(0, t));
  ROUTE.getPointAt(k, p);
  ROUTE.getTangentAt(k, q);
  o.position.copy(p);
  m4.lookAt(p, p.clone().add(q), UP);
  o.quaternion.setFromRotationMatrix(m4);
}

/** Route parameter of a beat's station (where its structure stands). */
export const STATION_AT: Record<BeatId, number> = { problem: 0.04, evidence: 0.22, policy: 0.4, strike: 0.58, audit: 0.76, reveal: 0.97 };

export const decisionOf = (s: string | null | undefined): Decision | null => (s === "ALLOW" || s === "REVIEW" || s === "DENY" ? s : null);
