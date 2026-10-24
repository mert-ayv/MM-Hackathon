"""`uv run python -m csee.dossier [package dir]`: what the package as loaded now (incl. the Sunday release) adds to
the static dossier, per supplier: new hedges, price letters, cash asks, news. Read-only; run it after
`uv run arena data` on Sunday 08:00. The agent re-derives the same fields itself at runtime (dossier.get)."""

import sys
from pathlib import Path

from arena_kit.data import DataPackage

from . import _load, derive

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parents[2] / "data" / "package"
pkg = DataPackage(root)
print(f"package {pkg.root}  release {pkg.release or '(none)'}")
static = _load()
changed = 0
for sid, e in sorted(static.items()):
    live = derive(pkg, sid)
    old_h = {(h.get("material"), h.get("until")) for h in e.get("hedges", [])}
    new_h = [h for h in live["hedges"] if (h.get("material"), h.get("until")) not in old_h]
    old_l = {x["id"] for x in e.get("price_letters", [])}
    new_l = [x for x in live["price_letters"] if x["id"] not in old_l]
    new_c = sorted(set(live["cash_asks"]) - set(e.get("cash_asks", [])))
    old_n = {x["id"] for x in e.get("news", [])}
    new_n = [x for x in live["news"] if x["id"] not in old_n]
    if not (new_h or new_l or new_c or new_n):
        continue
    changed += 1
    print(f"\n{sid} {e.get('name')}")
    for h in new_h:
        print(f"  HEDGE   {h['material']} until {h['until']} -> series {h['series']} {h['ids']}")
    for x in new_l:
        print(f"  LETTER  {x['id']} asked {x.get('asked_pct')} % / {x.get('asked_price')} from {x.get('effective_date')}")
    for x in new_c:
        print(f"  CASH    {x}")
    for x in new_n:
        print(f"  NEWS    {x['id']} [{x.get('topic')}] {x.get('headline')}")
print(f"\n{changed} of {len(static)} suppliers have new release facts")
