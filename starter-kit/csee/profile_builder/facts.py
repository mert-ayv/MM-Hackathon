"""Deterministic hard fields of a supplier profile, straight from the SQLite tables.

Same input -> same output: no model, no clock. Rounding follows the curated profiles
(prices as stored, percentages to 1-2 decimals, day averages to 1 decimal).
"""

from datetime import date

from .common import sid

AS_OF = "2026-09-30"
FY = "FY2026"
HARD_KEYS = (
    "supplier_id",
    "name",
    "category",
    "country",
    "owner_type",
    "group_parent",
    "staff",
    "turnover_eur",
    "our_spend_fy2026_eur",
    "our_share_of_their_turnover_pct",
    "parts",
    "contract",
    "standard_terms_hint",
    "quality",
    "payment_behaviour",
    "financial_health",
    "negotiation_history",
)


def _one(pkg, sql, params=()):
    rows = pkg.query(sql, params, limit=10_000)
    return rows[0] if rows else None


def _all(pkg, sql, params=()):
    return pkg.query(sql, params, limit=100_000)


def _band_mid(band):
    """'2-5 M EUR' -> 3.5e6 (the turnover band's midpoint)."""
    try:
        lo, hi = band.split()[0].split("-")
        return (float(lo) + float(hi)) / 2 * 1e6
    except (AttributeError, ValueError, IndexError):
        return None


def _pct(x):
    """Share of turnover: 2 decimals below 1 %, else 1 decimal (as in the curated profiles)."""
    if x is None:
        return None
    return round(x, 2) if abs(x) < 1 else round(x, 1)


def parts(pkg, supplier):
    out = []
    rows = _all(
        pkg,
        "SELECT s.part_id, s.status, s.quota_pct, p.description, p.price_unit FROM sourcing s "
        "JOIN parts p ON p.id = s.part_id WHERE s.supplier_id = ? ORDER BY (s.status = 'active') DESC, s.part_id",
        (supplier,),
    )
    for r in rows:
        part = r["part_id"]
        price = _one(
            pkg,
            "SELECT price, price_unit FROM price_conditions WHERE part_id = ? AND supplier_id = ? "
            "ORDER BY valid_from DESC LIMIT 1",
            (part, supplier),
        )
        alts = [
            a["supplier_id"]
            for a in _all(
                pkg,
                "SELECT supplier_id FROM sourcing WHERE part_id = ? AND supplier_id != ? ORDER BY supplier_id",
                (part, supplier),
            )
        ]
        costs = _all(pkg, "SELECT id, supplier_id, unit_cost FROM should_cost WHERE part_id = ? ORDER BY id", (part,))
        own = [c for c in costs if c["supplier_id"] == supplier]
        cost = (own or costs or [None])[0]
        out.append(
            {
                "part_id": part,
                "name": r["description"],
                "current_price": price["price"] if price else None,
                "price_unit": (price or r)["price_unit"],
                "quota_pct": r["quota_pct"],
                "qualified_alternatives": alts,
                "should_cost_id": cost["id"] if cost else None,
                "should_cost_unit": cost["unit_cost"] if cost else None,
                "should_cost_is_own_plant": bool(own) if cost else None,
                "status": r["status"],
            }
        )
    return out


def contract(pkg, supplier):
    c = _one(pkg, "SELECT * FROM contracts WHERE supplier_id = ? ORDER BY valid_to DESC", (supplier,))
    if not c:
        return {}
    idx = _all(
        pkg,
        "SELECT id, series, material_share, deadband_pct FROM contract_clauses "
        "WHERE contract_id = ? AND type = 'index' ORDER BY id",
        (c["id"],),
    )
    return {
        "id": c["id"],
        "valid_to": c["valid_to"],
        "payment_days": c["payment_days"],
        "incoterm": c["incoterm"],
        "notice_days": c["notice_days"],
        "index_clauses": [
            {
                "id": i["id"],
                "series": i["series"],
                "material_share": i["material_share"],
                "deadband_pct": i["deadband_pct"],
            }
            for i in idx
        ],
    }


