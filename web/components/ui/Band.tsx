import type { ReactNode } from "react";

/** Full-bleed section. `carbon` re-points every token (text, lines, signals -> lamp colours) via .band-carbon. */
export function Band({
  tone = "mist",
  id,
  labelledBy,
  children,
}: {
  tone?: "mist" | "carbon";
  id?: string;
  labelledBy?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={labelledBy} className={`band band-${tone}`}>
      <div className="container">{children}</div>
    </section>
  );
}
