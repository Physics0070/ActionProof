import type { Metadata } from "next";
import { EvalView } from "@/components/site/EvalView";

export const metadata: Metadata = {
  title: "Evaluation",
  alternates: { canonical: "/evaluation" },
  description: "How the gate is measured: attacks that executed, false blocks and added latency, against baselines. Every number is read from the evaluation results.",
};

export default function Evaluation() {
  return (
    <div className="eval-page">
      <div className="container">
        <h1 id="eval-title" className="t-display eval-title">
          Evaluation
        </h1>
        <p className="t-lede t-muted eval-lede">Measured against no gate, schema-only checks, a policy gateway and an LLM judge. Nothing here is typed by hand.</p>
        <EvalView />
      </div>
    </div>
  );
}