def standard_terms(pkg, s):
    skonto = f"{s['skonto_pct']}% within {s['skonto_days']} days" if s.get("skonto_pct") else None
    return {
        "payment_days": s["payment_days"],
        "incoterm": s["incoterm"],
        "lead_time_days": s["standard_lead_time_days"],
        "skonto": skonto,
    }


def quality(pkg, supplier):
    cards = _all(pkg, "SELECT * FROM scorecards WHERE supplier_id = ? ORDER BY quarter", (supplier,))
    if not cards:
        return {}
    last = cards[-1]
    year_ago = next((c for c in cards if c["quarter"] == f"{int(last['quarter'][:4]) - 1}{last['quarter'][4:]}"), None)
    colours = "/".join(c["colour"] for c in cards[-4:])
    trend = f"colours last 4Q: {colours}; score {cards[-4]['score'] if len(cards) >= 4 else '?'} -> {last['score']}"
    if year_ago:
        trend = (
            f"vs {year_ago['quarter']}: OTD {year_ago['otd_pct']}->{last['otd_pct']}%, "
            f"ppm {year_ago['ppm']}->{last['ppm']}; " + trend
        )
    return {
        "latest_scorecard_id": last["id"],
        "otd_pct": last["otd_pct"],
        "ppm": last["ppm"],
        "colour": last["colour"],
        "trend": trend,
        "open_8d_overdue": last["open_8d_overdue"],
        "qn_count_12m": last["qn_count"],
        "score": last["score"],
        "class": last["class"],
    }


def payment_behaviour(pkg, supplier, net_days):
    rows = _all(
        pkg,
        "SELECT due_date, paid_date, invoice_date, discount_taken, amount_eur FROM invoices WHERE supplier_id = ?",
        (supplier,),
    )
    paid = [r for r in rows if r["paid_date"]]
    if not paid:
        return {"avg_days_late_by_us": None, "note": "no paid invoices"}

    def days(a, b):
        return (date.fromisoformat(b) - date.fromisoformat(a)).days

    late = [days(r["due_date"], r["paid_date"]) for r in paid]
    avg_late = sum(late) / len(late)
    avg_term = sum(days(r["invoice_date"], r["paid_date"]) for r in paid) / len(paid)
    recent = [days(r["due_date"], r["paid_date"]) for r in paid if r["invoice_date"] > "2025-09-30"]
    disc = [r for r in paid if r["discount_taken"]]
    nodisc = [days(r["due_date"], r["paid_date"]) for r in paid if not r["discount_taken"]]
    after_due = sum(1 for x in late if x > 0)
    open_ = [r for r in rows if not r["paid_date"]]
    note = (
        f"{len(paid)} paid invoices, avg {avg_term:.1f} days from invoice on {net_days} net; "
        f"{after_due} paid after due date"
    )
    if recent:
        note += f"; {sum(recent) / len(recent):.1f} days late on average on invoices of the last 12m"
    if disc:
        note += f"; cash discount taken on {len(disc)} invoices, the {len(nodisc)} without average "
        note += f"{(sum(nodisc) / len(nodisc)) if nodisc else 0:.1f} days late"
    else:
        note += "; no cash discount ever taken"
    if open_:
        note += f"; {len(open_)} open invoices EUR {sum(r['amount_eur'] for r in open_):,.0f} at {AS_OF}"
    return {
        "avg_days_late_by_us": round(avg_late, 1),
        "avg_days_late_last_12m": round(sum(recent) / len(recent), 1) if recent else None,
        "note": note,
    }


