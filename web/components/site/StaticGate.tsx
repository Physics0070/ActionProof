// No-WebGL / reduced-motion twin of the 3D scene: the same story as one still poster. A packet reaches a shut door,
// the door opens to the decision light, and a copy of the receipt bounces off the closed door. Pure SVG + CSS tokens.
export function StaticGate({ className }: { className?: string }) {
  return (
    <figure className={className}>
      <svg viewBox="0 0 640 360" role="img" aria-labelledby="sg-t sg-d" className="static-gate">
        <title id="sg-t">A request packet reaches a door that opens only after its values re-check</title>
        <desc id="sg-d">A pink packet travels a corridor toward a bulkhead door. A second packet, a replayed receipt, bounces off the closed door in the DENY colour.</desc>
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <rect key={i} x={40 + i * 28} y={30 + i * 14} width={560 - i * 56} height={300 - i * 28} fill="none" stroke="var(--c-line)" strokeWidth="2" />
        ))}
        <rect x="248" y="110" width="144" height="150" fill="var(--c-paper)" stroke="var(--c-line)" strokeWidth="3" />
        <rect x="262" y="124" width="56" height="122" fill="var(--sig-review)" opacity="0.9" />
        <rect x="322" y="124" width="56" height="122" fill="var(--sig-allow)" opacity="0.9" />
        <rect x="236" y="116" width="26" height="138" fill="var(--c-line)" />
        <rect x="378" y="116" width="26" height="138" fill="var(--c-line)" />
        <circle cx="140" cy="200" r="16" fill="var(--c-accent)" />
        <circle cx="140" cy="200" r="26" fill="none" stroke="var(--c-accent)" strokeWidth="2" strokeDasharray="4 6" />
        <path d="M160 200H228" stroke="var(--c-accent)" strokeWidth="3" strokeDasharray="2 8" />
        <rect x="486" y="184" width="30" height="30" fill="var(--sig-deny)" />
        <path d="M480 199H430" stroke="var(--sig-deny)" strokeWidth="3" />
        <path d="M442 188 430 199 442 210" fill="none" stroke="var(--sig-deny)" strokeWidth="3" />
      </svg>
    </figure>
  );
}
