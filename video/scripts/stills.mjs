// node scripts/stills.mjs 2 6 10 ...  -> data/fr/s<sec>.png (full-size stills at those seconds) and data/fr/sheet_s.png contact sheet
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import path from "node:path";
const secs = process.argv.slice(2).map(Number);
const entry = path.resolve("src/index.ts");
const serveUrl = await bundle({ entryPoint: entry, publicDir: path.resolve("public") });
const comp = await selectComposition({ serveUrl, id: "Demo" });
for (const s of secs) {
  await renderStill({ composition: comp, serveUrl, frame: Math.round(s * 30), output: `data/fr/s${s}.png`, scale: 0.5 });
  console.log("still", s);
}
