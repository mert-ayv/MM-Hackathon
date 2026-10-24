"""Named agent variants: parameter presets, versioned in git, so every experiment is reproducible.

Add a variant here (never by editing defaults locally), run it with `--variant NAME`, compare with
`python -m csee board`. Promote a winner by moving its values into `Params` defaults on main.
"""

from dataclasses import asdict, fields

from .agent import Params

VARIANTS = {
    "base": {},  # Params defaults: the current champion on main
    # D02 lessons: stop fighting held terms, cite only lower rivals, always offer cash, concede slower
    "v2": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "follow_share": 0.5,
        "hold_above_floor": 0.4,
        "anchor_below_open": 0.18,
    },
    # replay lessons: weigh every offered sheet, cheapest clause when insisted, should-cost x0.95
    # v1 behaviour before `fix` was promoted into base (kept to reproduce the baseline)
    "v1": {"all_sheets": False, "clause_when_insisted": False, "fullcost_discount": 1.0},
    "v3": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "follow_share": 0.5,
        "hold_above_floor": 0.4,
        "anchor_below_open": 0.18,
        "all_sheets": True,
        "clause_when_insisted": True,
        "fullcost_discount": 0.95,
    },
    "v4": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "floor_guard": True,
        "rfq_beat_leader": True,
    },
    "v5": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "follow_share": 0.5,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "hold_on_internal": True,
    },
    "v6": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "hold_on_internal": True,
    },
    "v7": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
    },
    "v8": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "generic_trades": True,
        "text_signals": True,
    },
    "v9": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "sticky_terms": True,
    },
    "v10": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "sticky_terms": True,
        "push_after_final": 1,
    },
}


# What each variant tests, in words - stored with every ledger row (keep it one or two sentences).
DESCRIPTIONS = {
    "base": "Champion on main (v1 + fix): lever engine, verified claims, parallel threads; anchors 12% below "
    "the opening, concedes 25%/50% of the gap; weighs every offered sheet, cheapest clause when insisted, "
    "should-cost x0.95.",
    "v1": "The first baseline: like base but takes only the supplier's first sheet, no clause rule, should-cost x1.",
    "v2": "base + D02 sandbox lessons: adopt terms the supplier held twice, cite a rival only if lower, "
    "always offer a faster-payment sheet, concede at most half the supplier's step, anchor 18% below.",
    "v3": "v2 + the replay fixes (now in base) = base + v2's concession tactics.",
    "v5": "Fable review bets: anchor 22% below outside relationship goals with no floor; RFQ first ask <= 92% "
    "of the cheapest rival; keep terms the supplier's own alternative sheets show are cheaper for us; hold "
    "price while it asks its boss; v2's held-terms, lower-rival, cash sheet; concede at most half its step.",
    "v6": "v5 with base's concession speed (follow_share 1.1): keep the RFQ gain without the D01 patience loss.",
    "v7": "v6 without holding the price while the supplier asks its boss.",
    "v8": "v7 + trade sheets over every term (lead time, ppm, chargeback, incoterm, clause...), one step toward "
    "the supplier, liked terms first, then cheapest for us; + pressures read from the supplier's own e-mails.",
    "v9": "v7 + sticky terms: after our first ask keep the non-price terms of the supplier's cheapest-for-us "
    "sheet and negotiate price (P11 flipped quality terms 3x and accepted the dearest set).",
    "v10": "v9 + push once more after the supplier's final offer (0 walk-aways in ~630 real supplier moves).",
    "v4": "base tactics (12% anchor, steady concessions keep the supplier conceding: D01) + v2's adopt-held-terms, "
    "lower-rival-only, cash sheet + floor guard (P05 anchored 0.5% below the opening) + RFQ: beat the leader.",
}


def params(name):
    if name not in VARIANTS:
        raise SystemExit(f"unknown variant {name!r}; known: {', '.join(VARIANTS)}")
    known = {f.name for f in fields(Params)}
    bad = set(VARIANTS[name]) - known
    if bad:
        raise SystemExit(f"variant {name!r} sets unknown params: {bad}")
    return Params(**VARIANTS[name])


def describe(name):
    return asdict(params(name))


def description(name):
    return DESCRIPTIONS.get(name, "")
