import type { Metadata } from "next";
import { Band } from "@/components/ui/Band";
import { EvalView } from "@/components/site/EvalView";

export const metadata: Metadata = {
  title: "Evaluation",
  description: "How the gate is measured: attacks that executed, false blocks and added latency, against baselines. Every number is read from the evaluation results.",
};

export default function Evaluation() {
  return (
    <Band labelledBy="eval-title">
      <h1 id="eval-title" className="t-display eval-title">
        Evaluation
      </h1>
      <p className="t-lede t-muted">Measured against no gate, schema-only checks, a policy gateway and an LLM judge. Nothing on this page is typed in by hand.</p>
      <EvalView />
    </Band>
  );
}
