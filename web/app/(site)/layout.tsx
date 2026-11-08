import Link from "next/link";
import "./site.css";
import { MonoLabel } from "@/components/ui/MonoLabel";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="band-mist">
        <nav aria-label="Primary" className="container" style={{ display: "flex", gap: "var(--s-5)", alignItems: "center", minHeight: 64 }}>
          <Link href="/" style={{ textDecoration: "none", marginRight: "auto" }}>
            <MonoLabel>ActionProof</MonoLabel>
          </Link>
          <Link href="/evaluation">
            <MonoLabel>Evaluation</MonoLabel>
          </Link>
          <Link href="/console">
            <MonoLabel>Console</MonoLabel>
          </Link>
        </nav>
      </header>
      <main id="main">{children}</main>
      <footer className="band-carbon">
        <div className="container" style={{ paddingBlock: "var(--s-6)" }}>
          <MonoLabel muted>Prove the action before the system executes it.</MonoLabel>
        </div>
      </footer>
    </>
  );
}
