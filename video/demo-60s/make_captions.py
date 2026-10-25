"""Burned-in captions for the demo video: one transparent PNG per caption plus an ffmpeg filter script.
Times are seconds in csee-base-demo.mp4 (from a Whisper word-timestamp pass over the final mix, text
corrected against the script). Speaker labels only where no face is on screen (the AI voices)."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
B, S = "OUR AI BUYER", "SUPPLIER"
CAPS = [
    (2.15, 4.45, "", "Our supplier for pump housings"),
    (4.50, 7.00, "", "just raised the price by 9.5 %."),
    (7.30, 9.40, "", "For the Tacto Negotiation Arena,"),
    (9.42, 10.54, "", "we built an AI buyer"),
    (10.56, 12.44, "", "that negotiates this alone,"),
    (12.46, 13.40, "", "just by email."),
    (13.70, 16.00, B, "Supplier's letter is in: +9.5 %."),
    (16.75, 19.50, S, "We can offer you a price of €138.55"),
    (19.52, 22.40, S, "per unit, valid from 1 November."),
    (22.68, 25.00, B, "We cannot accept an increase of this size."),
    (25.24, 27.50, B, "Your letter gives 51 days' notice –"),
    (27.54, 29.20, B, "our agreement requires 90."),
    (29.44, 32.60, S, "We checked the notice period you cited… it holds."),
    (33.18, 35.40, S, "We did not know that. A fair point."),
    (35.58, 37.20, S, "We accept your offer:"),
    (37.24, 41.40, S, "€132.85 per unit, 14 days net, from April."),
    (41.74, 43.70, B, "9.5 % became 5 %."),
    (43.92, 46.20, B, "€55,000 saved."),
    (47.48, 48.74, "", "Code sets every number,"),
    (48.76, 51.20, "", "and our language model only writes the words."),
    (51.66, 52.95, "", "10 of 10 deals,"),
    (53.02, 55.05, "", "77 % of the best possible saving."),
    (55.12, 57.00, "", "Tacto's own agent gets only 70."),
    (57.16, 58.20, "", "We are csee-base."),
]

CSS = """
* { margin:0; box-sizing:border-box; }
html, body { width:1920px; height:1080px; background:transparent;
  font-family:-apple-system, "SF Pro Display", "Helvetica Neue", Arial, sans-serif; }
.wrap { position:absolute; left:0; right:0; bottom:70px; display:flex; justify-content:center; }
.cap { background:rgba(12,12,12,.78); border-radius:18px; padding:16px 30px 18px; max-width:1300px; text-align:center; }
.who { color:#F2552C; font-size:22px; font-weight:700; letter-spacing:2.5px; margin-bottom:4px; }
.txt { color:#fff; font-size:46px; font-weight:700; line-height:1.18; }
"""

filters, inputs = [], []
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width": 1920, "height": 1080})
    for i, (t0, t1, who, text) in enumerate(CAPS):
        label = f'<div class="who">{who}</div>' if who else ""
        page.set_content(f'<html><head><style>{CSS}</style></head><body><div class="wrap"><div class="cap">'
                         f'{label}<div class="txt">{text}</div></div></div></body></html>')
        png = OUT / f"cap_{i:02d}.png"
        page.screenshot(path=str(png), omit_background=True)
        inputs.append(str(png))
        prev = "[0:v]" if i == 0 else f"[c{i}]"
        nxt = "[vout]" if i == len(CAPS) - 1 else f"[c{i + 1}]"
        filters.append(f"{prev}[{i + 1}:v]overlay=enable='between(t,{t0},{t1})'{nxt}")
    b.close()
(OUT / "inputs.txt").write_text("\n".join(inputs))
(OUT / "filter.txt").write_text(";\n".join(filters))
(OUT / "captions.json").write_text(json.dumps(CAPS, ensure_ascii=False, indent=1))
print(len(CAPS), "captions")
