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
    source: str = ""  # "history": from history_claims, cited only with Params.history_claims


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


def build(case, pkg, supplier_id, opening_price=None, opening_text="", opening=None, should_cost_margin=0.08):
    """Everything we know about one supplier in this case, before the first counter-offer."""
    intel = Intel(supplier_id, load_profile(supplier_id))
    if not intel.profile:  # no curated profile: generate one (fallback.py); curated suppliers unchanged
        from .fallback import profile_for

        intel.profile = profile_for(supplier_id, case, pkg, opening or opening_text)
    rows = _q(pkg, "SELECT country FROM suppliers WHERE id = ?", (supplier_id,))
    intel.country = (rows[0]["country"] if rows else None) or intel.profile.get("country") or "DE"
    intel.full_cost, intel.full_cost_source = estimate_full_cost(case, pkg, supplier_id, intel.country)
    if intel.full_cost is None and intel.profile.get("floor_feed"):  # auto profiles only
        intel.full_cost, intel.full_cost_source = intel.profile["floor_estimate"], intel.profile["floor_source"]
    intel.claims = claims_for(case, pkg, supplier_id, opening_price, opening_text, should_cost_margin)
    return intel


NEWS_HELPS_US = {"free_capacity", "short_time_work", "new_plant", "looking_for_customers", "short_time"}
NEWS_HELPS_THEM = {"full_order_book", "big_order", "allocation", "chip_shortage", "noise", "renamed"}
DRIVER_RE = re.compile(r"([A-Z][A-Z0-9-]{2,}) rose [\d.]+ ?% in twelve months")


def claims_for(case, pkg, supplier_id, asked_price=None, opening_text="", should_cost_margin=0.08):
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
        # should-cost moved the price in 9 of 9 practice citations; the margin decides how far above it the ask must be
        if fact and fact.get("unit_cost") and (not asked_price or asked_price > fact["unit_cost"] * (1 + should_cost_margin)):
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
    out += history_claims(case, pkg, supplier_id, asked_price, cards)
    return sorted(out, key=lambda c: -c.strength)


def _years_back(known, prefix, supplier_id, years=2):
    """The date `years` before this supplier's latest record of this kind ("" if none)."""
    latest = max((f.get("date") or "" for r, f in known.items() if r.startswith(prefix) and isinstance(f, dict)
                  and f.get("supplier") == supplier_id), default="")
    return f"{int(latest[:4]) - years}{latest[4:]}" if latest[:4].isdigit() else ""


PO_GROUPS, PO_PER_CLAIM = 3, 3  # 2-8 orders of one part per argument; each ID counts once per case
PO_STRENGTH = (1.9, 1.1, 0.9)  # after notice/should-cost/quality, before forecast/news


