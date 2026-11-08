# Demo video: what is rendered, what is not

Source of truth for timings and captions: [DEMO.md](DEMO.md). Deck row S8.4. Project: [`video/`](../video/README.md).

## Final cut (Remotion): `video-out/actionproof-demo.mp4` (git-ignored)
1920x1080, 30 fps, H.264, **205.06 s (3:25.06)** (cap 210 s), 61.1 MB (the file carries a silent AAC track added by the renderer). Silent: no voice-over, no music; every narration line is a
burned-in caption (46 px, bottom band, never over the content), and big on-screen type carries the rest. Look: the site's
"Airlock" palette and type (`web/DESIGN.md`), the latch motion verb, procedural corridor backgrounds, signal marks
(shape + word, never colour alone).

| Time | Chapter | Source of what is on screen |
|---|---|---|
| 0:00-0:12 | Cold open: hook, INV-2048 $4,800 vs PO $4,300, "Proof before permission." | amounts from the real demo card + console API (`request.json`) |
| 0:12-0:35 | The problem: three gaps, the filter that sees nothing wrong | deck wording (`web/lib/site-copy.ts`) |
| 0:35-1:25 | **The gate** (hero beat): real site gate scene, the real intercept card, five steps with the re-derivation, real console: rev-alice signs in, source span highlighted on the PDF page, reason, Approve, Confirm, executed once; "requested by agent-7 for user-123 · approved by a different person" | Playwright recordings of the production build + demo log |
| 1:25-1:45 | Injected PDF: hidden text, DENY AP-VER-01 (G1) | demo log beat 2 |
| 1:45-2:10 | Replay AP-REP-05 (G2); two $4,900 approvals under a $5,000 cap, one executes, other AP-CUM-03; same person via agent-8 | demo log beats 3-4 |
| 2:10-2:30 | Refund connector: injected destination (taint) DENY, clean retry DENY on the cap, small refund ALLOW | demo log beat 5 |
| 2:30-2:50 | `audit: OK (25 entries, 25 checkpoints)`, then an edited copy: `audit: FAILED at seq 9` | `video/tamper.py` (real verifier; the edit is made on a COPY of the database, with the append-only trigger disabled as a DB admin could) |
| 2:50-3:15 | Attacks executed per arm (of 211), the three targets, the disclosures, "What ActionProof does not claim" (4 limits) | `eval/results.json` copy |
| 3:15-3:25 | "Prove the action before the system executes it." / "Proof before permission." / ActionProof | deck |

Honest disclosures shown on screen: the held-out set is a second handwritten set, not independent; the independent generator
was blocked. ActionProof's one false block (1 of 120) is shown, not hidden.

## Data truth
Nothing on screen is typed by hand: `video/scripts/build-props.mjs` parses `video/data/demo-output.txt` (real `bash demo.sh`),
`eval-results.json`, `audit-run.txt` and `request.json` into `src/data.generated.json`; scenes read that. Console footage is
a live approval of a freshly minted REVIEW (`scripts/mint_review.py` path via `video/rec/prepare.py`), password field
rendered transparent and never printed. After recording, `bash demo.sh` was re-run so the demo database holds the real
decision and replay attempt again.

