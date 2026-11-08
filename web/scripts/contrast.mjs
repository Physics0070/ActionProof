// WCAG 2.x contrast ratios for every text/mark pairing the "Airlock" tokens allow (web/DESIGN.md "Contrast").
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
  // light surfaces (console, slips)
  mint: "#e7f2ec", paper: "#ffffff", ink: "#0a2b26", muted: "#416257", line: "#b7d0c5",
  allowInk: "#00604d", reviewInk: "#6b4f00", denyInk: "#b3260a",
  // spruce (the airlock)
  spruce: "#0a2b26", pine: "#11403a", frost: "#eef8f3", sage: "#a4c9be", moss: "#2d6157",
  pink: "#ff3d9a",
  allowLamp: "#34f0c2", reviewLamp: "#ffd11a", denyLamp: "#ff7d52",
};
// [label, fg, bg, min]: 4.5 body text, 3.0 large text or non-text marks (WCAG 1.4.11).
const pairs = [
  ["ink on mint ground", T.ink, T.mint, 4.5],
  ["muted on mint ground", T.muted, T.mint, 4.5],
  ["ink on white paper", T.ink, T.paper, 4.5],
  ["muted on white paper", T.muted, T.paper, 4.5],
  ["ALLOW ink word on mint", T.allowInk, T.mint, 4.5],
  ["REVIEW ink word on mint", T.reviewInk, T.mint, 4.5],
  ["DENY ink word on mint", T.denyInk, T.mint, 4.5],
  ["ALLOW ink word on white", T.allowInk, T.paper, 4.5],
  ["REVIEW ink word on white", T.reviewInk, T.paper, 4.5],
  ["DENY ink word on white", T.denyInk, T.paper, 4.5],
  ["frost text on spruce", T.frost, T.spruce, 4.5],
  ["sage muted on spruce", T.sage, T.spruce, 4.5],
  ["sage muted on pine", T.sage, T.pine, 4.5],
  ["frost on pine", T.frost, T.pine, 4.5],
  ["pink on spruce (USP line, closing line)", T.pink, T.spruce, 4.5],
  ["spruce ink on pink (CTA, claims chapter, $500 slip)", T.spruce, T.pink, 4.5],
  ["frost on spruce card (claims cards on pink)", T.frost, T.spruce, 4.5],
  ["ALLOW lamp word on spruce", T.allowLamp, T.spruce, 4.5],
  ["REVIEW lamp word on spruce", T.reviewLamp, T.spruce, 4.5],
  ["DENY lamp word on spruce", T.denyLamp, T.spruce, 4.5],
  ["ALLOW lamp word on pine", T.allowLamp, T.pine, 4.5],
  ["REVIEW lamp word on pine", T.reviewLamp, T.pine, 4.5],
  ["DENY lamp word on pine", T.denyLamp, T.pine, 4.5],
  ["spruce word on ALLOW lamp plate", T.spruce, T.allowLamp, 4.5],
  ["spruce word on REVIEW lamp plate", T.spruce, T.reviewLamp, 4.5],
  ["spruce word on DENY lamp plate", T.spruce, T.denyLamp, 4.5],
  ["pink focus ring on spruce (non-text)", T.pink, T.spruce, 3.0],
  ["ink focus ring on mint (non-text)", T.ink, T.mint, 3.0],
  ["spruce focus ring on pink (non-text)", T.spruce, T.pink, 3.0],
  ["moss hairline on spruce (decorative)", T.moss, T.spruce, 1.0],
];
let fail = 0;
for (const [label, fg, bg, min] of pairs) {
  const r = ratio(fg, bg);
  const ok = r >= min;
  if (!ok) fail++;
  console.log(`| ${label} | \`${fg}\` on \`${bg}\` | ${r.toFixed(2)} | ${min} | ${ok ? "pass" : "FAIL"} |`);
}
process.exit(fail ? 1 : 0);
