// No-WebGL / reduced-motion twin of the 3D scene: the same idea as a static diagram. Requests arrive at the gate and
// leave as exactly one of three signals, each a shape plus a word (never colour alone). Pure SVG + CSS, no motion.
import { Signal } from "@/components/ui/Signal";

const OUT = [
  { state: "ALLOW", line: "executed once" },
  { state: "REVIEW", line: "paused for a different person" },
  { state: "DENY", line: "blocked, with the rule id and G1 or G2" },
] as const;

export function StaticSignals() {
  return (
    <figure className="static-signals">
      <svg viewBox="0 0 480 220" role="img" aria-labelledby="ss-title ss-desc" className="static-svg">
        <title id="ss-title">Requests pass one gate and leave as ALLOW, REVIEW or DENY</title>
        <desc id="ss-desc">Many agent requests on the left reach a vertical gate; three signals leave it, each with its own shape and word.</desc>
        {Array.from({ length: 5 }).map((_, r) =>
          Array.from({ length: 5 }).map((__, c) => (
            <circle key={`${r}-${c}`} cx={24 + c * 26} cy={40 + r * 34} r="4" fill="var(--c-muted)" />
          )),
        )}
        <line x1="230" y1="10" x2="230" y2="210" stroke="var(--c-line)" strokeWidth="2" />
        <rect x="222" y="98" width="16" height="16" fill="var(--c-accent)" />
        <circle cx="330" cy="50" r="12" fill="var(--sig-allow)" />
        <path d="M330 86 342 112H318Z" fill="var(--sig-review)" />
        <rect x="318" y="148" width="24" height="24" fill="var(--sig-deny)" />
        {[50, 100, 160].map((y) => (
          <line key={y} x1="240" y1={y} x2="312" y2={y} stroke="var(--c-line)" strokeWidth="1" />
        ))}
      </svg>
      <figcaption>
        <ul className="plain-list">
          {OUT.map((o) => (
            <li key={o.state}>
              <Signal state={o.state} /> <span className="t-muted">{o.line}</span>
            </li>
          ))}
        </ul>
      </figcaption>
    </figure>
  );
}
