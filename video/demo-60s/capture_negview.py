"""Stills of the Tactopus negotiation view (hero card, gap chart) at 1920x1080 for the demo video."""
import sys
from playwright.sync_api import sync_playwright

run, case, out = sys.argv[1], sys.argv[2], sys.argv[3]
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(f"http://127.0.0.1:8787/#/n/{run}/{case}")
    page.wait_for_timeout(3000)
    page.evaluate("document.documentElement.style.zoom = '1.25'")
    page.wait_for_timeout(800)
    page.screenshot(path=f"{out}/hero.png")
    page.mouse.move(960, 600)
    page.mouse.wheel(0, 640)
    page.wait_for_timeout(1000)
    page.screenshot(path=f"{out}/gap.png")
    b.close()
