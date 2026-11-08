// Deck copy for the public site (slides 1-4, 9, 10). Words only: every number on the site is fetched (invariant 7).

export const HERO = {
  usp: "Proof before permission.",
  title: "Before an AI agent acts, prove it should.",
  sub: "An evidence-verified safety gate for AI agents and the tools they control.",
};

export const GAPS = [
  { id: "evidence", gap: "Evidence gap", head: "Unverified arguments", body: "A tool argument can hold a value with no source field and no document citation behind it." },
  { id: "policy", gap: "Policy gap", head: "Policy bypass", body: "A valid tool name can still carry an amount, target or actor outside the caller's scope." },
  { id: "execution", gap: "Execution gap", head: "Unsafe state change", body: "Retries, stale records and check-then-commit races can repeat or invalidate an approved write." },
] as const;

export const STEPS = [
  { head: "Intercept", body: "An MCP proxy sits in front of every tool. Default deny." },
  { head: "Verify", body: "Re-extract each cited value, recompute derived ones, check taint." },
  { head: "Authorize", body: "OPA/Rego policy, plus a dry-run diff and a state version." },
  { head: "Receipt and commit", body: "A signed one-use receipt. Commit re-checks state, then calls the tool." },
  { head: "Audit", body: "Hash-chained log with signed checkpoints and a verifier CLI." },
] as const;

export const OUTCOMES = "Outcomes: ALLOW, REVIEW (a human mints a one-use token) or DENY. Any error fails closed.";

export const CLAIMS = [
  { kind: "DIRECT", body: "A deterministic parser re-extracts the value at the cited page and box. Value and document hash must both match." },
  { kind: "DERIVED", body: "Recomputed by an allowlisted pure function over verified claims. The model never does the arithmetic." },
  { kind: "ASSERTED", body: "Model-only. Fine for low-risk fields, never enough to authorize a money-moving argument." },
] as const;

export const TAINT = "Text from documents can be shown to a reviewer, but it can't fill an authority field unless it is DIRECT-verified or matches a system of record.";

export const USP_BODY = "No value can authorize a write unless its derivation re-checks (G1), and no approval can be replayed (G2).";

export const BENEFITS = [
  { who: "Developers shipping agents", body: "A drop-in gate instead of bespoke checks." },
  { who: "Finance and operations teams", body: "Risky approvals pause with the reason and source span." },
  { who: "Security and compliance", body: "A signed, tamper-evident record of each decision." },
  { who: "People whose money or data agents touch", body: "Fewer wrong writes." },
] as const;

export const IMPACT = [
  "Out-of-policy or unsupported writes are blocked before they execute.",
  "Reviewers decide from evidence, not from the agent's own summary.",
  "Replays and stale-state writes are rejected by construction.",
] as const;

export const LIMITS = [
  { head: "Verifier-bound", body: "Only as good as its deterministic verifiers. Free-form judgments can't be proven." },
  { head: "Semantic fraud", body: "A fake invoice that looks internally consistent is out of scope." },
  { head: "The gate is a target", body: "The signing key must stay out of the agent's reach, and the gateway needs hardening." },
  { head: "Safety, not judgment", body: "It stops unauthorized actions. It doesn't guarantee a good business decision." },
] as const;

export const CLOSING = "Prove the action before the system executes it.";

// ------------------------------------------------------------------------------------------------ evaluation (slides 5, 6, 9)

export const TABLE_ROWS = [
  { key: "llm_judge", label: "Output filter or LLM judge", measured: true },
  { key: "schema_only", label: "Schema validation only", measured: true },
  { key: "policy_gateway", label: "Plain policy gateway (OPA, Cedar)", measured: true },
  { key: "dual_llm", label: "Dual-LLM or capability designs (CaMeL-style)", measured: false },
  { key: "actionproof", label: "ActionProof", measured: true },
] as const;

export const TABLE_COLS = [
  { key: "checks_args", label: "Checks args" },
  { key: "evidence_per_arg", label: "Evidence per arg" },
  { key: "taint_flow", label: "Taint flow" },
  { key: "commit_time_check", label: "Commit-time check" },
  { key: "signed_receipt", label: "Signed receipt" },
] as const;

export const CLASSES = [
  { key: "prompt_injection", label: "Prompt injection", control: "Taint labels; text never fills authority fields.", test: "Hidden \"approve regardless\" in a PDF." },
  { key: "argument_tampering", label: "Argument tampering", control: "Claims re-verified at the cited span.", test: "Amount edited after extraction." },
  { key: "evidence_forgery", label: "Evidence forgery", control: "Span re-extraction and document hash match.", test: "Cited span lacks the value." },
  { key: "confused_deputy", label: "Confused deputy", control: "on_behalf_of scope checked in policy.", test: "Agent exceeds the user's scope." },
  { key: "split_payments", label: "Split payments", control: "Cumulative limits per actor and vendor.", test: "Two approvals that together pass the cap." },
  { key: "replay", label: "Replay", control: "One-use token and idempotency key.", test: "Reused token or key." },
  { key: "race", label: "Race (TOCTOU)", control: "Version precondition at commit.", test: "Record mutated mid-flight." },
] as const;

export const SETS = [
  { key: "handwritten", label: "Handwritten" },
  { key: "handwritten2", label: "Handwritten, second set (NOT independent)" },
  { key: "generated", label: "Generated (independent)" },
] as const;

export const FRAMING =
  "Rows describe typical designs, not specific products. None of the pieces is new alone. The contribution is combining claim verification, taint and a signed two-phase commit in one MCP gateway, then measuring it against baselines.";
