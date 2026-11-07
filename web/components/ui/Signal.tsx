// One decision = one colour + one shape + one word. Never colour alone (web/DESIGN.md "Signal system").
// ALLOW = circle (go), REVIEW = triangle (hold for a human), DENY = square (stop).
export type Decision = "ALLOW" | "REVIEW" | "DENY";

const SHAPES: Record<Decision, React.ReactNode> = {
  ALLOW: <circle cx="8" cy="8" r="7" />,
  REVIEW: <path d="M8 1 15 15H1Z" />,
  DENY: <rect x="1" y="1" width="14" height="14" />,
};

export function Signal({
  state,
  solid = false,
  label,
}: {
  state: Decision;
  /** Filled lamp plate with ink text (for carbon bands and the hero card). */
  solid?: boolean;
  /** Extra words after the decision, e.g. a rule id. */
  label?: string;
}) {
  return (
    <span className={solid ? "signal signal-solid" : "signal"} data-state={state}>
      <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false" fill="currentColor">
        {SHAPES[state]}
      </svg>
      <span>{state}</span>
      {label ? <span>{label}</span> : null}
    </span>
  );
}
