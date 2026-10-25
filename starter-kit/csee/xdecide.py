"""Cross-check plan, stream B (decide): pure helpers behind Params.xc_push / xc_hold / xc_pace.

Evidence (vault "Case Audits/00 Cross-check", 84 practice runs, Sun 25 Oct):
  * push after a final offer: 12 logged, 10 agreed (0.5-1.85 % below its final), 2 walked. Size was not the
    discriminator: both walks followed a supplier that had stopped moving (P18: 5.50 held twice, then "final"
    5.50; P02: steps 0.82 -> 0.56 -> 0.30 EUR on 372, i.e. 0.08 % - noise, not a concession). Every agreed push
    followed a real step (>= 0.36 % of its price).
  * desk authority: 17 of the 46 final suppliers have a meeting note "price changes above 2 % need the approval
    of their pricing committee". Inside that band the desk decides alone: Blankstahl (70740) agreed 5.40 -> 5.30
    (1.85 %) five times; Leitner (70610) 5.52 -> 5.48. Without such a note we push at most 0.8 %.
  * repeats/holds: an identical sheet set was resent 8x (the bot's next step was 0 or <= 0.35 %, 4x it went
    final); a price BELOW our own earlier ask for the same structure (P04 4.63 -> 4.39 @ 90 d/36 m, P01 30-day
    sheet) drew "your price ... has decreased significantly" + hold + final. After a hold 71 % of the bot's next
    steps are 0 (n = 38).

Everything here is a function of the case, the thread and the data package: no supplier constants.
"""

import math
import re

from arena_kit.cost import total_cost

AUTHORITY = re.compile(
    r"price changes above\s*(\d+(?:[.,]\d+)?)\s*%\s*(?:need|require|are subject to)[^.]{0,60}?(?:approval|committee)",
    re.I,
)
DEFAULT_PUSH = 0.008  # no documented authority: at most 0.8 % below its final (agreed: P07 0.72 %, P08 0.54 %)
BAND_MARGIN = 0.001  # stay this much inside a documented band: its own rounding must not put us at the committee
MIN_STEP = 0.002  # its last step below 0.2 % of its price = it has stopped moving (P02 walked after 0.08 %)
WITHIN_BY_THIRD = 0.01  # a 2 %-authority desk: within 1 % of its standing price by our 3rd mail (price comes from rounds)

_authority_cache = {}


def tick_of(prices):
    """The coarsest grid every one of its prices sits on (0.5, 0.1, 0.05, else 0.01) - P11 moved in 0.50 steps."""
    prices = [p for p in prices if p]
    for t in (0.5, 0.1, 0.05):
        if len(prices) >= 2 and all(abs(p / t - round(p / t)) < 1e-6 for p in prices):
            return t
    return 0.01


def their_prices(events):
    """Every price the supplier has quoted in this thread, first sheets and alternatives."""
    out = []
    for m in events:
        if m.get("from") == "buyer":
            continue
        for sh in m.get("term_sheets") or []:
            p = (sh.get("terms") or sh).get("unit_price")
            if p:
                out.append(p)
    return out


def desk_authority(pkg, sid):
    """The share by which this supplier's desk may change the price on its own authority, read from its
    meeting/call notes ("price changes above 2 % need the approval of their pricing committee"), else None.
    Fails closed (no package, no documents, no sentence -> None)."""
    if pkg is None or not sid:
        return None
    key = (id(pkg), sid)
    if key in _authority_cache:
        return _authority_cache[key]
    band = None
    try:
        for ref, fact in list((getattr(pkg, "facts", None) or {}).items()):
            if not (ref.startswith("doc:") and isinstance(fact, dict) and fact.get("supplier") == sid):
                continue
            try:
                text = pkg.document(ref) or ""
            except Exception:
                continue
            m = AUTHORITY.search(text)
            if m:
                pct = float(m.group(1).replace(",", "."))
                if 0 < pct <= 10:
                    band = pct / 100 if band is None else min(band, pct / 100)
    except Exception:
        band = None
    _authority_cache[key] = band
    return band


def sheet_key(case, terms):
    return tuple((f, str(terms.get(f))) for f in case["negotiable"] if f != "unit_price")


