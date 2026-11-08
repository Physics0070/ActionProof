"""Record the REAL console: login (password never shown), queue, open the pending INV-2048 review, scroll to the
evidence + highlighted source span, type a reason, Approve, Confirm -> executed. Writes video/public/footage/console.webm
and video/data/request.json (what the console API returned for that request). Needs `python video/rec/prepare.py` first
(prints the request hash; pass it as argv[1]). python video/rec/record_console.py <hash>"""
import json, re, shutil, sys, tempfile, time
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).parent)); import creds
ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:5174"; H = sys.argv[1]
pw = creds.logins()["rev-alice"]
tmp = tempfile.mkdtemp(); T0 = time.time()
mark = lambda n: print(f"mark {n} {time.time()-T0:.1f}", flush=True)
with sync_playwright() as p:
    b = p.chromium.launch(channel="chromium", args=["--use-angle=d3d11", "--ignore-gpu-blocklist", "--enable-gpu-rasterization"])  # real GPU: smooth frames
    ctx = b.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=tmp, record_video_size={"width": 1920, "height": 1080})
    pg = ctx.new_page(); T0 = time.time()
    pg.add_init_script("document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');s.textContent='input[type=password]{color:transparent!important;-webkit-text-fill-color:transparent!important;text-shadow:none!important}';document.head.appendChild(s)})")
    pg.goto(BASE + "/console/login"); pg.wait_for_timeout(1800); mark("login_page")
    pg.get_by_label(re.compile("login|username", re.I)).type("rev-alice", delay=90)
    pg.get_by_label(re.compile("password", re.I)).fill(pw)
    pg.wait_for_timeout(500)
    pg.get_by_role("button", name=re.compile("sign in|log in|login", re.I)).click()
    pg.wait_for_url(re.compile(r"/console$|/console\?"), timeout=15000); pg.wait_for_timeout(2600); mark("queue")
    pg.mouse.move(960, 500)
    pg.locator(f'a[href$="{H}"]').first.hover(); pg.wait_for_timeout(700)
    pg.locator(f'a[href$="{H}"]').first.click()
    pg.wait_for_url(re.compile(H), timeout=15000); pg.wait_for_timeout(4200); mark("request_top")
    def scroll(total, seconds):
        t0 = time.time(); done = 0.0
        while True:
            el = min(time.time() - t0, seconds); want = total * el / seconds
            if want - done >= 1: pg.mouse.wheel(0, want - done); done = want
            if el >= seconds: break
            pg.wait_for_timeout(15)
    scroll(620, 3.5); pg.wait_for_timeout(3500); mark("evidence")
    scroll(430, 3.0); pg.wait_for_timeout(2500); mark("source_page")
    pg.locator("textarea").first.click()
    pg.keyboard.type("Reviewed the source page and the purchase order. Approving.", delay=45); pg.wait_for_timeout(700); mark("typed")
    pg.get_by_role("button", name=re.compile(r"^Approve", re.I)).click(); pg.wait_for_timeout(1400); mark("approve_click")
    pg.get_by_role("button", name=re.compile(r"Confirm approve", re.I)).click(); mark("confirm_click")
    pg.wait_for_timeout(6000); mark("after_confirm")
    # what the console API says about this request (shown values come from here)
    r = ctx.request.get(BASE + f"/api/requests/{H}"); (ROOT / "data" / "request.raw.json").write_text(r.text(), encoding="utf-8")
    pg.screenshot(path=str(ROOT / "data" / "console-end.png"))
    ctx.close(); b.close()
v = next(Path(tmp).glob("*.webm")); out = ROOT / "public" / "footage"; out.mkdir(parents=True, exist_ok=True)
shutil.copy(v, out / "console.webm"); print("saved", v.stat().st_size)
