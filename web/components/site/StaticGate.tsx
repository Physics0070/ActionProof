// No-WebGL / reduced-motion twin of the 3D scene: one still poster per step (0 Intercept .. 4 Audit), drawn from the same
// beats as the scene. The words and numbers for each step are in the DOM next to it (data-driven readouts); this SVG only
// shows the door state. Pure SVG + CSS tokens; shapes differ per decision (circle, triangle, square), never colour alone.
type Light = "REVIEW" | "ALLOW" | "DENY";

const TITLES = [
  "Intercept: the request packet reaches the first ring, the door is shut",
  "Verify: the packet is held at the second ring while its numbers are re-derived, the door stays shut",
  "Authorize: the door opens to the decision light",
  "Receipt and commit: the packet has passed, the light shows the committed result",
  "Audit: the door is shut again and a replayed receipt bounces off it in the DENY colour",
] as const;

const lightVar = (l: Light) => (l === "ALLOW" ? "var(--sig-allow)" : l === "DENY" ? "var(--sig-deny)" : "var(--sig-review)");

export function StaticGate({ step, decision = "REVIEW", final = "ALLOW", chain = 0, denyIndex = -1 }: { step: number; decision?: Light; final?: Light; chain?: number; denyIndex?: number }) {
  const open = step === 2 || step === 3;
  const lamp = lightVar(step === 3 ? final : decision);
  const packetX = [70, 128, 196, 410, 70][step] ?? 70;
  const id = `sg-${step}`;
  const blocks = Math.min(chain, 24);
  return (
    <figure className="gate-poster">
      <svg viewBox="0 0 640 360" role="img" aria-labelledby={`${id}-t`} className="static-gate">
        <title id={`${id}-t`}>{TITLES[step] ?? TITLES[0]}</title>
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <rect key={i} x={40 + i * 28} y={30 + i * 14} width={560 - i * 56} height={300 - i * 28} fill="none" stroke="var(--c-line)" strokeWidth="2" />
        ))}
        {/* station rings, lit when the packet is at them */}
        {[70, 128, 196].map((x, i) => (
          <rect key={x} x={x + 14} y={150 - i * 6} width="14" height={120 + i * 12} fill={step === i ? "var(--c-accent)" : "var(--c-line)"} opacity={step === i ? 1 : 0.5} />
        ))}
        {/* the door */}
        <rect x="248" y="104" width="144" height="156" fill="var(--c-paper)" stroke="var(--c-line)" strokeWidth="3" />
        {open ? <rect x="262" y="118" width="116" height="128" fill={lamp} opacity="0.95" /> : null}
        {open && step === 3 ? <circle cx="320" cy="182" r="16" fill="var(--c-ground)" /> : null}
        <rect x={open ? 236 : 262} y="118" width={open ? 26 : 58} height="128" fill="var(--c-line)" />
        <rect x={open ? 378 : 322} y="118" width={open ? 26 : 58} height="128" fill="var(--c-line)" />
        {!open ? <rect x="318" y="118" width="4" height="128" fill="var(--c-accent)" /> : null}
        {/* the packet */}
        {step !== 3 && step !== 4 ? (
          <>
            <circle cx={packetX} cy="190" r="16" fill="var(--c-accent)" />
            <circle cx={packetX} cy="190" r="26" fill="none" stroke="var(--c-accent)" strokeWidth="2" strokeDasharray="4 6" />
          </>
        ) : null}
        {step === 1 ? <path d="M96 150h56M96 190h56M96 230h56" stroke="var(--c-accent)" strokeWidth="2" opacity="0.6" /> : null}
        {step === 3 ? <rect x="430" y="168" width="44" height="30" fill="var(--c-accent)" /> : null}
        {/* the replayed receipt bounces off the closed door */}
        {step === 4 ? (
          <>
            <path d="M470 190H414" stroke="var(--sig-deny)" strokeWidth="3" />
            <path d="M426 178 414 190 426 202" fill="none" stroke="var(--sig-deny)" strokeWidth="3" />
            <rect x="470" y="174" width="32" height="32" fill="var(--sig-deny)" />
            <path d="M392 190l-22 -22M392 190l-22 22" stroke="var(--sig-deny)" strokeWidth="3" />
            {Array.from({ length: blocks }).map((_, i) => (
              <rect key={i} x={60 + i * 22} y="296" width="16" height="12" fill={i === denyIndex ? "var(--sig-deny)" : "var(--sig-allow)"} />
            ))}
          </>
        ) : null}
      </svg>
    </figure>
  );
}
