// WCAG 2.x contrast ratios for every text/mark pairing the "Assay" tokens allow (web/DESIGN.md "Contrast").
// Run: npm run contrast. Exits 1 if any pairing is below its required ratio.
const lum = (hex) => {
  const c = hex.replace("#", "").match(/../g).map((h) => parseInt(h, 16) / 255);
  const [r, g, b] = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};
const T = {
  // light surfaces (console, evaluation details)
  bone: "#ece9e1", paper: "#f7f5ef", ink: "#0b0e10", muted: "#4b5a62", line: "#cbc5b5",
  allowInk: "#0a5c3f", reviewInk: "#7a4f00", denyInk: "#b3260a",
  // obsidian (the dark band)
  obsidian: "#07090a", raised: "#0e1316", boneText: "#ece9e1", steel: "#8d9da6", graphite: "#2a3236",
  allowLamp: "#b8ffe0", reviewLamp: "#ffb020", denyLamp: "#ff4a24",
};
// [label, fg, bg, min]: 4.5 body text, 3.0 large text or non-text marks (WCAG 1.4.11).
const pairs = [
  ["ink on bone ground", T.ink, T.bone, 4.5],
  ["muted on bone ground", T.muted, T.bone, 4.5],
  ["ink on paper", T.ink, T.paper, 4.5],
  ["muted on paper", T.muted, T.paper, 4.5],
  ["ALLOW ink word on bone", T.allowInk, T.bone, 4.5],
  ["REVIEW ink word on bone", T.reviewInk, T.bone, 4.5],
  ["DENY ink word on bone", T.denyInk, T.bone, 4.5],
  ["ALLOW ink word on paper", T.allowInk, T.paper, 4.5],
  ["REVIEW ink word on paper", T.reviewInk, T.paper, 4.5],
  ["DENY ink word on paper", T.denyInk, T.paper, 4.5],
  ["bone text on obsidian", T.boneText, T.obsidian, 4.5],
  ["steel muted on obsidian", T.steel, T.obsidian, 4.5],
  ["steel muted on raised", T.steel, T.raised, 4.5],
  ["bone on raised", T.boneText, T.raised, 4.5],
  ["obsidian on bone (primary button)", T.obsidian, T.boneText, 4.5],
  ["bone on ink (primary button on light)", T.bone, T.ink, 4.5],
  ["ALLOW lamp word on obsidian", T.allowLamp, T.obsidian, 4.5],
  ["REVIEW lamp word on obsidian", T.reviewLamp, T.obsidian, 4.5],
  ["DENY lamp word on obsidian", T.denyLamp, T.obsidian, 4.5],
  ["ALLOW lamp word on raised", T.allowLamp, T.raised, 4.5],
  ["REVIEW lamp word on raised", T.reviewLamp, T.raised, 4.5],
  ["DENY lamp word on raised", T.denyLamp, T.raised, 4.5],
  ["obsidian word on ALLOW lamp plate", T.obsidian, T.allowLamp, 4.5],
  ["obsidian word on REVIEW lamp plate", T.obsidian, T.reviewLamp, 4.5],
  ["obsidian word on DENY lamp plate", T.obsidian, T.denyLamp, 4.5],
  ["bone focus ring on obsidian (non-text)", T.boneText, T.obsidian, 3.0],
  ["ink focus ring on bone (non-text)", T.ink, T.bone, 3.0],
  ["graphite hairline on obsidian (decorative)", T.graphite, T.obsidian, 1.0],
];
let fail = 0;
for (const [label, fg, bg, min] of pairs) {
  const r = ratio(fg, bg);
  const ok = r >= min;
  if (!ok) fail++;
  console.log(`| ${label} | \`${fg}\` on \`${bg}\` | ${r.toFixed(2)} | ${min} | ${ok ? "pass" : "FAIL"} |`);
}
process.exit(fail ? 1 : 0);