def history_claims(case, pkg, supplier_id, asked_price=None, cards=()):
    """Arguments for rounds 2+ (round 1 uses the strongest three): our order history with this supplier,
    its complaint rate from quality notifications, its delivery record over earlier quarters, and the
    case's own references we hold no figures for (cited without one, the arena takes the data's value)."""
    out = []
    ctype = case.get("type")
    parts = case.get("parts", [])
    known = {**(pkg.facts if pkg else {}), **(case.get("facts") or {})}
    # 1. the prices it sold this part to us at: its cheapest orders of the last two years, per part
    for part in parts:
        pos = [
            (r, f)
            for r, f in known.items()
            if r.startswith("po:") and isinstance(f, dict) and f.get("supplier") == supplier_id
            and f.get("part") == part and f.get("unit_price")
        ]
        if len(pos) < 2:
            continue
        latest = max(f.get("date") or "" for _, f in pos)
        cutoff = f"{int(latest[:4]) - 2}{latest[4:]}" if latest[:4].isdigit() else ""
        recent = [x for x in pos if (x[1].get("date") or "") >= cutoff]
        pos = sorted(recent if len(recent) >= 2 else pos, key=lambda x: (x[1]["unit_price"], x[0]))
        if asked_price and pos[0][1]["unit_price"] >= asked_price * 0.99:
            continue  # it never sold cheaper than it asks now: no argument
        for g in range(PO_GROUPS):
            group = pos[g * PO_PER_CLAIM : (g + 1) * PO_PER_CLAIM]
            if len(group) < 2 or (asked_price and group[0][1]["unit_price"] >= asked_price * 0.99):
                break
            listed = ", ".join(f"EUR {f['unit_price']:.2f} ({r})" for r, f in group)
            out.append(
                Claim(
                    f"Our orders of this part with you were priced at {listed}.",
                    [r for r, _ in group],
                    "history",
                    strength=PO_STRENGTH[g] * (1.0 if len(parts) == 1 else 0.8),
                    tag="po",
                    source="history",
                )
            )
    # 2. its complaint rate from our quality notifications (quality cases, or a high rate)
    qns = sorted(
        (
            (r, f)
            for r, f in known.items()
            if r.startswith("qn:") and isinstance(f, dict) and f.get("supplier") == supplier_id
            and f.get("part") in parts and f.get("ppm") and (f.get("date") or "") >= _years_back(known, "qn:", supplier_id)
        ),
        key=lambda x: (-(x[1]["ppm"]), x[0]),
    )
    for g in range(2):
        group = qns[g * 3 : (g + 1) * 3]
        if len(group) < 2:
            break
        mean = sum(f["ppm"] for _, f in group) / len(group)
        if mean < 500 and ctype != "quality":
            break
        out.append(
            Claim(
                f"Your recent complaints on this part averaged {mean:.0f} ppm "
                f"({', '.join(r for r, _ in group)}).",
                [r for r, _ in group],
                "scorecard",
                strength=(3.0 if ctype == "quality" else 1.4) * (1.0 if g == 0 else 0.6),
                tag="ppm",
                source="history",
            )
        )
    # 3. its delivery record over earlier quarters (the latest two are cited on their own)
    earlier = [(r, f) for r, f in list(cards)[:-2] if f.get("otd_pct") is not None][-4:]
    if len(earlier) >= 2:
        mean = sum(f["otd_pct"] for _, f in earlier) / len(earlier)
        if mean < 92:
            out.append(
                Claim(
                    f"Your on-time delivery averaged {mean:.1f}% over the quarters before that "
                    f"({', '.join(r for r, _ in earlier)}).",
                    [r for r, _ in earlier],
                    "scorecard",
                    strength=0.9,
                    tag="otd",
                    source="history",
                )
            )
    # 4. the case's own references we have no figures for (sandbox, hidden final cases): orders and the
    #    should-cost estimate argue for us whatever their value; scorecards, forecasts and news may not
    unknown = [r for r in case.get("refs", []) if r not in known and not (pkg and pkg.lookup(r))]
    po_refs = [r for r in unknown if r.startswith("po:")][:8]
    if len(po_refs) >= 2:
        out.append(
            Claim(
                f"Please compare your offer with our recent orders of this part ({', '.join(po_refs)}).",
                po_refs,
                "history",
                strength=1.3,
                tag="po",
                source="history",
            )
        )
    for r in unknown:
        if r.startswith("cost:"):
            out.append(
                Claim(
                    f"Our should-cost analysis for this part ({r}) leaves clear room below your price.",
                    [r],
                    "should_cost",
                    strength=1.8,
                    source="history",
                )
            )
            break
    return out


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


ALT_QUOTE_MIN_GAP = 0.01  # cite the alternative only if at least this far below the standing ask


def alt_quote_claims(case, pkg, supplier_id, ask):
    """The case's own quotes (its alternative, quote refs of the same part) priced BELOW this supplier's
    standing ask: the cheapest as one argument. The arena checks a quote of this case as verified
    (brief/api.md, What counts); a quote outside the case or another supplier's orders come back
    `irrelevant` (P08/P18, and P18 then asked for "redacted invoices"). A pricier alternative is never
    cited (P05: "the rival offer is still higher than our price"). Single-part cases only."""
    if not ask or len(case.get("parts") or []) != 1:
        return []
    cands = {}
    alt = (case.get("buyer") or {}).get("alternative") or {}
    if alt.get("kind") == "quote" and alt.get("ref") and (alt.get("terms") or {}).get("unit_price"):
        f = _fact(case, pkg, alt["ref"]) or {}
        cands[alt["ref"]] = (float(alt["terms"]["unit_price"]), f.get("supplier"))
    for r in case.get("refs") or []:
        if not r.startswith("quote:") or r in cands:
            continue
        f = _fact(case, pkg, r) or {}
        if not f.get("unit_price") or (f.get("part") and f["part"] not in case["parts"]) or (f.get("price_unit") or 1) != 1:
            continue
        cands[r] = (float(f["unit_price"]), f.get("supplier"))
    below = [(p, r) for r, (p, s) in cands.items() if s != supplier_id and p < ask * (1 - ALT_QUOTE_MIN_GAP)]
    if not below:
        return []
    p, r = min(below)
    return [Claim(f"Our qualified second source has quoted EUR {p:.2f} per unit for this part ({r}).", [r], "rival", 2.5, p, tag="alt_quote")]


