import type { Metadata } from "next";
import { ConsoleShell } from "@/components/console/Shell";

export const metadata: Metadata = { title: "Review console", robots: { index: false, follow: false } };

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return <ConsoleShell>{children}</ConsoleShell>;
}
