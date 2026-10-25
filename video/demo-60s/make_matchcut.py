"""Text match cut for the intro: many procurement documents, the phrase "price increase" always highlighted
at the exact centre of the frame. Writes one PNG per document. Company names are invented or from the case."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
K = '<span id="k">price increase</span>'

# (background, text colour, font family, font size px, extra css, html)
DOCS = [
    ("#ffffff", "#222", "-apple-system, Helvetica Neue, sans-serif", 46, "", f"""
      <div style="color:#888;font-size:30px">From: sales@nordmark-antriebe.example · To: purchasing@hollerau.example</div>
      <div style="font-weight:700;margin:18px 0">Subject: Notice of {K} – frequency converters</div>
      Dear purchasing team,<br>due to rising copper and electronics costs we have to announce a price increase of 7.5 %
      effective 1 March. We thank you for your understanding."""),
    ("#f6f0e3", "#2b2418", "Georgia, Times New Roman, serif", 50, "", f"""
      <div style="text-align:right;font-size:32px">Ravensteiner Dichtungswerk GmbH · 12 September</div><br>
      Sehr geehrte Damen und Herren,<br>after careful review of our cost base we must inform you of a
      {K} on all seal kits, effective with the next delivery. Mit freundlichen Grüßen"""),
    ("#ffffff", "#111", "Georgia, serif", 74, "font-weight:700;letter-spacing:-1px", f"""
      <div style="font-size:28px;letter-spacing:3px;color:#b00;font-weight:600">INDUSTRY</div>
      Mid-sized suppliers push the next {K} as energy costs climb again"""),
    ("#eceff3", "#1d2733", "Menlo, monospace", 40, "", f"""
      § 4.2 Prices are fixed per calendar year.<br>§ 4.3 Any {K} requires ninety (90) days'<br>
      written notice and the buyer's written consent.<br>§ 4.4 Payment: 60 days net."""),
    ("#e9e2f5", "#222", "-apple-system, sans-serif", 54, "", f"""
      <div style="background:#fff;border-radius:28px;padding:28px 40px;display:inline-block;box-shadow:0 6px 20px #0002">
      <b>Anna (Purchasing)</b><br>another {K} letter just came in 😩<br>that's the fourth this week</div>"""),
    ("#ffffff", "#1f1f1f", "Arial, sans-serif", 40, "", f"""
      <table style="border-collapse:collapse;font-size:38px">
      <tr style="background:#1f6f43;color:#fff"><td>Supplier</td><td>Part</td><td>Reason</td><td>Ask</td></tr>
      <tr><td>Blankstahl Werdenfels</td><td>Shaft 42CrMo4</td><td>{K}</td><td>+6.2 %</td></tr>
      <tr><td>Edelstahl Donautal</td><td>Bar 1.4404</td><td>alloy surcharge</td><td>+4.1 %</td></tr></table>"""),
    ("#fffdf7", "#333", "Times New Roman, serif", 48, "", f"""
      <div style="font-size:30px;color:#777">INVOICE 2026-10-4471 · Schraubenhandel Leitner &amp; Sohn</div><br>
      Pos. 3 &nbsp; Surcharge – {K} (raw material) &nbsp;&nbsp; EUR 1,284.00<br>Total due within 30 days"""),
    ("#0f1b2d", "#e8eef7", "-apple-system, sans-serif", 60, "font-weight:600", f"""
      <div style="font-size:30px;color:#7fa7d9">PROCUREMENT WEEKLY · ISSUE 41</div>
      How to answer a {K} in 48 hours – and when to push back"""),
    ("#ffffff", "#222", "Helvetica Neue, sans-serif", 52, "", f"""
      <div style="font-size:30px;color:#999">Q3 REVIEW · CATEGORY CASTINGS</div>
      37 open {K} requests · €1.9M at stake · 2 buyers"""),
    ("#fff59a", "#2a2a2a", "Bradley Hand, Marker Felt, cursive", 64, "", f"""
      call Brandlhuber back<br>about the {K}!!<br>(before Friday)"""),
    ("#ffffff", "#222", "-apple-system, sans-serif", 46, "", f"""
      <div style="font-weight:700">Re: Notice of {K}</div><br>Thank you for your letter. We cannot accept an
      increase of this size. Your letter gives 51 days' notice, our agreement requires 90."""),
    ("#f3f4f6", "#111", "-apple-system, sans-serif", 48, "", f"""
      <div style="background:#fff;border-left:10px solid #F2552C;border-radius:14px;padding:30px 40px;box-shadow:0 8px 30px #0001">
      <div style="font-size:28px;color:#888">INBOX · 09:14</div>
      New {K} from Antriebstechnik Nordmark – reply due in 5 days</div>"""),
    ("#f6f0e3", "#2b2418", "Georgia, serif", 50, "", f"""
      Gießerei Brandlhuber GmbH &amp; Co. KG<br><br>Guten Tag,<br>for many years our family foundry has supplied
      you. We must now announce a {K} of 9.5 % on HN volute casings, valid from 1 November 2026."""),
]

CSS = """
* { margin:0; box-sizing:border-box; }
html, body { width:1920px; height:1080px; overflow:hidden; }
#doc { position:absolute; left:0; top:0; width:2300px; zoom:1.7; padding:60px 80px; line-height:1.45; }
#doc * { filter: blur(0.6px); }
#k { filter:none !important; font-size:56px; line-height:1.15; display:inline-block; background:#F2552C; color:#fff; padding:2px 14px; border-radius:8px;
     font-weight:700; white-space:nowrap; box-shadow:0 6px 24px rgba(242,85,44,.35); }
#vig { position:absolute; inset:0; pointer-events:none;
       background: radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(0,0,0,.28) 100%); }
"""

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width": 1920, "height": 1080})
    for i, (bg, fg, font, size, extra, html) in enumerate(DOCS):
        page.set_content(f"""<html><head><style>{CSS}</style></head>
          <body style="background:{bg}"><div id="doc" style="color:{fg};font-family:{font};font-size:{size}px;{extra}">{html}</div>
          <div id="vig"></div></body></html>""")
        page.wait_for_timeout(150)
        # move the document so the keyword's centre sits exactly at the frame centre
        page.evaluate("""() => {
          const k = document.getElementById('k').getBoundingClientRect();
          const d = document.getElementById('doc');
          d.style.left = ((960 - (k.left + k.width / 2)) / 1.7) + 'px';  // #doc has zoom 1.7
          d.style.top = ((540 - (k.top + k.height / 2)) / 1.7) + 'px';
        }""")
        page.screenshot(path=str(OUT / f"mc_{i:02d}.png"))
    b.close()
print(len(DOCS), "frames")