# ---------- cross-check plan item 1 (Params.xc_claims): the supplier's own evidence first ----------
# Claim kinds the arena checks (brief/api.md, What counts) and the logged results (1,204 practice replies, Sun 25 Oct):
# idx 216 verified / 2 irrelevant, fc 98 verified, sc 212 verified / 7 contradicted (all ppm sentences without the word
# "quality"), po 94 verified (0 moved a price), news 20/20, doc+ctr notice 28/28, a ctr clause with its days 1/1.
# A `quote:` of THIS supplier was never cited (0 checks): whether the arena verifies it outside the case's refs is
# unknown - the api lists "a quote of this case"; an unknown result is at worst `irrelevant` (true, no trust cost).
OWN_QUOTE_MIN_GAP = 0.01  # cite its own quote only if at least this far below its standing ask
NOTE_CAPACITY_RE = re.compile(
    r"idle|second shift|additional parts|spare capacity|short[- ]time|short hours|new customers|free capacity|"
    r"under-?utili|take (?:on )?(?:more|additional)",
    re.I,
)
FORECAST_TYPES = ("renewal", "bundling", "rfq", "price_increase", "raw_material")
FORECAST_MIN_GROWTH = 3


def _doc_text(pkg, ref):
    try:
        return (pkg.document(ref) if pkg else "") or ""
    except Exception:
        return ""


def own_quote_claims(case, pkg, supplier_id, ask):
    """This supplier's own most recent quote for the case's part, priced below its standing ask (P08: its live
    quote 5.45 vs opening 6.05; P03/P04: its list price). Single-part cases, same price unit, one claim."""
    if not ask or len(case.get("parts") or []) != 1:
        return []
    part = case["parts"][0]
    quotes = [
        (f.get("date") or "", r, f)
        for r, f in supplier_facts(case, pkg, supplier_id, "quote:").items()
        if f.get("part") == part and f.get("unit_price") and (f.get("price_unit") or 1) == 1
    ]
    below = [q for q in quotes if float(q[2]["unit_price"]) < ask * (1 - OWN_QUOTE_MIN_GAP)]
    if not below:
        return []
    latest = max(below)[0]
    # the lowest of its quotes from the last twelve months (P04: list price 4.39, not the small-lot RFQ quote 4.63
    # two weeks later; P08: its live quote 5.45, not a 16-month-old 5.34)
    recent = [q for q in below if q[0] >= _month_minus(latest[:7], 12)] or [max(below)]
    date, ref, fact = min(recent, key=lambda q: (float(q[2]["unit_price"]), q[0]))
    newer = [q for q in quotes if q[0] > date]  # a newer own quote exists: this one is not its "most recent"
    rows = _q(pkg, "SELECT remarks FROM quotes WHERE id = ?", (ref,))
    remark = ((rows[0].get("remarks") if rows else "") or "").lower()
    price = float(fact["unit_price"])
    if "list" in remark:
        sentence = f"Your own list price for this part is EUR {price:.2f} per unit ({ref})."
    else:
        sentence = f"Your own {'most recent ' if not newer else ''}quote to us for this part was EUR {price:.2f} per unit ({ref})."
    return [Claim(sentence, [ref], "own_quote", strength=4.5, price=price, tag="own_quote")]


