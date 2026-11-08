// Generates src/data.generated.json from the REAL artifacts: data/demo-output.txt (bash demo.sh), data/eval-results.json
// (copy of ../eval/results.json), data/audit-run.txt (tamper.py) and data/request.json (console API, if recorded).
// Nothing on screen is typed by hand: scenes read this file.
import fs from "node:fs";
const rd = (f) => fs.readFileSync(new URL(`../data/${f}`, import.meta.url), "utf8");
const log = rd("demo-output.txt").split(/\r?\n/);

// beats: "--- BEAT n: title ---" then a sub line, then body
const beats = [];
let cur = null;
for (const l of log) {
  const m = l.match(/^--- BEAT (\d+): (.*?) -+$/);
  if (m) { cur = { n: +m[1], title: m[2].trim(), lines: [] }; beats.push(cur); continue; }
  if (/^={10,}/.test(l)) { cur = null; continue; }
  if (cur) cur.lines.push(l);
}
// cards: consecutive lines starting with "+---" ... "+---"
function cards(lines) {
  const out = []; let c = null;
  for (const l of lines) {
    const t = l.trim();
    if (t.startsWith("+-")) { if (c) { out.push(c); c = null; } else c = []; continue; }
    if (c && t.startsWith("|")) c.push(t.replace(/^\|\s?/, "").replace(/\s*\|$/, ""));
  }
  return out;
}
const field = (card, key) => (card.find((r) => r.startsWith(key + ":")) || "").slice(key.length + 1).trim();
const B = Object.fromEntries(beats.map((b) => [b.n, b]));
const grab = (b, re) => b.lines.map((l) => l.trim()).filter((l) => re.test(l));
const data = {
  beats: beats.map((b) => ({ n: b.n, title: b.title, cards: cards(b.lines) })),
  b1: { card: cards(B[1].lines)[0], reason: grab(B[1], /^reason:/)[0], label: grab(B[1], /^label:/)[0],
        span: grab(B[1], /^source span/)[0], approved: grab(B[1], /^console ->/)[0] },
  b2: { card: cards(B[2].lines)[0], hidden: grab(B[2], /hides/)[0], reasons: grab(B[2], /^reason:/) },
  b3: { reasons: grab(B[3], /^reason:/), audited: grab(B[3], /recorded in the audit chain/)[0] },
  b4: { lines: grab(B[4], /^(approval [AB]|committed for|reason:|agent-7 spends|actor rotation)/) },
  b5: { cards: cards(B[5].lines), reasons: grab(B[5], /^reason:/), shows: grab(B[5], /shows/)[0] },
  b6: { audit: grab(B[6], /^audit: OK/)[0] },
  results: grab({ lines: log }, /^(ok|FAIL)\s/),
  pass: log.some((l) => /^PASS: every beat/.test(l)),
};
const ar = rd("audit-run.txt").split(/\r?\n/).filter(Boolean);
data.audit = { ok: ar.find((l) => l.startsWith("audit: OK")), failed: ar.find((l) => l.startsWith("audit: FAILED")),
  edit: ar.find((l) => l.includes("edits one row")), cmds: ar.filter((l) => l.startsWith("$ python")) };
const ev = JSON.parse(rd("eval-results.json"));
const arms = ["no_gate", "schema_only", "llm_judge", "policy_gateway", "actionproof"];
data.eval = {
  arms: arms.map((k) => ({ key: k, n: ev.arms[k].attacks.total.n, executed: ev.arms[k].attacks.total.success,
    benignN: ev.arms[k].benign.n, falseBlocks: ev.arms[k].benign.false_blocks,
    addedP95: ev.arms[k].latency_ms.added_p95, p95: ev.arms[k].latency_ms.p95 })),
  heldOutSet: ev.targets_met.held_out_set, heldOutN: ev.targets_met.held_out_n,
  heldOutExecuted: ev.arms.actionproof.attacks.by_set.handwritten2.success,
  generatedStatus: ev.arms.actionproof.attacks.generated_status,
  targets: ev.targets, met: ev.targets_met,
};
try { const r = JSON.parse(rd("request.json")); data.request = r; } catch { data.request = null; }
fs.writeFileSync(new URL("../src/data.generated.json", import.meta.url), JSON.stringify(data, null, 1));
console.log("beats", beats.map((b) => b.n).join(","), "| b1 card", data.b1.card?.length, "| eval n", data.eval.arms[4].n, "| audit", data.audit.ok, "/", data.audit.failed);
