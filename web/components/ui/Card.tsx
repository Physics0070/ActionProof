import type { ElementType, ReactNode } from "react";

/** Flat panel: paper fill + 1px hairline, no shadow, no radius. */
export function Card({ as: Tag = "div", children }: { as?: ElementType; children: ReactNode }) {
  return <Tag className="card">{children}</Tag>;
}
