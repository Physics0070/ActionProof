// GLSL for the assay scene. Three small programs, all cheap: a drifting dust cloud, the unstable request packet, and an
// expanding strike ring. No textures, no post-processing.

/** Dust: the unproven world around the request. It drifts, and thins out as proofs complete (uClarity). */
export const DUST_VERT = /* glsl */ `
  attribute float aSeed;
  uniform float uTime;
  uniform float uClarity;
  uniform float uSize;
  varying float vA;
  void main() {
    vec3 p = position;
    p.x += sin(uTime * 0.15 + aSeed * 40.0) * 0.35;
    p.y += cos(uTime * 0.12 + aSeed * 31.0) * 0.3;
    p.z += sin(uTime * 0.10 + aSeed * 17.0) * 0.35;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uSize * (0.6 + aSeed) * (30.0 / -mv.z);
    vA = mix(0.95, 0.2, uClarity * step(0.2, aSeed));
  }`;
export const DUST_FRAG = /* glsl */ `
  uniform vec3 uColor;
  varying float vA;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    float a = smoothstep(0.5, 0.0, d) * vA;
    gl_FragColor = vec4(uColor, a);
  }`;

/** Packet: wobbles while unproven (uInstab), settles when proven. Fresnel rim so it reads as light, not as a solid. */
export const PACKET_VERT = /* glsl */ `
  uniform float uTime;
  uniform float uInstab;
  varying vec3 vN;
  varying vec3 vV;
  float h(vec3 p) { return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453); }
  void main() {
    vec3 p = position;
    float j = (h(floor(p * 6.0) + floor(uTime * 8.0)) - 0.5) * uInstab;
    p += normal * j;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    vN = normalize(normalMatrix * normal);
    vV = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }`;
export const PACKET_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uLevel;
  varying vec3 vN;
  varying vec3 vV;
  void main() {
    float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 2.2);
    gl_FragColor = vec4(uColor, (0.18 + f * 0.9) * uLevel);
  }`;

/** Ring: an expanding band for the strike and the replay bounce. uT runs 0..1. */
export const RING_VERT = /* glsl */ `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
export const RING_FRAG = /* glsl */ `
  uniform vec3 uColor;
  uniform float uT;
  varying vec2 vUv;
  void main() {
    float d = distance(vUv, vec2(0.5)) * 2.0;
    float edge = abs(d - uT);
    float a = smoothstep(0.09, 0.0, edge) * (1.0 - uT);
    gl_FragColor = vec4(uColor, a);
  }`;
