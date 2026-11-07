import { Band } from "@/components/ui/Band";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal } from "@/components/ui/Signal";

// Scaffold only (task 7.1). The hero scene, the replay card and the sections land in task 7.2; every number they show
// is fetched from the backend (/api/public/replay/inv-2048, /api/public/eval).
export default function Home() {
  return (
    <Band tone="carbon" labelledBy="hero-title">
      <MonoLabel as="p" muted>
        Proof before permission
      </MonoLabel>
      <h1 id="hero-title" className="t-display" style={{ marginBlock: "var(--s-6)" }}>
        Before an AI agent acts, prove it should.
      </h1>
      <p className="t-lede t-muted">
        Every value in an agent&apos;s write is re-checked against its source before the write runs. One decision per action.
      </p>
      <ul aria-label="Decisions" style={{ display: "flex", gap: "var(--s-5)", listStyle: "none", padding: 0, marginTop: "var(--s-7)" }}>
        <li>
          <Signal state="ALLOW" />
        </li>
        <li>
          <Signal state="REVIEW" />
        </li>
        <li>
          <Signal state="DENY" />
        </li>
      </ul>
    </Band>
  );
}
