import type { ElementType, ReactNode } from "react";

/** Instrument label: mono, small, carries real information (a field name, a rule id, a hash). */
export function MonoLabel({ as: Tag = "span", muted = false, children }: { as?: ElementType; muted?: boolean; children: ReactNode }) {
  return <Tag className={muted ? "mono-label t-muted" : "mono-label"}>{children}</Tag>;
}
