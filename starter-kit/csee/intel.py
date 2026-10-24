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
    tag: str = ""  # e.g. the index series, "ppm"/"otd" (for the profile's arguments_to_avoid)


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


def series_label(pkg, series):
    """The series name without any digits (a number next to our figure could be read as the figure)."""
    name = re.sub(r"\(.*?\)", "", series_name(pkg, series))
    words = [w for w in re.split(r"\s+", name.replace(",", " ").replace(":", " ")) if w and not re.search(r"\d", w)]
    label = " ".join(words).strip(" .-") or "This cost driver"
    return label[0].upper() + label[1:]


WINDOW_WORDS = {12: "twelve", 9: "nine", 6: "six", 4: "four", 3: "three"}


def _month_minus(month, k):
    y, m = map(int, month.split("-"))
    m -= k
    while m <= 0:
        m += 12
        y -= 1
    return f"{y}-{m:02d}"


def index_change(pkg, case, series, windows=(12,)):
    """The most favourable (lowest) change of a series over a window ending at its latest month:
    (pct, id_from, id_to, months) or None. Any window of <= 12 months ending within the last 12 months
    of the data is checkable (api.md); a 3-month fall can argue where the 12-month figure rose."""
    ids = set(i for i in (pkg.ids(f"idx:{series}@") if pkg else []) if "@" in i)
    ids |= {k for k in (case.get("facts") or {}) if k.startswith(f"idx:{series}@")}
    if len(ids) < 2:
        return None
    last = max(ids)
    b = _fact(case, pkg, last)
    best = None
    for k in windows:
        first = f"idx:{series}@{_month_minus(last.split('@')[1], k)}"
        a = _fact(case, pkg, first) if first in ids else None
        if not a or not b or not a.get("value"):
            continue
        pct = (float(b["value"]) / float(a["value"]) - 1) * 100
        if best is None or pct < best[0]:
            best = (pct, first, last, k)
    return best


def supplier_facts(case, pkg, supplier_id, prefix):
    """{id: fact} of one type for one supplier, from the package (incl. the Sunday release) and the case's
    own facts (hidden cases carry facts that exist only in the case)."""
    out = {}
    for ref, fact in list((pkg.facts if pkg else {}).items()) + list((case.get("facts") or {}).items()):
        if ref.startswith(prefix) and isinstance(fact, dict) and fact.get("supplier") == supplier_id:
            out[ref] = fact
    return out


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
        fact = _fact(case, pkg, f"cost:{part.split(':')[-1]}")  # a hidden case may carry its own estimate
        if fact and fact.get("unit_cost"):
            factor = COUNTRY_COST.get(country, 1.0)
            return fact["unit_cost"] * factor, f"cost:{part.split(':')[-1]} (case fact, DE base x{factor:.2f})"
    return None, ""


def build(case, pkg, supplier_id, opening_price=None, opening_text=""):
    """Everything we know about one supplier in this case, before the first counter-offer."""
    intel = Intel(supplier_id, load_profile(supplier_id))
    rows = _q(pkg, "SELECT country FROM suppliers WHERE id = ?", (supplier_id,))
    intel.country = (rows[0]["country"] if rows else None) or intel.profile.get("country") or "DE"
    intel.full_cost, intel.full_cost_source = estimate_full_cost(case, pkg, supplier_id, intel.country)
    intel.claims = claims_for(case, pkg, supplier_id, opening_price, opening_text)
    return intel


NEWS_HELPS_US = {"free_capacity", "short_time_work", "new_plant", "looking_for_customers", "short_time"}
NEWS_HELPS_THEM = {"full_order_book", "big_order", "allocation", "chip_shortage", "noise", "renamed"}
DRIVER_RE = re.compile(r"([A-Z][A-Z0-9-]{2,}) rose [\d.]+ ?% in twelve months")


