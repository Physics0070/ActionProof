import type { Metadata } from "next";
import Link from "next/link";
import { MonoLabel } from "@/components/ui/MonoLabel";

export const metadata: Metadata = { title: "Review console", robots: { index: false, follow: false } };

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="band-carbon">
        <nav aria-label="Console" className="container" style={{ display: "flex", gap: "var(--s-5)", alignItems: "center", minHeight: 56 }}>
          <Link href="/" style={{ textDecoration: "none", marginRight: "auto" }}>
            <MonoLabel>ActionProof</MonoLabel>
          </Link>
          <Link href="/console">
            <MonoLabel>Queue</MonoLabel>
          </Link>
        </nav>
      </header>
      <main id="main" className="container" style={{ paddingBlock: "var(--s-7)" }}>
        {children}
      </main>
    </>
  );
}
