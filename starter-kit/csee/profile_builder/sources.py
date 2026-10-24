"""What the LLM reads about a supplier: its documents, news, quote remarks, history notes, and a
short list of citable facts (contract clauses, cost-driver index moves, should-cost, scorecards)."""

import json
import re

from .common import digits, sid


def _q(pkg, sql, params=()):
    return pkg.query(sql, params, limit=100_000)


def item_supplier(pkg, ref):
    """The supplier an ID belongs to: facts' `supplier`, the row's supplier_id, or the doc ID pattern."""
    fact = pkg.facts.get(ref) or {}
    row = pkg._ids.get(ref) or {}
    s = fact.get("supplier") or row.get("supplier_id") or row.get("supplier")
    if s:
        return sid(s)
    m = re.match(r"doc:\d{8}-(\d{5})-", ref)
    return f"sup:{m.group(1)}" if m else None


def item_text(pkg, ref):
    """Full text of a doc/news item (news: headline + body), '' if none."""
    row = pkg._ids.get(ref) or {}
    if ref.startswith("news:"):
        head = row.get("headline") or (pkg.facts.get(ref) or {}).get("headline") or ""
        return f"{head}\n{row.get('body') or ''}".strip()
    try:
        return pkg.document(ref)
    except (FileNotFoundError, OSError):
        return ""


def item_meta(pkg, ref):
    fact = pkg.facts.get(ref) or {}
    row = pkg._ids.get(ref) or {}
    keep = (
        "date",
        "kind",
        "type",
        "topic",
        "subject",
        "title",
        "author",
        "part_ids",
        "asked_pct",
        "asked_price",
        "effective_date",
        "notice_days",
        "days",
        "source",
    )
    meta = {k: (row.get(k) if row.get(k) not in (None, "") else fact.get(k)) for k in keep}
    return {k: v for k, v in meta.items() if v not in (None, "")}


def supplier_items(pkg, supplier, exclude=()):
    """[(ref, meta, text)] of every doc and news item about the supplier, oldest first."""
    s = sid(supplier)
    refs = [r for r in pkg.ids("doc:") + pkg.ids("news:") if r not in exclude and item_supplier(pkg, r) == s]
    out = [(r, item_meta(pkg, r), item_text(pkg, r)) for r in refs]
    return sorted(out, key=lambda x: (str(x[1].get("date") or ""), x[0]))


def citable(pkg, supplier, hard):
    """Compact facts with their IDs that arguments may cite."""
    s = sid(supplier)
    lines = []
    ctr = (hard.get("contract") or {}).get("id")
    if ctr:
        for c in _q(pkg, "SELECT id, text FROM contract_clauses WHERE contract_id = ? ORDER BY id", (ctr,)):
            lines.append(f"{c['id']}: {c['text']}")
    parts = [p["part_id"] for p in hard.get("parts", [])]
    for part in parts:
        for c in _q(
            pkg, "SELECT id, supplier_id, unit_cost, cost_base, price_unit FROM should_cost WHERE part_id = ?", (part,)
        ):
            lines.append(
                f"{c['id']}: should-cost {part} = EUR {c['unit_cost']} per {c['price_unit']} "
                f"({'this supplier' if c['supplier_id'] == s else (c['supplier_id'] or 'generic')} plant, base {c['cost_base']})"  # noqa: E501
            )
        drivers = _q(pkg, "SELECT series_id, weight FROM cost_drivers WHERE part_id = ? ORDER BY weight DESC", (part,))
        for d in drivers:
            ids = pkg.ids(f"idx:{d['series_id']}@")
            if len(ids) < 13:
                continue
            last, first = ids[-1], ids[-13]
            a, b = pkg.lookup(first) or {}, pkg.lookup(last) or {}
            if a.get("value") and b.get("value"):
                pct = (float(b["value"]) / float(a["value"]) - 1) * 100
                lines.append(
                    f"cost driver of {part}: {d['series_id']} weight {d['weight']}: {a['value']} ({first}) -> "
                    f"{b['value']} ({last}) = {pct:+.1f} % yoy"
                )
    for r in _q(
        pkg,
        "SELECT id, rfq_id, part_id, quote_date, unit_price, price_unit, lead_time_days, incoterm, payment_days, "
        "awarded, remarks, missing_fields FROM quotes WHERE supplier_id = ? ORDER BY quote_date",
        (s,),
    ):
        lines.append("quote " + json.dumps({k: v for k, v in r.items() if v not in (None, "")}, ensure_ascii=False))
    for r in _q(
        pkg,
        "SELECT id, quarter, otd_pct, ppm, colour, score FROM scorecards WHERE supplier_id = ? ORDER BY quarter",
        (s,),
    )[-5:]:
        lines.append(f"{r['id']}: OTD {r['otd_pct']} %, ppm {r['ppm']}, {r['colour']}, score {r['score']}")
    for r in _q(
        pkg,
        "SELECT event_id, part_id, type, asked_pct, settled_pct, note FROM negotiation_history WHERE supplier_id = ? ORDER BY date",  # noqa: E501
        (s,),
    ):
        lines.append("history " + json.dumps({k: v for k, v in r.items() if v not in (None, "")}, ensure_ascii=False))
    qn = _q(
        pkg,
        "SELECT COUNT(*) AS n, SUM(cost_recharged_eur) AS eur FROM quality_notifications WHERE supplier_id = ? AND qn_date > '2025-09-30'",  # noqa: E501
        (s,),
    )
    if qn and qn[0]["n"]:
        lines.append(f"quality notifications in the last 12 months: {qn[0]['n']} (EUR {qn[0]['eur'] or 0} recharged)")
    return lines


def render_items(items):
    out = []
    for ref, meta, text in items:
        out.append(f"<item id=\"{ref}\" meta='{json.dumps(meta, ensure_ascii=False)}'>\n{text.strip()}\n</item>")
    return "\n".join(out)


def rivals(pkg, hard):
    """Other suppliers on the same parts (names), so the LLM can reason about threats and alternatives."""
    out = {}
    for p in hard.get("parts", []):
        for a in p.get("qualified_alternatives", []):
            r = pkg.query("SELECT name FROM suppliers WHERE id = ?", (a,))
            out[a] = r[0]["name"] if r else a
    return out


def file_stub(supplier):
    return digits(supplier)
