"""Bounded, deterministic economics for a draft strategy move.

This is feedback, not a negotiation policy: one-field changes hold all other terms fixed and say
nothing about whether a supplier will agree. Only case options and a case-derived coverage term
are inspected; prices, supplier floors and acceptance probabilities are never searched or invented.
"""

import json
from copy import deepcopy

from arena_kit.cost import RELATIONSHIP_GOALS, closing_terms, must_haves_ok, supplier_value
from ..agent import standard_terms
from arena_kit.play import live_threads, standing

from .. import levers
from .strategy_support import finite, normalise_sheet

MAX_VALUATIONS = 80
MAX_OPTIONS = 8
EPS = 0.02


def _key(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _number(value):
    return round(value, 2) if finite(value) else None


def _coverage(case, terms, std, breakdown):
    t, buyer = closing_terms(case, terms, std), case["buyer"]
    years = min(t["contract_months"] / 12 if t["contract_months"] else 1, buyer["horizon_years"])
    committed = t["volume_per_year"] * years
    covered = min(t["volume_per_year"], buyer["need_per_year"]) * years
    return {
        "need_units": round(buyer["need_per_year"] * buyer["horizon_years"], 4),
        "committed_units": round(committed, 4),
        "covered_units": round(covered, 4),
        "uncovered_units": round(buyer["need_per_year"] * buyer["horizon_years"] - covered, 4),
        "uncovered_need_and_risk_cost": round(
            breakdown.get("uncovered_need", 0) + breakdown.get("fallback_risk", 0), 2
        ),
        "contract_beyond_valued_horizon_months": max(0, t["contract_months"] - 12 * buyer["horizon_years"]),
    }


def _options(case, field, current, std):
    """Sample large explicit lists; never manufacture a business range for an unbounded field."""
    options = list(case.get("term_options", {}).get(field) or [])
    source = "case.term_options"
    if not options and field == "contract_months":
        months = case["buyer"]["horizon_years"] * 12
        if finite(months) and int(months) == months and 0 < months <= 36:
            options = [int(months)]
            source = "buyer_horizon_within_contract_schema"
    # Supplier-standard values are legal even if absent from the enumerated options.
    if field in std and std[field] not in options and std[field] != current:
        options.append(std[field])
        source += "_or_supplier_standard"
    unique = []
    for value in options:
        if value != current and value not in unique:
            unique.append(value)
    sampled = len(unique) > MAX_OPTIONS
    if sampled:
        indexes = {round(i * (len(unique) - 1) / (MAX_OPTIONS - 1)) for i in range(MAX_OPTIONS)}
        unique = [value for i, value in enumerate(unique) if i in indexes]
    # Inspect endpoints first when the whole turn runs out of valuation budget.
    if len(unique) > 2:
        unique = [unique[-1], unique[0], *unique[1:-1]]
    return unique, source, sampled


def _payment_trade(case, std, base, changed, estimate):
    """Exact buyer cash-neutral price for a one-field payment change, excluding relationship risk."""
    old, new = closing_terms(case, base["terms"], std), closing_terms(case, changed["terms"], std)
    buyer = case["buyer"]
    old_factor = 1 + buyer["interest_rate"] * (buyer["reference_payment_days"] - old["payment_days"]) / 360
    new_factor = 1 + buyer["interest_rate"] * (buyer["reference_payment_days"] - new["payment_days"]) / 360
    # Only purchases after the effective date change with the quoted unit price. The deterministic
    # breakdown gives their combined spend without introducing a second approximation of the dates.
    total_units = base["coverage"]["committed_units"]
    pre = 0.0
    if old.get("effective_date"):
        from arena_kit.cost import _units_before

        years = min(old["contract_months"] / 12 if old["contract_months"] else 1, buyer["horizon_years"])
        pre = _units_before(case, old, years)
    new_units = total_units - pre
    pre_spend = pre * (buyer.get("current_unit_price") or old["unit_price"])
    spend = base["breakdown"]["price"]
    # Index adjustments and index-risk charges scale with post-effective-date spend as well. Omitting
    # them would overstate the price a longer payment period can compensate, especially on raw material.
    index_cash = base["breakdown"].get("index_clause", 0) + base["breakdown"].get("index_risk", 0)
    index_per_price = index_cash / old["unit_price"]
    denominator = new_units * new_factor + index_per_price
    neutral = (
        (spend * old_factor + index_cash - pre_spend * new_factor) / denominator
        if new_units > 0 and denominator > 0
        else None
    )
    result = {
        "from_payment_days": old["payment_days"],
        "to_payment_days": new["payment_days"],
        "buyer_financing_cost_change": round(
            changed["breakdown"]["payment_terms"] - base["breakdown"]["payment_terms"], 2
        ),
        "buyer_cash_neutral_unit_price": round(neutral, 4) if neutral is not None else None,
        "buyer_cash_neutral_price_change": round(neutral - old["unit_price"], 4) if neutral is not None else None,
        "assumption": (
            "Buyer cash arithmetic before offer-price rounding; other terms fixed. Supplier acceptance is unknown."
        ),
    }
    if estimate:
        try:
            result["estimated_supplier_cash_value_change_per_unit"] = round(
                supplier_value(case, new, estimate) - supplier_value(case, old, estimate), 4
            )
            result["supplier_financing_rate_assumption"] = estimate["interest_rate"]
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
    return result


def build_review(agent, case, threads, sid, move, arguments):
    """Return decision-ready arithmetic without recommending or requiring a particular strategy.

    At most MAX_VALUATIONS cached ``agent.price`` calls are made. Standard terms are preserved
    before valuation, so an omitted negotiable field cannot silently become a buyer-preferred value.
    ``arguments`` is accepted for the draft/review interface; evidence relevance is reviewed separately.
    """
    raw = move.model_dump() if hasattr(move, "model_dump") else dict(move)
    std = standard_terms(threads[sid])
    _, current = standing(threads[sid])
    cache, errors, warnings = {}, [], []
    count = 0

    def price(supplier_id, values):
        nonlocal count
        events = threads[supplier_id]
        standard = standard_terms(events)
        _, existing = standing(events)
        closed = closing_terms(case, {**existing, **values}, standard)
        sheet = {field: closed[field] for field in case["negotiable"] if field in closed}
        sheet = normalise_sheet(case, sheet, existing, standard)
        if not must_haves_ok(case, sheet, standard):
            raise ValueError("package violates a buyer must-have")
        key = (supplier_id, _key(sheet))
        if key not in cache:
            if count >= MAX_VALUATIONS:
                return None
            count += 1
            result = deepcopy(agent.price(case, threads, supplier_id, sheet))
            if not finite(result.get("estimated_total_cost")) or not finite(result.get("cash_cost")):
                raise ValueError("valuation returned a non-finite cost")
            result["coverage"] = _coverage(case, result["terms"], standard, result["breakdown"])
            result["acceptance"] = "unknown"
            cache[key] = result
        return deepcopy(cache[key])

    def safe_price(supplier_id, values, label):
        try:
            return price(supplier_id, values)
        except (ValueError, KeyError, TypeError, OverflowError, ZeroDivisionError) as exc:
            errors.append({"package": label, "error": str(exc)})
            return None

    base = safe_price(sid, current, "standing") if standing(threads[sid])[0] else None
    alternative = levers.alternative_cost(case)
    proposed = []
    for index, terms in enumerate(raw.get("term_sheets") or [], 1):
        label = f"proposed:{index}"
        # Refuse unknown draft fields before closing_terms discards them.
        if set(terms) - set(case["negotiable"]):
            errors.append({"package": label, "error": "draft contains a non-negotiable field"})
            continue
        result = safe_price(sid, terms, label)
        if result:
            result["basis"] = label
            result["delta_vs_standing"] = (
                _number(result["estimated_total_cost"] - base["estimated_total_cost"]) if base else None
            )
            result["saving_vs_standing"] = _number(-result["delta_vs_standing"]) if base else None
            proposed.append(result)

    others = []
    for other_sid in live_threads(threads):
        if other_sid == sid:
            continue
        offer_id, terms = standing(threads[other_sid])
        result = safe_price(other_sid, terms, other_sid) if offer_id else None
        if result:
            others.append(
                {
                    "supplier_id": other_sid,
                    "offer_id": offer_id,
                    "terms": result["terms"],
                    "estimated_total_cost": result["estimated_total_cost"],
                    "cash_cost": result["cash_cost"],
                    "coverage": result["coverage"],
                }
            )

    bases = [("standing", base)] if base else []
    bases.extend((result["basis"], result) for result in proposed)
    fields = [field for field in case["negotiable"] if field != "unit_price"]
    tasks = []
    unbounded = set()
    for label, valuation in bases:
        full = closing_terms(case, valuation["terms"], std)
        per_field = []
        for field in fields:
            options, source, sampled = _options(case, field, full.get(field), std)
            if not options and not case.get("term_options", {}).get(field):
                unbounded.add(field)
            if sampled:
                warnings.append(f"{field}: sampled at most {MAX_OPTIONS} explicit options per package.")
            per_field.append([(label, valuation, field, option, source) for option in options])
        # Round robin across fields so a long options list cannot consume the whole review.
        for index in range(max((len(items) for items in per_field), default=0)):
            tasks.extend(items[index] for items in per_field if index < len(items))

    counterfactuals, payment_trades = [], []
    try:
        estimate = agent.supplier_estimate(case, sid, std)
    except (KeyError, AttributeError, TypeError, ValueError):
        estimate = None
    for label, valuation, field, option, source in tasks:
        if count >= MAX_VALUATIONS:
            break
        try:
            changed = price(sid, {**valuation["terms"], field: option})
        except (ValueError, KeyError, TypeError, OverflowError, ZeroDivisionError):
            continue  # Invalid case options / must-have breaks are not proposed as valid counterfactuals.
        if changed is None:
            break
        saving = round(valuation["estimated_total_cost"] - changed["estimated_total_cost"], 2)
        entry = {
            "id": f"lever:{len(counterfactuals) + 1}",
            "basis": label,
            "field": field,
            "from": valuation["terms"].get(field),
            "to": option,
            "source": source,
            "estimated_total_cost": changed["estimated_total_cost"],
            "mathematical_saving": saving,
            "cash_saving": round(valuation["cash_cost"] - changed["cash_cost"], 2),
            "changed_cost_components": {
                key: round(value - valuation["breakdown"].get(key, 0), 2)
                for key, value in changed["breakdown"].items()
                if abs(value - valuation["breakdown"].get(key, 0)) >= 0.005
            },
            "acceptance": "unknown",
        }
        if field in ("contract_months", "volume_per_year"):
            entry["coverage"] = changed["coverage"]
        counterfactuals.append(entry)
        if field == "payment_days":
            payment_trades.append(
                {
                    "counterfactual_id": entry["id"],
                    "basis": label,
                    **_payment_trade(case, std, valuation, changed, estimate),
                }
            )

    material = []
    for field in fields:
        candidates = [entry for entry in counterfactuals if entry["field"] == field]
        better = sorted(
            (entry for entry in candidates if entry["mathematical_saving"] > EPS),
            key=lambda entry: -entry["mathematical_saving"],
        )
        neutral = [entry for entry in candidates if abs(entry["mathematical_saving"]) <= EPS]
        if better or neutral:
            material.append(
                {
                    "field": field,
                    "best_lower_cost_option": better[0] if better else None,
                    "cost_neutral_options": neutral[:2],
                    "assumptions": [
                        "One field changed; unit price and all other terms held fixed.",
                        "Mathematical saving is not evidence that the supplier will accept.",
                    ],
                }
            )

    strategic = case["buyer"].get("category_goal") in RELATIONSHIP_GOALS
    warnings.append(
        "Relationship costs use uncertain supplier economics; central estimates and sensitivity cases "
        "are not exact scores."
        if strategic
        else "This category has no relationship penalty in the published formula; low cost still "
        "does not imply acceptance."
    )
    if any(v["coverage"]["contract_beyond_valued_horizon_months"] for _, v in bases):
        warnings.append("Contract commitments beyond the buyer horizon are not charged by this cost formula.")
    if unbounded:
        warnings.append(
            "No range invented for fields without explicit alternative options: " + ", ".join(sorted(unbounded))
        )
    truncated = count >= MAX_VALUATIONS
    if truncated:
        warnings.append(f"Review stopped at {MAX_VALUATIONS} package valuations; unreviewed changes remain possible.")
    return {
        "kind": "deterministic_economics_review",
        "action": raw.get("action"),
        "standing": base,
        "alternative_cost": _number(alternative),
        "proposed_packages": proposed,
        "other_live_standings": others,
        "one_field_counterfactuals": counterfactuals,
        "material_levers": material,
        "payment_trade_values": payment_trades,
        "errors": errors,
        "warnings": list(dict.fromkeys(warnings)),
        "assumptions": [
            "Only the first current standing supplier sheet can be accepted.",
            "Counterfactuals are legal arithmetic comparisons, not predictions or negotiation recommendations.",
            "Cash-neutral payment prices precede offer rounding and exclude relationship costs "
            "and acceptance conditions.",
        ],
        "valuation_count": count,
        "truncated": truncated,
    }


def compact_review(report):
    """Model-facing view; keep the full report in logs rather than truncating a JSON tool result.

    Every material field, proposed package valuation, uncertainty scenario and competing standing
    cost is preserved. Exhaustive one-field rows are represented by the best/neutral rows in
    material_levers; payment endpoints retain concrete cash-neutral exchange arithmetic.
    """
    compact = deepcopy(report)
    valuation_keys = {
        "terms",
        "cash_cost",
        "estimated_total_cost",
        "breakdown",
        "supplier_cost_source",
        "supplier_cost_confidence",
        "sensitivity_scenarios",
        "scenario_range",
        "coverage",
        "basis",
        "delta_vs_standing",
        "saving_vs_standing",
        "acceptance",
    }

    def valuation(value):
        return {key: item for key, item in value.items() if key in valuation_keys} if value else value

    compact["standing"] = valuation(compact.get("standing"))
    compact["proposed_packages"] = [valuation(value) for value in compact.get("proposed_packages", [])]
    compact["one_field_counterfactuals_omitted"] = len(compact.pop("one_field_counterfactuals", []))
    compact["counterfactual_detail"] = "Best lower-cost and neutral rows for every material field are below."
    entry_keys = {
        "id", "basis", "field", "from", "to", "estimated_total_cost", "mathematical_saving", "cash_saving", "coverage"
    }

    def entry(value):
        return {key: item for key, item in value.items() if key in entry_keys} if value else value

    for lever in compact.get("material_levers", []):
        lever["best_lower_cost_option"] = entry(lever.get("best_lower_cost_option"))
        lever["cost_neutral_options"] = [entry(value) for value in lever.get("cost_neutral_options", [])]
        # One shared statement replaces identical text for each field.
        lever.pop("assumptions", None)
    payments = {}
    for trade in compact.pop("payment_trade_values", []):
        payments.setdefault(trade["basis"], []).append(trade)
    compact["payment_trade_values"] = []
    for trades in payments.values():
        ordered = sorted(trades, key=lambda item: item["to_payment_days"])
        endpoints = [ordered[0]] + ([ordered[-1]] if len(ordered) > 1 else [])
        for trade in endpoints:
            trade.pop("assumption", None)
            compact["payment_trade_values"].append(trade)
    compact["assumptions"].append(
        "All displayed changes hold other terms fixed. Supplier acceptance is unknown; "
        "financial value is not a requirement to propose a change."
    )
    return compact
