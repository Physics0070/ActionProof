import type { Metadata } from "next";
import { ConsoleShell } from "@/components/console/Shell";

export const metadata: Metadata = { title: "Review console", description: "Review the actions an AI agent paused. Approve or reject with evidence.", robots: { index: false, follow: false } };

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return <ConsoleShell>{children}</ConsoleShell>;
}
