import Link from "next/link";
import { Signal } from "@/components/ui/Signal";

export default function NotFound() {
  return (
    <main id="main" className="band band-carbon" style={{ minHeight: "100vh" }}>
      <div className="container">
        <Signal state="DENY" label="no such page" />
        <h1 className="t-h2" style={{ marginBlock: "var(--s-6)" }}>
          Nothing is registered at this address.
        </h1>
        <Link className="button" href="/">
          Go to the start
        </Link>
      </div>
    </main>
  );
}
