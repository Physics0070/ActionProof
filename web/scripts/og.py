"""Regenerates public/og.png (1200x630) from the live hero. Run against a production server: python scripts/og.py http://127.0.0.1:5174"""
import sys
from playwright.sync_api import sync_playwright

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5174"
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    page = b.new_context(viewport={"width": 1200, "height": 630}, bypass_csp=True).new_page()
    page.goto(base + "/", wait_until="load")
    page.wait_for_function("document.querySelector('.canvas-wrap')?.dataset.ready === 'true'", timeout=30000)
    page.wait_for_timeout(2500)
    page.add_style_tag(content=".rail,.site-head{display:none!important}")
    page.screenshot(path="public/og.png")
    b.close()