def negotiation_history(pkg, supplier):
    rows = _all(
        pkg,
        "SELECT event_id, part_id, type, asked_pct, settled_pct, note FROM negotiation_history "
        "WHERE supplier_id = ? ORDER BY date",
        (supplier,),
    )
    ev = [r for r in rows if r["asked_pct"] is not None and r["settled_pct"] is not None]
    if not ev:
        return {
            "events": 0,
            "events_total": len(rows),
            "avg_asked_pct": None,
            "avg_settled_pct": None,
            "settle_to_ask_ratio": None,
            "notes": [],
        }
    pos = [r for r in ev if r["asked_pct"] > 0]
    ask_pos = sum(r["asked_pct"] for r in pos)
    ratio = round(sum(r["settled_pct"] for r in pos) / ask_pos, 2) if pos and ask_pos else None
    notes = []
    if pos:
        notes.append(
            f"settle_to_ask_ratio = settled/asked summed over the {len(pos)} events with a positive ask "
            f"(ask avg {ask_pos / len(pos):+.2f} %, settled avg {sum(r['settled_pct'] for r in pos) / len(pos):+.2f} %)"
        )
    for text in sorted({r["note"] for r in rows if r["note"]}):
        evs = [r["event_id"] for r in rows if r["note"] == text]
        notes.append(f"{text}: {', '.join(evs)}")
    types = sorted({r["type"] for r in ev})
    notes.append(f"event types: {', '.join(types)}")
    return {
        "events": len(ev),
        "events_total": len(rows),
        "avg_asked_pct": round(sum(r["asked_pct"] for r in ev) / len(ev), 2),
        "avg_settled_pct": round(sum(r["settled_pct"] for r in ev) / len(ev), 2),
        "settle_to_ask_ratio": ratio,
        "notes": notes,
    }


def financial_health(intel):
    if not intel:
        return {}
    eq, ci, ci0 = intel["equity_ratio_pct"], intel["credit_index"], intel["credit_index_12m_ago"]
    sig = []
    if ci is not None and ci0 is not None and ci != ci0:
        sig.append(f"credit index {'worsened' if ci > ci0 else 'improved'} {ci0}->{ci}")  # higher = worse
    else:
        sig.append(f"credit index {ci} unchanged")
    if eq is not None:
        sig.append(f"equity {eq}%" + (" (thin)" if eq < 26 else ""))
    if intel.get("vda63_grade"):
        sig.append(f"VDA 6.3 grade {intel['vda63_grade']}")
    return {
        "equity_ratio_pct": eq,
        "credit_index": ci,
        "credit_index_12m_ago": ci0,
        "signal": "; ".join(sig) + " (filed figures; see soft fields for current distress signals)",
    }


def build(pkg, supplier):
    """All hard fields for one supplier, in the schema's key order."""
    s_id = sid(supplier)
    s = _one(pkg, "SELECT * FROM suppliers WHERE id = ?", (s_id,))
    if not s:
        raise SystemExit(f"unknown supplier {s_id}")
    intel = _one(pkg, "SELECT * FROM supplier_intel WHERE supplier_id = ?", (s_id,)) or {}
    spend = _one(
        pkg, "SELECT SUM(spend_eur) AS v FROM spend_cube WHERE supplier_id = ? AND fiscal_year = ?", (s_id, FY)
    )
    spend = round(spend["v"]) if spend and spend["v"] is not None else None
    turnover = intel.get("turnover_eur")
    base = turnover or _band_mid(intel.get("turnover_band"))
    ctr = contract(pkg, s_id)
    return {
        "supplier_id": s_id,
        "name": s["name"],
        "category": s["category"],
        "country": s["country"],
        "owner_type": intel.get("owner_type"),
        "group_parent": intel.get("group_parent") or None,
        "staff": intel.get("staff"),
        "turnover_eur": turnover,
        "turnover_band": intel.get("turnover_band"),
        "our_spend_fy2026_eur": spend,
        "our_share_of_their_turnover_pct": _pct(spend / base * 100) if spend and base else None,
        "parts": parts(pkg, s_id),
        "contract": ctr,
        "standard_terms_hint": standard_terms(pkg, s),
        "quality": quality(pkg, s_id),
        "payment_behaviour": payment_behaviour(pkg, s_id, ctr.get("payment_days") or s["payment_days"]),
        "financial_health": financial_health(intel),
        "negotiation_history": negotiation_history(pkg, s_id),
    }
