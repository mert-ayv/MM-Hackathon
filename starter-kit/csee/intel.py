"""What we know before and during a case: the supplier's profile, an estimate of its cost floor,
and data arguments ("claims") the arena will check as verified.

Numbers come from the data package, never from a model. Each claim is one sentence with its figure
next to its IDs, the format the arena checks (`brief/api.md`, What counts).
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("csee")
PROFILES = Path(__file__).parent / "profiles"
# company.md: other countries' full cost relative to the German should-cost base
COUNTRY_COST = {"DE": 1.0, "AT": 1.05, "CH": 1.1, "CZ": 0.82, "PL": 0.82, "HU": 0.82, "TR": 0.75, "CN": 0.7}


@dataclass
class Claim:
    sentence: str  # one argument, figure and IDs in the same sentence
    ids: list
    kind: str  # index | should_cost | rival | scorecard | notice | forecast | news | history
    strength: float = 1.0  # how strongly it supports a lower price (for ordering)
    price: float | None = None  # the figure, for rival offers


@dataclass
class Intel:
    supplier_id: str
    profile: dict = field(default_factory=dict)
    full_cost: float | None = None  # per price unit, our estimate of the supplier's full cost
    full_cost_source: str = ""
    claims: list = field(default_factory=list)
    country: str = "DE"


def load_profile(supplier_id):
    path = PROFILES / f"{supplier_id.split(':')[-1]}.json"
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _fact(case, pkg, ref):
    return (case.get("facts") or {}).get(ref) or (pkg.lookup(ref) if pkg else None)


def _q(pkg, sql, params=()):
    try:
        return pkg.query(sql, params) if pkg else []
    except Exception as e:  # a query that fails must never cost a case
        log.debug("query failed: %s", e)
        return []


def series_name(pkg, series):
    rows = _q(pkg, "SELECT name FROM index_series WHERE id = ?", (series,))
    return rows[0]["name"] if rows else series


def index_change(pkg, case, series):
    """The 12-month change of a series ending at its latest month: (pct, id_from, id_to) or None."""
    ids = sorted(i for i in (pkg.ids(f"idx:{series}@") if pkg else []) if "@" in i)
    ids += sorted(k for k in (case.get("facts") or {}) if k.startswith(f"idx:{series}@"))
    ids = sorted(set(ids))
    if len(ids) < 2:
        return None
    last = ids[-1]
    y, m = map(int, last.split("@")[1].split("-"))
    first = f"idx:{series}@{y - 1}-{m:02d}"
    if first not in ids:
        return None
    a, b = _fact(case, pkg, first), _fact(case, pkg, last)
    if not a or not b or not a.get("value"):
        return None
    return (float(b["value"]) / float(a["value"]) - 1) * 100, first, last


def estimate_full_cost(case, pkg, supplier_id, country):
    """Full cost per unit (without margin) in the case's price unit: should-cost, else history."""
    for part in case.get("parts", []):
        rows = _q(pkg, "SELECT * FROM should_cost WHERE part_id = ?", (part,))
        for r in rows:
            unit = r.get("unit_cost")
            if not unit:
                continue
            own = r.get("supplier_id") == supplier_id
            factor = 1.0 if own else COUNTRY_COST.get(country, 1.0) / COUNTRY_COST.get(r.get("cost_base") or "DE", 1.0)
            return unit * factor, f"{r['id']} ({'its own plant' if own else 'DE base x' + format(factor, '.2f')})"
    return None, ""


def build(case, pkg, supplier_id, opening_price=None):
    """Everything we know about one supplier in this case, before the first counter-offer."""
    intel = Intel(supplier_id, load_profile(supplier_id))
    rows = _q(pkg, "SELECT country FROM suppliers WHERE id = ?", (supplier_id,))
    intel.country = (rows[0]["country"] if rows else None) or intel.profile.get("country") or "DE"
    intel.full_cost, intel.full_cost_source = estimate_full_cost(case, pkg, supplier_id, intel.country)
    intel.claims = claims_for(case, pkg, supplier_id, opening_price)
    return intel


