import Link from "next/link";
import { REPO_URL } from "@/lib/config";
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
        <nav aria-label="Footer" className="container foot-inner">
          <Link href="/" className="foot-brand">
            ActionProof
          </Link>
          <Link href="/#limits">What it does not claim</Link>
          <Link href="/evaluation">Evaluation</Link>
          <Link href="/console">Console</Link>
          {REPO_URL ? (
            <a href={REPO_URL} rel="noopener">
              GitHub
            </a>
          ) : null}
        </nav>
      </footer>
    </div>
  );
}
