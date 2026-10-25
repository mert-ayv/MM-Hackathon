"""Record the dashboard replay of one case to video, headless, at 1920x1080.

Usage (dashboard running on :8787):
  uv run --with playwright python video/demo-60s/record_replay.py RUN_ID CASE_ID OUT_DIR
"""
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

run_id, case_id, out_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
out_dir.mkdir(parents=True, exist_ok=True)
url = f"http://127.0.0.1:8787/#/replay/{run_id}/{case_id}"
size = {"width": 1920, "height": 1080}

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport=size, device_scale_factor=1, record_video_dir=str(out_dir), record_video_size=size)
    page = ctx.new_page()
    page.goto(url)
    page.wait_for_timeout(2500)
    page.evaluate("document.documentElement.style.zoom = '1.25'")  # readable text in the video
    page.wait_for_timeout(500)
    page.keyboard.press("Home")
    page.keyboard.press("4")  # Demo speed
    page.wait_for_timeout(1500)
    t0 = time.time()
    page.keyboard.press("Space")

    def clock():
        times = page.evaluate(
            "[...document.querySelectorAll('body *')].filter(e => e.children.length === 0)"
            ".map(e => e.textContent.trim()).filter(t => /^\\d\\d:\\d\\d$/.test(t))"
        )
        return times[:2]

    marks = []
    probe = ("(() => { const t = document.body.innerText;"
             " return [ (t.match(/Round \\d/) || [''])[0], (t.match(/Guten Tag/g) || []).length,"
             " (t.match(/Good day/g) || []).length, (t.match(/VERIFIED|verified/g) || []).length,"
             " /Accepted|Agreed/.test(t) ]; })()")
    while time.time() - t0 < 240:
        page.wait_for_timeout(250)
        m = [round(time.time() - t0, 2)] + page.evaluate(probe)
        if not marks or m[1:] != marks[-1][1:]:
            marks.append(m)
            print("mark", m, flush=True)
        c = clock()
        if len(c) == 2 and c[0] == c[1] and time.time() - t0 > 5:
            break
    page.wait_for_timeout(3000)  # hold the final frame
    print("played", round(time.time() - t0, 1), "s; clock", clock())
    video = page.video
    ctx.close()
    browser.close()
    print("video", video.path())
