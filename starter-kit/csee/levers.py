"""The lever engine: which value of every negotiable term is best for us, what each lever is worth
in EUR, and which price a term sheet needs to hit a target cost. Pure arithmetic over the published
cost function (`arena_kit.cost`) - no model involved.
"""

import math

from arena_kit.cost import (
    OPS,
    RELATIONSHIP_GOALS,
    closing_terms,
    complete_offer,
    must_haves_ok,
    supplier_value,
    total_cost,
)

# Which way each term pleases the supplier (+1: higher is better for it). Used to break ties: among
# values that cost us the same, we give the supplier the one it likes.
SUPPLIER_LIKES = {
    "payment_days": -1,
    "lead_time_days": +1,
    "volume_per_year": +1,
    "contract_months": +1,
    "tooling_eur": +1,
    "ppm_commitment": +1,
    "chargeback_eur_per_complaint": -1,
}
INCOTERM_SUPPLIER_PREF = {"EXW": 2, "FCA": 1, "DAP": 0}  # it carries less freight on the left


def options(case, field):
    return list(case.get("term_options", {}).get(field) or [])


def cost(case, terms, std=None, supplier=None):
    return total_cost(case, complete_offer(case, terms), std, supplier)


def _supplier_rank(field, value, case):
    if field == "incoterm":
        return INCOTERM_SUPPLIER_PREF.get(value, 0)
    if field == "effective_date":  # an earlier new price is better for a supplier raising it
        return -int(str(value).replace("-", "")) if value else 0
    if field == "index_clause":
        return 1 if value else 0
    sign = SUPPLIER_LIKES.get(field, 0)
    return sign * value if isinstance(value, int | float) else 0


VALUE_NEUTRAL_FIELDS = ("chargeback_eur_per_complaint", "ppm_commitment")  # payment: own priced trade sheets


def price_cap(case):
    """The highest unit price our must-haves allow (None without a price must-have)."""
    caps = [m["value"] for m in case["buyer"].get("must_haves", []) if m["field"] == "unit_price" and m["op"] in ("<=", "<")]
    return min(caps) if caps else None


def nearest_ok(case, field, value):
    """The allowed value of `field` closest to `value` that keeps our must-haves on that field (P09: it holds
    49 days against our <= 42: offer 42, not our 28 again), else None."""
    rules = [m for m in case["buyer"].get("must_haves", []) if m["field"] == field]
    if not rules or not isinstance(value, int | float):
        return None
    opts = options(case, field) or [m["value"] for m in rules]
    ok = [o for o in opts if isinstance(o, int | float) and all(OPS[m["op"]](o, m["value"]) for m in rules)]
    return min(ok, key=lambda o: (abs(o - value), o)) if ok else None


def real_ppm_default(case, std=None, supplier=None):
    """The defect rate the supplier really has, when the caller knows nothing better: `supplier["ppm"]`,
    else its standard ppm commitment, else the case's highest ppm option (quality suppliers run well above
    the options they offer: P11 scorecard 2,376 ppm, P12 4,118)."""
    if supplier and supplier.get("ppm") is not None:
        return supplier["ppm"]
    if std and std.get("ppm_commitment"):
        return std["ppm_commitment"]
    return max(options(case, "ppm_commitment") or [0])


def supplier_value_fn(case, std=None, supplier=None, real_ppm=None):
    """`terms -> supplier_value` per unit, with chargebacks at the supplier's REAL defect rate (`real_ppm`).
    A chargeback costs it real_ppm x chargeback x units; a lower ppm *commitment* does not change its real
    ppm, so it costs it nothing here. Unknown standard terms come from the case (closing_terms)."""
    est = dict(supplier or {})
    est["standard"] = closing_terms(case, {}, {**(std or {}), **(est.get("standard") or {})})
    est.setdefault("interest_rate", 0.08)
    est["ppm"] = real_ppm if real_ppm is not None else real_ppm_default(case, std, supplier)

    def value(terms):
        try:
            return supplier_value(case, {**terms, "unit_price": terms.get("unit_price") or 1.0}, est)
        except (KeyError, TypeError, ZeroDivisionError):
            return 0.0

    return value


