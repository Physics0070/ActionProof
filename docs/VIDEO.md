# Demo video: what is rendered, what is not

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
