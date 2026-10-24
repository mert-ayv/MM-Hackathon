"""What the data package says about a raw-material negotiation, for any supplier and part.

No supplier names, letters or practice-case numbers: every function reads tables every supplier has
(contracts, negotiation history, purchase orders) and returns None when the data is missing, so a
stranger in the Live Final simply plays like base.
"""

import statistics

from ..intel import _q

GIVE_CLIP = (0.0, 6.0)  # a supplier's usual settlement below its ask, in percentage points


def current_clause(pkg, sid):
    """The index clause of our current contract with this supplier: {series, material_share} or None."""
    rows = _q(
        pkg,
        "SELECT cc.series, cc.material_share FROM contract_clauses cc JOIN contracts c ON c.id = cc.contract_id "
        "WHERE c.supplier_id = ? AND cc.type = 'index' AND cc.series IS NOT NULL",
        (sid,),
    )
    for r in rows:
        if r.get("series"):
            return {"series": r["series"], "material_share": r.get("material_share")}
    return None


def _gives(rows):
    out = []
    for r in rows:
        asked, settled = r.get("asked_pct"), r.get("settled_pct")
        if asked is not None and settled is not None and asked != "" and settled != "":
            out.append(float(asked) - float(settled))
    return out


def typical_give(pkg, sid):
    """How many percentage points below its ask this supplier usually settles (median of past renewals),
    else the median of its category, else of all suppliers. Clipped to GIVE_CLIP; None without data."""
    sql = "SELECT asked_pct, settled_pct FROM negotiation_history WHERE type = 'annual renewal'"
    gives = _gives(_q(pkg, sql + " AND supplier_id = ?", (sid,)))
    if not gives:
        cat = _q(pkg, "SELECT category FROM suppliers WHERE id = ?", (sid,))
        if cat and cat[0].get("category"):
            gives = _gives(
                _q(
                    pkg,
                    sql + " AND supplier_id IN (SELECT id FROM suppliers WHERE category = ?)",
                    (cat[0]["category"],),
                )
            )
    if not gives:
        gives = _gives(_q(pkg, sql))
    if not gives:
        return None
    return min(max(statistics.median(gives), GIVE_CLIP[0]), GIVE_CLIP[1])


def benchmark(pkg, part, sid):
    """The lowest latest order price for the same part from another supplier, in the same price unit as
    this supplier's own orders: {price, supplier_id, ids: [2 PO IDs]} or None."""
    own = _q(
        pkg,
        "SELECT price_unit FROM po_lines WHERE part_id = ? AND supplier_id = ? ORDER BY order_date DESC LIMIT 1",
        (part, sid),
    )
    if not own:
        return None
    unit = own[0].get("price_unit")
    rows = _q(
        pkg,
        "SELECT id, supplier_id, price, order_date FROM po_lines WHERE part_id = ? AND supplier_id != ? "
        "AND price_unit = ? AND price IS NOT NULL ORDER BY order_date DESC",
        (part, sid, unit),
    )
    latest = {}
    for r in rows:  # newest first: the first two lines per supplier
        latest.setdefault(r["supplier_id"], [])
        if len(latest[r["supplier_id"]]) < 2:
            latest[r["supplier_id"]].append(r)
    best = None
    for other, lines in latest.items():
        if len(lines) < 2 or lines[0]["price"] != lines[1]["price"]:
            continue  # cite two orders at one price, so the figure is unambiguous
        if best is None or lines[0]["price"] < best["price"]:
            best = {"price": float(lines[0]["price"]), "supplier_id": other, "ids": [l["id"] for l in lines]}
    return best