def best_terms(
    case,
    base,
    std=None,
    supplier=None,
    fixed=(),
    tolerance=1.0,
    exclude=None,
    value_of=None,
    cap_contract=False,
    supplier_ppm=None,
    supplier_cost_aware=True,
):
    """Coordinate descent over the negotiable non-price fields at the price in `base`: the value with
    the lowest C for us; among values within `tolerance` EUR of it, the one the supplier likes most.
    Free volume and contract length fields: our need and the horizon (more costs, less leaves need uncovered).

    Quality terms (ppm commitment, chargeback) are compared at the price that keeps the supplier's value
    equal: it prices a chargeback at its REAL defect rate (`supplier_ppm`; default `real_ppm_default`), so a
    chargeback above its standard is chosen only if it saves us more than it costs the supplier. Among
    options within `tolerance` the one cheapest for the supplier wins, then the lowest ppm commitment
    (P11: (1,500 ppm, EUR 500) and (300 ppm, EUR 500) both cost us EUR 0, but the supplier charged
    EUR 2.00-2.50/unit for the chargeback, worth EUR 0.11-0.45/unit to us). `value_of` overrides the
    supplier's value function; `supplier_cost_aware=False` restores the old pure-C comparison with the
    "supplier likes" tie-break (the local simulator's C_best yardstick)."""
    b = case["buyer"]
    if value_of is None and supplier_cost_aware:
        value_of = supplier_value_fn(case, std, supplier, supplier_ppm)
    t = complete_offer(case, base)
    cap = price_cap(case)
    if (
        "volume_per_year" in case["negotiable"]
        and not options(case, "volume_per_year")
        and "volume_per_year" not in fixed
    ):
        t["volume_per_year"] = b["need_per_year"]
    if (
        "contract_months" in case["negotiable"]
        and not options(case, "contract_months")
        and "contract_months" not in fixed
    ):
        t["contract_months"] = min(36, round(12 * b["horizon_years"]))
    for _ in range(2):
        for field in case["negotiable"]:
            if field == "unit_price" or field in fixed or not options(case, field):
                continue
            scored = []
            neutral = value_of is not None and field in VALUE_NEUTRAL_FIELDS
            here = value_of(t) if neutral else None
            for v in options(case, field):
                if v in (exclude or {}).get(field, []):
                    continue
                if cap_contract and field == "contract_months" and v > round(12 * b["horizon_years"]):
                    continue  # longer than we need: the supplier then insists on an index clause (P08, P18)
                cand = {**t, field: v}
                its_cost = 0.0  # EUR per unit the move costs the supplier (+) at its real defect rate
                if neutral:
                    its_cost = here - value_of(cand)
                    if t.get("unit_price"):
                        # the supplier prices what a term costs IT (a chargeback at its real defect rate):
                        # compare options at the price that keeps its value equal
                        cand["unit_price"] = round(t["unit_price"] + its_cost, 4)
                c = total_cost(case, cand, std, supplier)
                # a price above our price must-have is still being negotiated down: judge the other terms at the cap
                mh = {**cand, "unit_price": min(cand["unit_price"], cap)} if cap and cand.get("unit_price") else cand
                if must_haves_ok(case, mh, std):
                    scored.append((c, its_cost, v))
            if not scored:
                continue
            low = min(c for c, _, _ in scored)
            near = [(cost, v) for c, cost, v in scored if c <= low + tolerance]
            if neutral:
                # cheapest for the supplier; then the lowest ppm commitment (free to it: its real ppm is what it
                # is), or the chargeback closest to its standard
                std_cb = (std or {}).get("chargeback_eur_per_complaint") or 0

                def second(v, field=field, std_cb=std_cb):
                    return _num(v) if field == "ppm_commitment" else abs(_num(v) - std_cb)

                t[field] = min(near, key=lambda x: (round(x[0], 6), second(x[1])))[1]
            else:
                t[field] = max((v for _, v in near), key=lambda v: _supplier_rank(field, v, case))
    return t


def _num(v):
    return v if isinstance(v, int | float) else 0


