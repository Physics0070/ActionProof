import type { Metadata } from "next";
import { Band } from "@/components/ui/Band";

export const metadata: Metadata = { title: "Evaluation", description: "How the gate is measured: attacks blocked, false blocks, added latency." };

// Scaffold only (task 7.1). Results come from GET /api/public/eval in task 7.2; nothing here is a hardcoded number.
export default function Evaluation() {
  return (
    <Band labelledBy="eval-title">
      <h1 id="eval-title" className="t-h2">
        Evaluation
      </h1>
    </Band>
  );
}
