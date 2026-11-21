// Static drawings of the six stations, for visitors without the 3D scene (reduced motion, no WebGL, WebGL failure) and
// for crawlers. Same vocabulary as the scene: solid / ringed / dashed claims, notched rings, the die and the latch, the
// linked chain. They are decoration (aria-hidden); the copy beside them carries the meaning, and nothing here shows data.
import type { BeatId } from "@/lib/assay";

const ink = "var(--as-bone)";
const dim = "var(--as-steel)";
const line = "var(--as-line)";
const hot = "var(--as-deny)";

type Pt = [number, number];
const DOTS: Pt[] = [[60, 60], [90, 200], [300, 80], [320, 190], [250, 40], [120, 40], [40, 140]];
const MARKS: Pt[] = [[90, 200], [170, 140], [235, 118], [300, 70]];

function Evidence() {
  return (
    <>
      <rect x="40" y="40" width="46" height="60" fill="none" stroke={line} />
      <path d="M63 100v34" stroke={ink} />
      <path d="M63 134 52 148h22z" fill={ink} />
      <circle cx="170" cy="150" r="22" fill="none" stroke={ink} />
      <path d="M170 136l10 14-10 14-10-14z" fill="none" stroke={ink} />
      <path d="M63 148 148 150M63 148 160 170" stroke={ink} strokeOpacity=".5" />
      <path d="M262 110 330 70" stroke={dim} strokeDasharray="5 5" />
      <path d="M262 96l12 12-12 12-12-12z" fill="none" stroke={dim} strokeDasharray="3 3" />
    </>
  );
}
function Policy() {
  return (
    <>
      {[40, 70, 100].map((r, i) => (
        <g key={r}>
          <circle cx="190" cy="130" r={r} fill="none" stroke={i === 1 ? ink : dim} strokeOpacity={i === 1 ? 1 : 0.7} />
          <circle cx="190" cy="130" r={r} fill="none" stroke={ink} strokeWidth="6" strokeDasharray="1 11" strokeOpacity=".5" />
        </g>
      ))}
      <circle cx="190" cy="130" r="9" fill={ink} />
    </>
  );
}
function Strike() {
  return (
    <>
      <rect x="150" y="30" width="80" height="44" fill="none" stroke={ink} />
      <rect x="170" y="92" width="40" height="40" fill="none" stroke={ink} />
      {[0, 1, 2, 3].flatMap((a) => [0, 1, 2, 3].map((b) => ((a * 3 + b * 5) % 3 === 0 ? <rect key={`${a}${b}`} x={175 + a * 9} y={97 + b * 9} width="6" height="6" fill={ink} /> : null)))}
      <circle cx="190" cy="180" r="22" fill="none" stroke={ink} />
      <path d="M100 205h180" stroke={ink} strokeWidth="4" />
      <path d="M100 150v60M280 150v60" stroke={line} strokeWidth="4" />
      <path d="M330 215 300 207" stroke={hot} strokeDasharray="4 4" />
      <circle cx="338" cy="217" r="9" fill="none" stroke={hot} />
    </>
  );
}
function Audit() {
  return (
    <>
      <path d="M40 130H340" stroke={dim} />
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <rect key={i} x={46 + i * 52} y="106" width="40" height="48" fill="none" stroke={i === 5 ? hot : ink} strokeWidth={i === 5 ? 2 : 1} />
      ))}
      <circle cx="170" cy="130" r="36" fill="none" stroke="#fff" />
    </>
  );
}
function Problem() {
  return (
    <>
      <path d="M190 80l36 24v44l-36 24-36-24v-44z" fill="none" stroke={ink} />
      <path d="M190 80v92M154 104l72 44M226 104l-72 44" stroke={ink} strokeOpacity=".5" />
      {DOTS.map(([x, y]) => (
        <circle key={`${x}${y}`} cx={x} cy={y} r="2" fill={dim} />
      ))}
    </>
  );
}
function Reveal() {
  return (
    <>
      <path d="M40 240C120 200 90 150 170 140S300 90 340 40" fill="none" stroke={ink} />
      <circle cx="340" cy="40" r="7" fill={ink} />
      {MARKS.map(([x, y]) => (
        <rect key={`${x}`} x={x - 7} y={y - 7} width="14" height="14" fill="none" stroke={ink} />
      ))}
      <rect x="290" y="62" width="14" height="14" fill="none" stroke={hot} />
    </>
  );
}

const DRAW: Record<BeatId, () => React.JSX.Element> = { problem: Problem, evidence: Evidence, policy: Policy, strike: Strike, audit: Audit, reveal: Reveal };

export function Glyph({ id }: { id: BeatId }) {
  const D = DRAW[id];
  return (
    <svg className="beat-glyph" viewBox="0 0 380 260" role="presentation" aria-hidden="true" focusable="false" fill="none" strokeWidth="1.4">
      <D />
    </svg>
  );
}
