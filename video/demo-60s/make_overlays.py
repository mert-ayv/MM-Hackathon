"""Transparent 1920x1080 overlay cards (Tactopus style) for the presenter shots, plus the end card."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

CSS = """
* { margin: 0; box-sizing: border-box; }
html, body { width: 1920px; height: 1080px; background: transparent;
  font-family: -apple-system, "SF Pro Display", "Helvetica Neue", Arial, sans-serif; }
.card { position: absolute; background: #fff; border-radius: 22px; padding: 26px 34px;
  box-shadow: 0 18px 50px rgba(0,0,0,.28); color: #111; }
.big { font-size: 76px; font-weight: 800; letter-spacing: -2px; line-height: 1; }
.small { font-size: 26px; font-weight: 500; color: #555; margin-top: 10px; }
.or { color: #F2552C; }
.strike { color: #999; text-decoration: line-through; font-weight: 600; }
.name { position: absolute; left: 90px; bottom: 90px; background: #111; color: #fff; border-radius: 16px;
  padding: 18px 28px; font-size: 32px; font-weight: 700; }
.name span { color: #F2552C; font-weight: 600; margin-left: 12px; font-size: 26px; }
"""

CARDS = {
    "card_95": '<div class="card" style="left:90px;top:300px"><div class="big or">+9.5 %</div>'
               '<div class="small">price increase from 1 November</div></div>',
    "card_deals": '<div class="card" style="left:90px;top:250px"><div class="big">10 / 10</div>'
                  '<div class="small">practice negotiations closed</div></div>',
    "card_77": '<div class="card" style="left:90px;top:520px"><div class="big or">77 %</div>'
               '<div class="small">of the best possible saving</div></div>',
    "card_70": '<div class="card" style="left:90px;top:380px"><div class="big"><span class="or">77 %</span>'
               ' <span style="font-size:44px;color:#999;font-weight:600">vs</span> 70 %</div>'
               '<div class="small">ours vs Tacto\'s own agent · same 10 practice cases</div></div>',
    "name_mert": '<div class="name">Mert<span>csee-base</span></div>',
    "name_ege": '<div class="name">Ege<span>csee-base</span></div>',
}

END = """
<div style="position:absolute;inset:0;background:#fff;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:26px">
  <div style="font-size:120px;font-weight:800;letter-spacing:-4px;color:#111">csee-base</div>
  <div style="font-size:38px;font-weight:500;color:#555">Our AI buyer reads the supplier before it negotiates.</div>
  <div style="font-size:26px;font-weight:600;color:#F2552C;margin-top:18px">Tacto Negotiation Arena · Munich 2026</div>
</div>
"""

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width": 1920, "height": 1080})
    for name, html in {**CARDS, "endcard": END}.items():
        page.set_content(f"<html><head><style>{CSS}</style></head><body>{html}</body></html>")
        page.screenshot(path=str(OUT / f"{name}.png"), omit_background=name != "endcard")
    b.close()
print("ok", sorted(f.name for f in OUT.glob("*.png")))