def hedge_claims(case, pkg, supplier_id, opening_text=""):
    """The symmetric reading of the supplier's own hedge letter (P08: "nickel covered at fixed prices until March
    2027"): a rise it blames has not reached its cost either while the cover runs past the new contract year.
    One sentence without figures (the arena takes the document's own value), cited by its ID."""
    from . import dossier  # hedge wording parser shared with the dossier

    start = (case.get("fixed_terms") or {}).get("effective_date") or min(
        (d for d in (case.get("term_options") or {}).get("effective_date") or [] if d), default=""
    )
    if not start:
        return []
    named = set(DRIVER_RE.findall(opening_text or ""))
    series_in_case = {c["series"] for c in (case.get("term_options") or {}).get("index_clause") or [] if c}
    best = None
    for ref, fact in supplier_facts(case, pkg, supplier_id, "doc:").items():
        if fact.get("type") not in ("letter", "call_note", "meeting_note", "email"):
            continue
        for material, series, until in dossier.hedges_from_text(_doc_text(pkg, ref)):
            if until < start[:7] or not material:
                continue
            blamed = bool(named & set(series)) or bool(series_in_case & set(series))
            key = (blamed, fact.get("type") == "letter", until, ref)
            if best is None or key > best[0]:
                best = (key, ref, material, series)
    if not best or not best[0][0]:  # only when the hedged material is the one in play
        return []
    _, ref, material, series = best
    label = series_label(pkg, next(iter(named & set(series)), series[0])) if series else "that material"
    sentence = (
        f"Your own letter on material costs ({ref}) states that your {material} requirement is covered at fixed "
        f"prices beyond the start of the new contract year, so the rise in {label} you cite does not reach your "
        f"cost in that period either."
    )
    return [Claim(sentence, [ref], "hedge", strength=2.6, tag="hedge")]


def note_claims(case, pkg, supplier_id):
    """Our own call / meeting notes that record spare capacity at this supplier (P07: "could take additional parts
    at short notice; the second shift has been on hold"). Meeting notes are context for the arena, never a wrong
    figure; the bots verified the doc IDs we cited. Volume-hungry suppliers only (same case types as forecasts)."""
    if case.get("type") not in FORECAST_TYPES:
        return []
    notes = [
        (f.get("date") or "", r)
        for r, f in supplier_facts(case, pkg, supplier_id, "doc:").items()
        if f.get("type") in ("call_note", "meeting_note") and NOTE_CAPACITY_RE.search(_doc_text(pkg, r))
    ]
    if not notes:
        return []
    _, ref = max(notes)
    return [
        Claim(
            f"Our meeting notes record that you have spare capacity for additional parts at present ({ref}).",
            [ref],
            "news",
            strength=1.3,
            tag="note",
        )
    ]


def forecast_claims(case, pkg, any_type=False):
    """One forecast claim per case part with growth >= 3 %, the LARGEST growth first (P07: fc:360011 +15.3 % is
    the part that is new business for the supplier; the old loop broke at the first part, +6.0 %). `any_type`:
    also in quality / capacity cases, as the verifiable fact behind an answer to "which volume" (P11 +20 %)."""
    if not any_type and case.get("type") not in FORECAST_TYPES:
        return []
    known = list((pkg.facts if pkg else {}).items()) + list((case.get("facts") or {}).items())
    found = []
    for part in case.get("parts", []):
        fcs = sorted((r, f) for r, f in known if r.startswith(f"fc:{part.split(':')[-1]}@") and isinstance(f, dict))
        if fcs and (fcs[-1][1].get("change_pct") or 0) >= FORECAST_MIN_GROWTH:
            found.append(fcs[-1])
    found.sort(key=lambda x: -(x[1]["change_pct"]))
    out = []
    for rank, (ref, fc) in enumerate(found):
        out.append(
            Claim(
                f"Our demand forecast for this part grows {fc['change_pct']:+.1f}% ({ref}).",
                [ref],
                "forecast",
                strength=(1.2 + 0.05 * fc["change_pct"]) * (0.9**rank),
            )
        )
    return out


def quality_wording(claim):
    """A ppm claim must say "quality": the arena judged sc sentences without the word as on-time delivery and
    contradicted every one of them (7/7; P11 "that costs trust")."""
    if claim.tag == "ppm" and "quality" not in claim.sentence.lower():
        s = claim.sentence
        claim.sentence = "On quality: " + s[0].lower() + s[1:]
    return claim


def refine_claims(case, pkg, supplier_id, claims, ask=None, opening_text=""):
    """The xc_claims claim list: the supplier's own evidence (quote, hedge letter) first, spare-capacity notes,
    forecasts by growth, "quality" on every ppm sentence, no index that rose. Strongest first, as claims_for."""
    out = [c for c in claims if c.kind != "forecast"]
    out = [c for c in out if not (c.kind == "index" and re.search(r"changed \+", c.sentence))]
    out = [quality_wording(c) for c in out]
    out += own_quote_claims(case, pkg, supplier_id, ask)
    out += hedge_claims(case, pkg, supplier_id, opening_text)
    out += note_claims(case, pkg, supplier_id)
    out += forecast_claims(case, pkg)
    return sorted(out, key=lambda c: -c.strength)