def cost_minimal_price(case, terms, std=None, supplier=None, lo=0.0, hi=None, steps=120):
    """The unit price with the lowest C on [lo, hi]. Only the relationship term (stabilise and secure_supply,
    with a supplier estimate) makes C non-monotone in the price: below some price each EUR saved returns as
    relationship charge. Without it C rises with the price and this is `lo`. Scan, then golden-section."""
    hi = hi or max(terms.get("unit_price") or 1.0, 1.0) * 4
    if case["buyer"].get("category_goal") not in RELATIONSHIP_GOALS or not supplier:
        return lo

    def c_at(p):
        sheet = {**terms, "unit_price": p}
        try:
            if supplier_value(case, closing_terms(case, sheet, std), supplier) <= 0:
                return math.inf  # worth nothing to it: the margin formula breaks down, never a target
            return total_cost(case, sheet, std, supplier)
        except (KeyError, TypeError, ZeroDivisionError):
            return math.inf

    grid = [lo + (hi - lo) * i / steps for i in range(steps + 1)]
    i = min(range(len(grid)), key=lambda k: (c_at(grid[k]), grid[k]))
    a, z = grid[max(i - 1, 0)], grid[min(i + 1, steps)]
    g = (math.sqrt(5) - 1) / 2
    for _ in range(60):
        x1, x2 = z - g * (z - a), a + g * (z - a)
        if c_at(x1) <= c_at(x2):
            z = x2
        else:
            a = x1
    p = (a + z) / 2
    return p if c_at(p) <= c_at(grid[i]) else grid[i]


def price_for(case, terms, target_c, std=None, supplier=None, lo=0.0, hi=None):
    """The unit price at which `terms` cost `target_c`, or None if no price gets C that low.

    Bisection on the monotone branch only: in stabilise/secure_supply cases the relationship term makes C
    rise again below the C-minimal price, so we first find that price (`cost_minimal_price`) and search
    [p_min, hi]. Before, bisection from 0 could converge to ~0 and callers silently dropped the sheet."""
    hi = hi or max(terms.get("unit_price") or 1.0, 1.0) * 4
    lo = cost_minimal_price(case, terms, std, supplier, lo, hi)
    if total_cost(case, {**terms, "unit_price": lo}, std, supplier) > target_c:
        return None  # even the C-minimal price costs more than the target
    for _ in range(60):
        mid = (lo + hi) / 2
        if total_cost(case, {**terms, "unit_price": mid}, std, supplier) > target_c:
            hi = mid
        else:
            lo = mid
    return round(lo, 2)


def lever_values(case, terms, std=None, supplier=None):
    """For every negotiable field and option: what moving there saves us (EUR, + = cheaper) and the
    same as an equivalent unit-price change. Tells the agent what to ask for and what is cheap to give."""
    base = total_cost(case, terms, std, supplier)
    per_euro = total_cost(case, {**terms, "unit_price": terms["unit_price"] + 1}, std, supplier) - base
    out = {}
    for field in case["negotiable"]:
        if field == "unit_price":
            continue
        for v in options(case, field):
            c = total_cost(case, {**terms, field: v}, std, supplier)
            out.setdefault(field, {})[json_key(v)] = {
                "saves_eur": round(base - c, 2),
                "price_equiv": round((base - c) / per_euro, 4) if per_euro else None,
            }
    return out


def json_key(v):
    return v if isinstance(v, str | int | float) or v is None else str(v)


def relationship_optimal_price(case, terms, std, supplier, low, high, steps=200):
    """Strategic and bottleneck goals: below a point, a lower price costs us more in relationship
    charge than it saves. The price with the lowest C, searched between low and high."""
    if case["buyer"].get("category_goal") not in RELATIONSHIP_GOALS or not supplier:
        return None
    best = (math.inf, None)
    for i in range(steps + 1):
        p = low + (high - low) * i / steps
        c = total_cost(case, {**terms, "unit_price": p}, std, supplier)
        best = min(best, (c, p))
    return round(best[1], 2) if best[1] is not None else None


def alternative_cost(case):
    alt = case["buyer"].get("alternative") or {}
    if alt.get("kind") in (None, "none") or not (alt.get("terms") or {}).get("unit_price"):
        return math.inf
    return total_cost(case, alt["terms"])


def closing_cost(case, terms, std, supplier=None):
    """C of a standing sheet as it would close (gaps filled from the supplier's standard terms)."""
    return total_cost(case, closing_terms(case, terms, std), None, supplier)
