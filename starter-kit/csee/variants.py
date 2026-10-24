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