## Not included / limits
- No voice-over, no sound (nothing was sent to any external service). Add a narration track over the captions if wanted.
- AnimatedWebs backgrounds were not used (needs a signed-in Pro account); backgrounds are procedural.
- The console footage shows a request minted for the take (same content as the demo's INV-2048), not the demo.sh decision itself.
- The video renders needed `--offthreadvideo-cache-size-in-bytes` at concurrency 4 (Remotion otherwise raised "No frame found").

## Regenerate
See [video/README.md](../video/README.md).

---
# Earlier terminal-only cut (scripts/record_demo.py)

Source of truth for timings and captions: [DEMO.md](DEMO.md). Deck row S8.4.

## What the machine has (checked with `where` / `--version` only)
| Tool | Available |
|---|---|
| ffmpeg on PATH | no |
| Python `playwright` 1.65 + Chromium (and Playwright's bundled ffmpeg) | yes |
| Screen recorder (OBS) | not found |
| Pillow | yes |

## Rendered by `scripts/record_demo.py`
```bash
python scripts/record_demo.py                 # runs demo.sh, then renders video-out/actionproof-demo.webm
python scripts/record_demo.py --log video-out/demo-output.txt     # reuse a captured run
python scripts/record_demo.py --speed 12      # 15 s smoke render
```
- **`video-out/actionproof-demo.webm`**: 1280x720, 3:00, VP8 WebM (git-ignored). Opening card "Proof before permission." (0:00-0:12), beats 1-6 on the DEMO.md timings, closing card "Proof before permission." with "Prove the action before the system executes it." (2:56-3:00). Every terminal line is the real output of `demo.sh` (the script refuses to render a failing demo or one missing a beat); the page only reveals the lines on schedule, colours reason lines and shows the DEMO.md caption bar (beat 1: "requested by agent-7 for user-123 · approved by a different person").
- `video-out/demo-output.txt`: the exact captured output.

## NOT rendered
- **MP4.** Playwright's ffmpeg records but cannot transcode, and no system ffmpeg exists. Convert elsewhere: `ffmpeg -i actionproof-demo.webm -c:v libx264 -pix_fmt yuv420p actionproof-demo.mp4`.
- **Console and site footage inside the 3:00 cut.** They need the console API and the Next app running on the demo database. `record_demo.py --ui http://127.0.0.1:5173 --console-login rev-alice` records a separate `actionproof-ui.webm` (site scroll story, console login, first request) when they are up; it was not run here. It was never composited with the terminal clip: that edit (picture-in-picture at beats 1 and 3, as in the shot list) needs an editor.
- **Voice-over, music, cursor movement.** None exists. The narration spine is in DEMO.md.

## Shot list (final edit, 3:00)
| Time | Shot | Source | Caption |
|---|---|---|---|
| 0:00-0:12 | Title card | rendered | Before an AI agent acts, prove it should. |
| 0:12-1:20 | Terminal: slide-1 card; then console detail with the PDF box over `$4,800.00`; rev-alice approves; terminal "executed" | terminal rendered; console from `--ui` | requested by agent-7 for user-123 · approved by a different person |
| 1:20-1:42 | Terminal: hidden-text injection DENY AP-VER-01 | rendered | A hidden instruction in the PDF cannot authorize anything |
| 1:42-2:02 | Terminal: replay AP-REP-05; site signature panel step 4 | terminal rendered; site from `--ui` | A spent receipt replays: AP-REP-05 (G2) |
| 2:02-2:30 | Terminal: racing $4,900 approvals, agent-8 rotation | rendered | exactly one executes, AP-CUM-03 (G1) |
| 2:30-2:50 | Terminal: REF-311 taint, cap, small refund (cut if the taint does not land in one frame) | rendered | Same gate, second tool |
| 2:50-3:00 | Audit OK, closing card | rendered | Proof before permission. |

## Exact record commands for a human take
1. `bash demo.sh` once to check it prints PASS, then `DEMO_PAUSE=1 bash demo.sh` while screen-recording the terminal, or just use the rendered WebM.
2. Console and web on the demo database: `python scripts/demo_seed.py --reset && python scripts/seed_console.py`, `python -m actionproof.console`, `cd web && npm run dev`; record `http://localhost:5173`, then `/console`.
3. Join the clips in any editor following the shot list.

## Voiced version
`video-out/actionproof-demo-voiced.mp4` = the 3:25.06 video (video stream copied, not re-encoded) plus the voice-over (script: `docs/VOICEOVER.md`; recording: `video/audio/vo.mp3`, git-ignored so the voice is not published).

How it is built: `python video/scripts/mix-voiceover.py [vo.mp3] [video.mp4] [out.mp4]`. The voice file is one continuous take, so chapter boundaries (`video/data/vo-bounds.json`) were found by aligning the script's words to the detected speech segments (dynamic programming on pause positions), not by listening. Each chapter is cut at its boundary and placed at its video slot start + 0.3 s with exact silences between, then loudness-normalised (-16 LUFS target, -1.5 dB true peak) and encoded AAC 48 kHz mono. The script asserts every chapter's voice fits its slot (tightest: chapter 3, 46.7 s in a 50 s slot).

Verified from the output file: duration 3:25.06; chapter speech onsets at 12.3, 35.3, 85.3, 105.3, 130.3, 150.3, 170.3, 195.3 s (the planned slot starts). Not verified: that each boundary lands exactly between the right two sentences (inferred from words and pauses; no transcript was made), and numeric loudness of the final file.