def normalized(case, sheets):
    """Sheets as the arena sees them: negotiable fields only, prices rounded to the cent."""
    out = []
    for s in sheets:
        t = s.get("terms", s) if isinstance(s, dict) else {}
        n = {f: t.get(f) for f in case["negotiable"]}
        if n.get("unit_price") is not None:
            n["unit_price"] = round(n["unit_price"], 2)
        out.append(n)
    return out


def our_messages(events):
    """Our messages that carried term sheets, oldest first, each as its list of sheets."""
    return [
        [x.get("terms", x) for x in m["term_sheets"]]
        for m in events
        if m.get("from") == "buyer" and m.get("term_sheets")
    ]


def our_history(case, events):
    """{non-price structure: the highest price we ever asked for it} over everything we sent in this thread."""
    hist = {}
    for sheets in our_messages(events):
        for t in sheets:
            if t.get("unit_price") is not None:
                k = sheet_key(case, t)
                hist[k] = max(hist.get(k, 0.0), t["unit_price"])
    return hist


def supplier_replies(events):
    """Its messages with a priced first sheet, oldest first."""
    out = []
    for m in events:
        if m.get("from") == "buyer":
            continue
        sheets = [x.get("terms") or x for x in m.get("term_sheets") or []]
        if sheets and sheets[0].get("unit_price") is not None:
            out.append((m, sheets))
    return out


def supplier_step(case, events, std=None):
    """Its last price step in price units (> 0 = it came down), None before its second priced message.
    Same structure: the price difference. Changed structure: the drop in our C, as a unit-price equivalent."""
    replies = supplier_replies(events)
    if len(replies) < 2:
        return None
    _, prev = replies[-2]
    _, now = replies[-1]
    latest = now[0]
    same = [t for t in prev if sheet_key(case, t) == sheet_key(case, latest)]
    if same:
        return min(t["unit_price"] for t in same) - latest["unit_price"]
    try:
        c_prev = min(total_cost(case, t, std) for t in prev)
        c_now = total_cost(case, latest, std)
        per_euro = total_cost(case, {**latest, "unit_price": latest["unit_price"] + 1.0}, std) - c_now
        if not per_euro or not math.isfinite(c_prev) or not math.isfinite(c_now):
            return None
        return (c_prev - c_now) / per_euro
    except Exception:
        return None


def consecutive_holds(case, events):
    """How many of its latest replies in a row repeated its standing sheet (price and terms) although we had
    changed our ask in between. Our own repeat does not count as its hold."""
    holds = 0
    replies = []  # (index in events, standing sheet)
    for i, m in enumerate(events):
        if m.get("from") == "buyer":
            continue
        sheets = [x.get("terms") or x for x in m.get("term_sheets") or []]
        if sheets and sheets[0].get("unit_price") is not None:
            replies.append((i, sheets[0]))
    for j in range(len(replies) - 1, 0, -1):
        i_now, now = replies[j]
        i_prev, prev = replies[j - 1]
        same = sheet_key(case, now) == sheet_key(case, prev) and round(now["unit_price"], 2) == round(
            prev["unit_price"], 2
        )
        if not same:
            break
        between = [
            m for m in events[i_prev + 1 : i_now] if m.get("from") == "buyer" and m.get("term_sheets")
        ]
        before = [m for m in events[:i_prev] if m.get("from") == "buyer" and m.get("term_sheets")]
        if not between:
            break
        if before and normalized(case, between[-1]["term_sheets"]) == normalized(case, before[-1]["term_sheets"]):
            break  # we repeated ourselves: its hold answers ours
        holds += 1
    return holds


def push_ask(final_price, limit, tick):
    """The smallest price on its tick grid strictly inside the band `limit` below its final price, or None
    when that is not below the final (a push smaller than one tick says nothing to a coarse-tick desk)."""
    if not final_price or not limit or limit <= 0:
        return None
    tick = max(tick or 0.01, 0.01)
    edge = final_price * (1 - limit)
    ask = (math.floor(edge / tick + 1e-9) + 1) * tick
    ask = round(ask, 2)
    return ask if ask < round(final_price, 2) - 1e-9 else None


def ceil_tick(price, tick):
    tick = max(tick or 0.01, 0.01)
    return round(math.ceil(price / tick - 1e-9) * tick, 2)