def claims_for(case, pkg, supplier_id, asked_price=None, opening_text=""):
    """Verified-able arguments for a lower price, strongest first (at most 3 per message, each ID once)."""
    out = []
    parts = case.get("parts", [])
    ctype = case.get("type")
    # 1. cost drivers that fell, over the most favourable window (3-12 months); the series the supplier
    #    itself blames in its opening e-mail count too (unseen parts have no cost_drivers rows)
    drivers = []
    for part in parts:
        drivers += _q(pkg, "SELECT series_id, weight FROM cost_drivers WHERE part_id = ?", (part,))
    named = DRIVER_RE.findall(opening_text or "")
    drivers += [{"series_id": sname, "weight": 0.3} for sname in named]
    for ref in case.get("refs", []):
        if ref.startswith("idx:"):
            drivers.append({"series_id": ref[4:].split("@")[0], "weight": 0.2})
    seen = set()
    for d in sorted(drivers, key=lambda d: -(d.get("weight") or 0)):
        sname = d["series_id"]
        if sname in seen:
            continue
        seen.add(sname)
        ch = index_change(pkg, case, sname, windows=(12, 9, 6, 4, 3))
        if not ch or ch[0] >= -0.5:  # only a clear fall argues for us; a rise "confirms their case"
            continue
        pct, a, b, k = ch
        weight = d.get("weight") or 0
        bonus = 1.5 if sname in named else 1.0  # rebutting the driver it blamed lands best
        out.append(
            Claim(
                f"{series_label(pkg, sname)} changed {pct:+.1f}% over the last {WINDOW_WORDS[k]} months ({a}, {b}).",
                [a, b],
                "index",
                strength=bonus * (weight + 0.2) * (1.0 - pct),
                tag=sname,
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
    # 3. a short notice period: any letter of this supplier giving notice, against its contract
    letters = supplier_facts(case, pkg, supplier_id, "doc:")
    trig = case.get("trigger_doc")
    if trig and _fact(case, pkg, trig):
        letters[trig] = _fact(case, pkg, trig)
    contracts = {
        r: f for r, f in supplier_facts(case, pkg, supplier_id, "ctr:").items() if "#" not in r and f.get("days")
    }
    given = sorted(
        ((r, f) for r, f in letters.items() if f.get("days") is not None),
        key=lambda x: (x[0] != trig, x[1].get("date") or ""),
    )
    if given and contracts:
        ref, letter = given[0] if given[0][0] == trig else given[-1]
        cref, cfact = next(iter(contracts.items()))
        if letter["days"] < cfact["days"]:
            out.append(
                Claim(
                    f"Your letter gives {letter['days']} days' notice ({ref}), while our agreement requires "
                    f"{cfact['days']} days ({cref}).",
                    [ref, cref],
                    "notice",
                    strength=3.0,
                )
            )
    # 4. quality: lead with the defect rate in quality cases, delivery otherwise (distinct sc rows)
    cards = sorted(supplier_facts(case, pkg, supplier_id, "sc:").items(), key=lambda x: x[1].get("quarter") or "")
    if cards:
        last_ref, last = cards[-1]
        prev_ref, prev = cards[-2] if len(cards) > 1 else (None, None)
        red = last.get("colour") in ("red", "amber")
        if (ctype == "quality" or red) and (last.get("ppm") or 0) >= 500:
            out.append(
                Claim(
                    f"Your complaint rate was {last['ppm']:.0f} ppm in the rolling twelve months ({last_ref}).",
                    [last_ref],
                    "scorecard",
                    strength=3.5 if ctype == "quality" else 1.6,
                    tag="ppm",
                )
            )
            otd_ref, otd = (prev_ref, prev) if prev else (None, None)
        else:
            otd_ref, otd = last_ref, last
        if otd and (otd.get("colour") in ("red", "amber") or (otd.get("otd_pct") or 100) < 90):
            out.append(
                Claim(
                    f"Your on-time delivery was {otd['otd_pct']:.1f}% in the rolling twelve months ({otd_ref}).",
                    [otd_ref],
                    "scorecard",
                    strength=1.5 if otd.get("colour") == "red" else 0.8,
                    tag="otd",
                )
            )
    # 5. our demand grows: volume is what idle suppliers want (not in allocation/capacity squeezes)
    if ctype in ("renewal", "bundling", "rfq", "price_increase", "raw_material"):
        for part in parts:
            fcs = sorted(
                (
                    (r, f)
                    for r, f in list((pkg.facts if pkg else {}).items()) + list((case.get("facts") or {}).items())
                    if r.startswith(f"fc:{part.split(':')[-1]}@") and isinstance(f, dict)
                ),
                key=lambda x: x[0],
            )
            if fcs and (fcs[-1][1].get("change_pct") or 0) >= 3:
                ref, fc = fcs[-1]
                out.append(
                    Claim(
                        f"Our demand forecast for this part grows {fc['change_pct']:+.1f}% ({ref}).",
                        [ref],
                        "forecast",
                        strength=1.2,
                    )
                )
                break
    # 6. news that this supplier needs work (never news that helps it: full order books, allocation)
    news = supplier_facts(case, pkg, supplier_id, "news:")
    rows = {n["id"]: n for n in _q(pkg, "SELECT id, topic, headline FROM news WHERE supplier_id = ?", (supplier_id,))}
    for ref in sorted(news, reverse=True):
        n = {**news[ref], **rows.get(ref, {})}
        topic, head = (n.get("topic") or "").lower(), n.get("headline") or ""
        if topic in NEWS_HELPS_THEM:
            continue
        if topic in NEWS_HELPS_US or re.search(
            r"new customers|short-time|idle|spare capacity|second shift", head, re.I
        ):
            out.append(Claim(f"We read that {head.rstrip('.')} ({ref}).", [ref], "news", strength=0.6))
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
    skip = ("margin", "profit", "unit price", "price", "total", "sum", "full cost")
    full = sum(v for k, v in out.items() if not any(w in k for w in skip))
    return {"elements": out, "full_cost": full, "margin": out.get("margin") or out.get("profit")}
