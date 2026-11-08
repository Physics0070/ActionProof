# ActionProof explainer video (Remotion, not a product dependency)

1920x1080, 30 fps, H.264, 205 s (hard cap 210 s), silent with burned-in captions. Palette and type are the "Airlock"
system of `web/DESIGN.md`; the one motion verb is the latch (`cubic-bezier(0.2,0,0,1)`, no bounce). Backgrounds are
procedural (SVG rings, frame-driven). Every number, rule id and quote on screen is generated from real artifacts:
`data/demo-output.txt` (real `bash demo.sh`), `data/eval-results.json` (copy of `eval/results.json`),
`data/audit-run.txt` (real audit verifier, clean DB and an edited copy), `data/request.json` (console API response for the
approved request). Footage is recorded from the running production site and console with Playwright.

## Regenerate (from the repo root; services up: Postgres, OPA, console API :8766, web :5174)
```bash
set -a; . ./.env.example; set +a
# 1. the real demo output (exit 0 only if every beat passed)
DEMO_ASCII=1 PYTHONIOENCODING=utf-8 bash demo.sh > video/data/demo-output.txt
# 2. audit: verify, edit one row of a COPY, verify again (real verifier)
PYTHONPATH=src .venv/Scripts/python.exe video/tamper.py
# 3. eval numbers
cp eval/results.json video/data/eval-results.json
# 4. footage: reset + seed + mint a pending review (prints its request hash), then record
.venv/Scripts/python.exe video/rec/prepare.py                  # -> {"request_hash": "..."}
python video/rec/record_gate.py                                # needs system Python Playwright + Chromium
python video/rec/record_console.py <request_hash>              # logins read from keys/demo-logins.txt, never printed
cd video && npm install
npx remotion ffmpeg -y -i public/footage/gate.webm -c:v libx264 -crf 15 -pix_fmt yuv420p -r 30 public/footage/gate.mp4
npx remotion ffmpeg -y -i public/footage/console.webm -c:v libx264 -crf 15 -pix_fmt yuv420p -r 30 public/footage/console.mp4
# 5. data -> props, render
node scripts/build-props.mjs
npm run render                                                 # -> ../video-out/actionproof-demo.mp4
node scripts/stills.mjs 10 58 100                              # quick look: data/fr/s<sec>.png
```
After step 4 re-run `bash demo.sh` once more so the demo database is back to the real decision + replay state.
Footage offsets live in `src/clips.ts` and `src/S3_Hero.tsx` (tuned against extracted frames).

## Layout
`src/Root.tsx` timeline and captions; `S1_Cold`..`S9_Close` scenes; `Footage.tsx` framed recording with a latch-eased
camera; `Card.tsx` the real intercept card; `facts.ts` typed accessors over `src/data.generated.json`.
