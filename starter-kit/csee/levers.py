"""The lever engine: which value of every negotiable term is best for us, what each lever is worth
in EUR, and which price a term sheet needs to hit a target cost. Pure arithmetic over the published
cost function (`arena_kit.cost`) - no model involved.
"""

import math

from arena_kit.cost import RELATIONSHIP_GOALS, closing_terms, complete_offer, must_haves_ok, total_cost

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


def best_terms(
    case, base, std=None, supplier=None, fixed=(), tolerance=1.0, exclude=None, value_of=None, cap_contract=False
):
    """Coordinate descent over the negotiable non-price fields at the price in `base`: the value with
    the lowest C for us; among values within `tolerance` EUR of it, the one the supplier likes most.
    Free volume and contract length fields: our need and the horizon (more costs, less leaves need uncovered)."""
    b = case["buyer"]
    t = complete_offer(case, base)
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
            here = value_of(t) if value_of and field in VALUE_NEUTRAL_FIELDS and t.get("unit_price") else None
            for v in options(case, field):
                if v in (exclude or {}).get(field, []):
                    continue
                if cap_contract and field == "contract_months" and v > round(12 * b["horizon_years"]):
                    continue  # longer than we need: the supplier then insists on an index clause (P08, P18)
                cand = {**t, field: v}
                if here is not None:
                    # the supplier prices what a term costs IT (a chargeback at its real defect rate, faster
                    # payment at its cost of money): compare options at the price that keeps its value equal
                    cand["unit_price"] = round(t["unit_price"] + (here - value_of(cand)), 4)
                c = total_cost(case, cand, std, supplier)
                if must_haves_ok(case, cand, std):
                    scored.append((c, v))
            if not scored:
                continue
            low = min(c for c, _ in scored)
            near = [v for c, v in scored if c <= low + tolerance]
            t[field] = max(near, key=lambda v: _supplier_rank(field, v, case))
    return t


def price_for(case, terms, target_c, std=None, supplier=None, lo=0.0, hi=None):
    """The unit price at which `terms` cost `target_c` (bisection; C rises with the price)."""
    hi = hi or max(terms.get("unit_price") or 1.0, 1.0) * 4
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
