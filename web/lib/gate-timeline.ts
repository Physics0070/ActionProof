// Pure map from gate progress (0..1) to scene parameters. Five stations, one per deck step (STEPS):
//   0 Intercept, 1 Verify (re-derive BEFORE the door moves), 2 Authorize (door opens), 3 Receipt and commit, 4 Audit (replay bounces).
// `verified` gates the door: if the browser did not re-derive the value, the door never opens (G1).
export const STATIONS = 5;
const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const seg = (p: number, a: number, b: number) => clamp((p - a) / (b - a));
const ease = (t: number) => t * t * (3 - 2 * t);

export type Frame = {
  step: number;
  camZ: number;
  packetZ: number;
  packetVisible: number;
  /** 0 closed .. 1 open. */
  door: number;
  /** 0 none, 1 decision light (REVIEW), 2 final light (ALLOW/executed). */
  light: number;
  lightLevel: number;
  /** Receipt copy position and the bounce flash (0..1). */
  ghostZ: number;
  ghostVisible: number;
  flash: number;
  /** Chain blocks revealed 0..1. */
  chain: number;
};

export const DOOR_Z = 0;
export const RING_Z = [24, 17, 10] as const;

export function frame(p: number, verified: boolean): Frame {
  const step = Math.min(STATIONS - 1, Math.floor(p * STATIONS));
  const v = verified ? 1 : 0;
  const open = ease(seg(p, 0.42, 0.52)) * v * (1 - ease(seg(p, 0.8, 0.86)));
  const pass = ease(seg(p, 0.58, 0.72));
  const approach = ease(seg(p, 0, 0.2));
  const toVerify = ease(seg(p, 0.2, 0.4));
  const toDoor = ease(seg(p, 0.4, 0.55));
  let packetZ = 34 - 8 * approach - 8 * toVerify - 8 * toDoor;
  if (verified) packetZ -= pass * 16;
  const bounce = seg(p, 0.88, 0.96);
  const ghostIn = ease(seg(p, 0.82, 0.9));
  const ghostZ = bounce < 0.5 ? 17 - ghostIn * 16 : 1 + (bounce - 0.5) * 2 * 8;
  return {
    step,
    camZ: 40 - 4 * ease(seg(p, 0, 0.2)) - 6 * ease(seg(p, 0.2, 0.4)) - 11 * ease(seg(p, 0.4, 0.6)) + 4 * ease(seg(p, 0.8, 1)),
    packetZ,
    packetVisible: verified ? 1 - ease(seg(p, 0.7, 0.76)) : 1,
    door: open,
    light: p < 0.6 ? 1 : 2,
    lightLevel: open,
    ghostZ,
    ghostVisible: ghostIn,
    flash: p > 0.9 ? 1 - ease(seg(p, 0.92, 1)) * 0.5 : 0,
    chain: ease(seg(p, 0.78, 0.98)),
  };
}
