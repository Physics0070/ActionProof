"""Render the demo to a WebM from the REAL output of demo.sh, timed to docs/DEMO.md.

    python scripts/record_demo.py                     # run demo.sh, then render video-out/actionproof-demo.webm (3:00)
    python scripts/record_demo.py --log run.txt       # reuse a captured demo.sh output instead of running it
    python scripts/record_demo.py --speed 10          # render 10x faster (smoke test; real timings are speed 1)
    python scripts/record_demo.py --ui http://127.0.0.1:5173 [--console-login rev-alice]
                                                      # also record the site / console as video-out/actionproof-ui.webm

What is real: every terminal line is the gate's output captured from `demo.sh` (nothing typed by hand); the page
only reveals those lines on the DEMO.md beat timings and adds the title/closing cards and captions.
Needs: Python playwright + a Chromium (`python -m playwright install chromium`). Output is WebM (VP8): Playwright's
bundled ffmpeg records but cannot transcode, so no MP4 is produced here (convert elsewhere: ffmpeg -i x.webm x.mp4).
The UI clip needs the console + web already running on the demo database (docs/RUNBOOK.md, no Docker section).
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "video-out"
USP = "Proof before permission."
LABEL = "requested by agent-7 for user-123 · approved by a different person"
# (key, seconds, caption) from docs/DEMO.md. Beat keys match "--- BEAT n:" lines of demo.py; "0"/"end" are cards.
TIMELINE = [
    ("0", 12, "Before an AI agent acts, prove it should."),
    ("1", 68, LABEL),
    ("2", 22, "A hidden instruction in the PDF cannot authorize anything: AP-VER-01 (G1)"),
    ("3", 20, "A spent receipt replays: AP-REP-05 (G2)"),
    ("4", 28, "Two $4,900 approvals race: exactly one executes, AP-CUM-03 (G1)"),
    ("5", 20, "Same gate, second tool: the refund destination is an authority field"),
    ("6", 6, "Every decision is in a signed, hash-chained audit log"),
    ("end", 4, USP),
]
PAGE = """<!doctype html><meta charset=utf-8><title>ActionProof demo</title><style>
html,body{margin:0;height:100%;background:#0b0f14;color:#d7dde4;font:15px/1.35 Consolas,'DejaVu Sans Mono',monospace;overflow:hidden}
#term{position:absolute;inset:48px 56px 96px 56px;overflow:hidden;white-space:pre;display:flex;flex-direction:column;justify-content:flex-end}
.ok{color:#4ade80}.fail{color:#f87171}.reason{color:#fbbf24}.hd{color:#67e8f9;font-weight:bold}.dim{color:#7b8794}
#cap{position:absolute;left:0;right:0;bottom:0;height:72px;background:#111923;border-top:1px solid #243244;display:flex;align-items:center;justify-content:center;font:600 22px/1.2 system-ui,sans-serif;color:#fff;padding:0 32px;text-align:center}
#card{position:absolute;inset:0;background:#0b0f14;display:none;flex-direction:column;align-items:center;justify-content:center;text-align:center;font-family:system-ui,sans-serif}
#card h1{font-size:68px;margin:0 0 18px;color:#fff}#card p{font-size:26px;margin:0;color:#9fb3c8}
</style><div id=term></div><div id=cap></div><div id=card><h1></h1><p></p></div>
<script>
const PLAN=__PLAN__, LINES=__LINES__, SPEED=__SPEED__;
const term=document.getElementById('term'),cap=document.getElementById('cap'),card=document.getElementById('card');
function cls(t){return /\\[ OK \\]|^ok /.test(t.trim())||/ ok  /.test(t.slice(0,8))?'ok':/\\[FAIL\\]|FAIL/.test(t)?'fail':/reason:/.test(t)?'reason':/^---|^===|BEAT/.test(t.trim())?'hd':/^\\s{4}(real MCP|document text|cap |an approval|refund dest)/.test(t)?'dim':''}
function add(t){const d=document.createElement('div');d.className=cls(t);d.textContent=t||' ';term.appendChild(d);while(term.children.length>34)term.removeChild(term.firstChild)}
window.run=async function(){
  const sleep=ms=>new Promise(r=>setTimeout(r,ms/SPEED));
  for(const [key,secs,caption] of PLAN){
    cap.textContent=caption;
    if(key==='0'||key==='end'){term.style.display='none';card.style.display='flex';card.querySelector('h1').textContent=key==='0'?'ActionProof':'__USP__';
      card.querySelector('p').textContent=key==='0'?'__USP__ Before an AI agent acts, prove it should.':'Prove the action before the system executes it.';await sleep(secs*1000);continue}
    card.style.display='none';term.style.display='flex';term.innerHTML='';
    const ls=LINES[key]||[];const span=secs*1000*0.8;
    for(const l of ls){add(l);await sleep(span/Math.max(ls.length,1))}
    await sleep(secs*1000*0.2);
  }
  window.done=true;
};
</script>"""


def capture() -> str:
    env = {**os.environ, "NO_COLOR": "1", "DEMO_ASCII": "1", "DEMO_PAUSE": "0",
           "DEMO_DB": os.environ.get("DEMO_DB", "actionproof_demo_rec")}
    r = subprocess.run(["bash", str(ROOT / "demo.sh")], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=ROOT, timeout=900)
    if r.returncode != 0:
        sys.exit(f"demo.sh failed (exit {r.returncode}); not rendering a video of a failing demo:\n{r.stdout[-1500:]}")
    return r.stdout


def split_beats(text: str) -> dict[str, list[str]]:
    beats: dict[str, list[str]] = {}
    key = None
    for line in text.splitlines():
        m = re.match(r"--- BEAT (\d+):", line)
        if m:
            key = m.group(1)
        elif line.startswith("  RESULT") or line.startswith("PASS:"):
            key = "6" if key else key
        if key:
            beats.setdefault(key, []).append(line)
    return beats


def render(beats: dict[str, list[str]], speed: float) -> Path:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(exist_ok=True)
    page_html = (PAGE.replace("__PLAN__", json.dumps(TIMELINE)).replace("__LINES__", json.dumps(beats))
                 .replace("__SPEED__", str(speed)).replace("__USP__", html.escape(USP)))
    tmp = Path(tempfile.mkdtemp(prefix="ap-rec-"))
    (tmp / "index.html").write_text(page_html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(tmp),
                            record_video_size={"width": 1280, "height": 720})
        pg = ctx.new_page()
        pg.goto((tmp / "index.html").as_uri())
        pg.evaluate("window.run()")
        pg.wait_for_function("window.done === true", timeout=int(240_000 / speed) + 60_000)
        video = pg.video
        ctx.close()
        dest = OUT / "actionproof-demo.webm"
        video.save_as(str(dest))
        b.close()
    return dest


def record_ui(base: str, login: str | None) -> Path | None:
    from playwright.sync_api import sync_playwright

    import urllib.request
    try:
        urllib.request.urlopen(base, timeout=3).close()
    except Exception:
        print(f"UI not reachable at {base}: skipping the UI clip (start console + web, see docs/RUNBOOK.md)")
        return None
    tmp = Path(tempfile.mkdtemp(prefix="ap-ui-"))
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(tmp),
                            record_video_size={"width": 1280, "height": 720})
        pg = ctx.new_page()
        pg.goto(base)
        for _ in range(8):  # the scroll story of the public site, then the recorded INV-2048 proof
            pg.mouse.wheel(0, 700)
            time.sleep(1.5)
        pw = os.environ.get("CONSOLE_PASSWORD_" + (login or "").upper().replace("-", "_"))
        if login and pw:
            pg.goto(f"{base}/console/login")
            pg.fill("input[name=login], input[type=text]", login)
            pg.fill("input[type=password]", pw)
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(2500)
            link = pg.locator("a[href*='/console/requests/']").first
            if link.count():
                link.click()
                pg.wait_for_timeout(5000)
        else:
            print("console part skipped: pass --console-login rev-alice and set CONSOLE_PASSWORD_REV_ALICE")
        video = pg.video
        ctx.close()
        dest = OUT / "actionproof-ui.webm"
        video.save_as(str(dest))
        b.close()
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log", help="reuse the captured output of demo.sh instead of running it")
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed-up for smoke tests (default 1 = 3:00)")
    ap.add_argument("--ui", help="base URL of the running web app to record as a second clip")
    ap.add_argument("--console-login", help="console login for the UI clip (password from CONSOLE_PASSWORD_<LOGIN>)")
    args = ap.parse_args(argv)
    text = Path(args.log).read_text(encoding="utf-8") if args.log else capture()
    beats = split_beats(text)
    missing = [k for k, _, _ in TIMELINE if k not in ("0", "end") and k not in beats]
    if missing:
        sys.exit(f"demo output has no beat(s) {missing}: refusing to render")
    OUT.mkdir(exist_ok=True)
    (OUT / "demo-output.txt").write_text(text, encoding="utf-8")
    dest = render(beats, args.speed)
    total = sum(s for _, s, _ in TIMELINE)
    print(f"wrote {dest} ({dest.stat().st_size // 1024} KiB, timeline {total}s at speed {args.speed:g})")
    if args.ui:
        ui = record_ui(args.ui, args.console_login)
        if ui:
            print(f"wrote {ui}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
