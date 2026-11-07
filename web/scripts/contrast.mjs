// WCAG 2.x contrast ratios for every text/mark pairing the tokens allow (web/DESIGN.md "Contrast").
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
  mist: "#f6f8f7", paper: "#ffffff", ink: "#15141f", muted: "#55535f", line: "#c9ccd0",
  carbon: "#15141f", carbonRaised: "#211f2d", carbonText: "#f6f8f7", carbonMuted: "#a9a7b4", carbonLine: "#3a3846",
  amber: "#f5a524",
  allowLamp: "#3ddc84", reviewLamp: "#f5a524", denyLamp: "#ff5a4a",
  allowInk: "#0b6b35", reviewInk: "#7f4d00", denyInk: "#b3261e",
};
// [label, fg, bg, min] — 4.5 body text, 3.0 large text / non-text marks (WCAG 1.4.11).
const pairs = [
  ["ink on mist", T.ink, T.mist, 4.5],
  ["muted on mist", T.muted, T.mist, 4.5],
  ["ink on paper", T.ink, T.paper, 4.5],
  ["hairline on mist (non-text)", T.line, T.mist, 1.0],
  ["carbon text on carbon", T.carbonText, T.carbon, 4.5],
  ["carbon muted on carbon", T.carbonMuted, T.carbon, 4.5],
  ["carbon muted on carbon raised", T.carbonMuted, T.carbonRaised, 4.5],
  ["amber on carbon", T.amber, T.carbon, 4.5],
  ["ink on amber (filled CTA)", T.ink, T.amber, 4.5],
  ["ALLOW ink word on mist", T.allowInk, T.mist, 4.5],
  ["REVIEW ink word on mist", T.reviewInk, T.mist, 4.5],
  ["DENY ink word on mist", T.denyInk, T.mist, 4.5],
  ["ALLOW lamp word on carbon", T.allowLamp, T.carbon, 4.5],
  ["REVIEW lamp word on carbon", T.reviewLamp, T.carbon, 4.5],
  ["DENY lamp word on carbon", T.denyLamp, T.carbon, 4.5],
  ["ink word on ALLOW lamp", T.ink, T.allowLamp, 4.5],
  ["ink word on REVIEW lamp", T.ink, T.reviewLamp, 4.5],
  ["ink word on DENY lamp", T.ink, T.denyLamp, 4.5],
  ["ALLOW ink mark on mist (non-text)", T.allowInk, T.mist, 3.0],
  ["DENY lamp vs ALLOW lamp (non-text, shape also differs)", T.denyLamp, T.allowLamp, 1.0],
];
let fail = 0;
for (const [label, fg, bg, min] of pairs) {
  const r = ratio(fg, bg);
  const ok = r >= min;
  if (!ok) fail++;
  console.log(`| ${label} | \`${fg}\` on \`${bg}\` | ${r.toFixed(2)} | ${min} | ${ok ? "pass" : "FAIL"} |`);
}
process.exit(fail ? 1 : 0);
