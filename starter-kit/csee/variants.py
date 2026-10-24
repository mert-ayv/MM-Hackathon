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