def claims_for(case, pkg, supplier_id, asked_price=None):
    """Verified-able arguments for a lower price, strongest first. At most 3 go into one message."""
    out = []
    parts = case.get("parts", [])
    # 1. cost drivers that did not rise as much as the supplier claims (or fell)
    drivers = []
    for part in parts:
        drivers += _q(pkg, "SELECT series_id, weight FROM cost_drivers WHERE part_id = ?", (part,))
    seen = set()
    for d in sorted(drivers, key=lambda d: -(d.get("weight") or 0)):
        s = d["series_id"]
        if s in seen:
            continue
        seen.add(s)
        ch = index_change(pkg, case, s)
        if not ch:
            continue
        pct, a, b = ch
        weight = d.get("weight") or 0
        if pct < 3.0:  # only drivers that argue for us: flat or falling
            name = series_name(pkg, s)
            out.append(
                Claim(
                    f"{name} changed {pct:+.1f}% over the last twelve months ({a}, {b}).",
                    [a, b],
                    "index",
                    strength=weight * (3.0 - pct),
                )
            )
    # 2. our should-cost estimate, when the ask is clearly above it
    for part in parts:
        ref = f"cost:{part.split(':')[-1]}"
        fact = _fact(case, pkg, ref)
        if fact and fact.get("unit_cost") and (not asked_price or asked_price > fact["unit_cost"] * 1.08):
            out.append(
                Claim(
                    f"Our should-cost estimate for this part is EUR {fact['unit_cost']:.2f} per unit ({ref}).",
                    [ref],
                    "should_cost",
                    strength=2.0,
                )
            )
    # 3. a short notice period: the letter against the contract
    trig = case.get("trigger_doc")
    letter = _fact(case, pkg, trig) if trig else None
    if letter and letter.get("days") is not None:
        ctrs = [c for c in _q(pkg, "SELECT id, notice_days FROM contracts WHERE supplier_id = ?", (supplier_id,))]
        for c in ctrs:
            fact = _fact(case, pkg, c["id"])
            if fact and fact.get("days") and letter["days"] < fact["days"]:
                out.append(
                    Claim(
                        f"Your letter gives {letter['days']} days' notice ({trig}), while our agreement requires "
                        f"{fact['days']} days ({c['id']}).",
                        [trig, c["id"]],
                        "notice",
                        strength=3.0,
                    )
                )
    # 4. quality: a weak rolling scorecard
    rows = _q(
        pkg,
        "SELECT id, otd_pct, ppm, colour FROM scorecards WHERE supplier_id = ? ORDER BY quarter DESC LIMIT 1",
        (supplier_id,),
    )
    if rows and (rows[0]["colour"] in ("red", "amber") or (rows[0]["otd_pct"] or 100) < 90):
        r = rows[0]
        out.append(
            Claim(
                f"Your on-time delivery was {r['otd_pct']:.1f}% in the rolling twelve months ({r['id']}).",
                [r["id"]],
                "scorecard",
                strength=1.5 if r["colour"] == "red" else 0.8,
            )
        )
    # 5. news about this supplier looking for work
    for n in _q(pkg, "SELECT id, topic, headline FROM news WHERE supplier_id = ? ORDER BY date DESC", (supplier_id,)):
        if re.search(
            r"customer|order|capacity|utili|short.?time|kurzarbeit|work",
            (n["headline"] or "") + (n["topic"] or ""),
            re.I,
        ):
            out.append(Claim(f"We read that {n['headline'].rstrip('.')} ({n['id']}).", [n["id"]], "news", strength=0.6))
            break
    return sorted(out, key=lambda c: -c.strength)


def rival_claims(case, threads_standing, me):
    """In an RFQ: the best rival offer, citable to every other bidder (it reveals the figure)."""
    best = None
    for sid, (offer_id, terms) in threads_standing.items():
        if sid == me or not offer_id or terms.get("unit_price") is None:
            continue
        if best is None or terms["unit_price"] < best[1]:
            best = (offer_id, terms["unit_price"])
    if not best:
        return []
    return [
        Claim(f"We hold a competing offer at EUR {best[1]:.2f} per unit ({best[0]}).", [best[0]], "rival", 2.5, best[1])
    ]


def parse_cost_breakdown(text):
    """Material, conversion, overhead and margin per unit from a supplier's cost breakdown XLSX text."""
    out = {}
    for line in (text or "").splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 2:
            try:
                out[cells[0].lower()] = float(cells[1])
            except ValueError:
                continue
    if not out:
        return None
    full = sum(v for k, v in out.items() if k not in ("margin", "profit", "unit price"))
    return {"elements": out, "full_cost": full, "margin": out.get("margin") or out.get("profit")}
