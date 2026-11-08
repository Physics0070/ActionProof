import Link from "next/link";
import "./site.css";

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="site-root band-carbon">
      <header className="site-head">
        <nav aria-label="Primary" className="container site-nav">
          <Link href="/" className="site-brand">
            ActionProof
          </Link>
          <Link href="/evaluation" className="site-link">
            Evaluation
          </Link>
          <Link href="/console" className="site-link">
            Console
          </Link>
        </nav>
      </header>
      <main id="main">{children}</main>
      <footer className="site-foot">
        <div className="container">
          <p className="mono-label t-muted">Prove the action before the system executes it.</p>
        </div>
      </footer>
    </div>
  );
}
