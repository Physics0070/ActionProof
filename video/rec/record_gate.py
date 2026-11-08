"""Record the REAL production site (http://127.0.0.1:5174): hero, problem, then the scroll-into-the-gate scene.
Output: video/footage/gate.webm (1920x1080). python video/rec/record_gate.py"""
import shutil, sys, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
OUT = Path(__file__).resolve().parents[1] / "public" / "footage"
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5174"
tmp = tempfile.mkdtemp()
with sync_playwright() as p:
    b = p.chromium.launch(channel="chromium", args=["--use-angle=d3d11", "--ignore-gpu-blocklist", "--enable-gpu-rasterization"])  # real GPU: smooth frames
    ctx = b.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=tmp, record_video_size={"width": 1920, "height": 1080})
    pg = ctx.new_page()
    pg.goto(BASE + "/"); pg.wait_for_timeout(500); pg.wait_for_timeout(4500)       # hero 0-5 s
    pg.mouse.move(960, 540)
    import time
    def scroll(total, seconds):               # time-based: the wheel call itself takes ~0.15 s under software GL
        t0 = time.time(); done = 0.0
        while True:
            el = min(time.time() - t0, seconds)
            want = total * el / seconds
            if want - done >= 1:
                pg.mouse.wheel(0, want - done); done = want
            if el >= seconds: break
            pg.wait_for_timeout(15)
    print("t_problem_start", flush=True); scroll(1330, 7)                                  # problem chapter
    pg.wait_for_timeout(1500)
    y0 = pg.evaluate("scrollY"); print("scrollY at gate start", y0)
    scroll(5050 - (y0 - 2410) , 44)                  # through the gate (pinned stage ~5000 px)
    pg.wait_for_timeout(2500)
    print("scrollY end", pg.evaluate("scrollY"))
    ctx.close(); b.close()
v = next(Path(tmp).glob("*.webm"))
shutil.copy(v, OUT / "gate.webm"); print(OUT / "gate.webm", v.stat().st_size)
