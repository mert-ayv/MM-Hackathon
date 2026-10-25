"""Complete-bid comparisons for RFQs, shared by strategy context and tools.

Only live first sheets are awardable. Supplier alternatives are separate opportunities that need
confirmation. Match prices are buyer-cost arithmetic, never supplier reservation-price estimates.
"""

from arena_kit.cost import closing_terms, must_haves_ok, total_cost
from ..agent import standard_terms
from arena_kit.play import ENDED, latest, moves_left, standing

from .. import levers
from ..intel import Claim
from .strategy_support import finite, normalise_sheet


def quoted_bids(agent, case, threads):
    """Value each received sheet on its OWN defaults, without inheriting another sheet's terms."""
    bids = []
    for sid, events in threads.items():
        if not events:
            continue
        message, std = latest(events), standard_terms(events)
        status = message.get("status")
        for index, sheet in enumerate(message.get("term_sheets") or []):
            row = {
                "supplier_id": sid,
                "offer_id": sheet.get("term_sheet_id"),
                "status": status,
                "first_sheet": index == 0,
                "can_accept": False,
                "valid": False,
            }
            try:
                terms = closing_terms(case, sheet.get("terms") or {}, std)
                row["terms"] = terms
                if status in ENDED:
                    raise ValueError("supplier thread has ended")
                if not row["offer_id"]:
                    raise ValueError("no supplier offer ID")
                if not finite(terms.get("unit_price")) or terms["unit_price"] <= 0:
                    raise ValueError("no finite positive quoted price")
                if not must_haves_ok(case, terms, std):
                    raise ValueError("quoted package violates a buyer must-have")
                # Pass every negotiable value: an alternative's omissions use standard terms,
                # rather than price_package's normal inheritance from the first standing sheet.
                values = {field: terms[field] for field in case["negotiable"] if field in terms}
                valuation = agent.price(case, threads, sid, values)
                if not all(finite(valuation.get(key)) for key in ("cash_cost", "estimated_total_cost")):
                    raise ValueError("non-finite bid valuation")
                row.update(
                    valid=True,
                    can_accept=index == 0,
                    cash_cost=valuation["cash_cost"],
                    estimated_total_cost=valuation["estimated_total_cost"],
                    supplier_cost_confidence=valuation["supplier_cost_confidence"],
                    sensitivity_scenarios=valuation["sensitivity_scenarios"],
                    warnings=valuation["warnings"],
                    needs_confirmation=index != 0,
                )
            except (ValueError, KeyError, TypeError, OverflowError, ZeroDivisionError) as exc:
                row.pop("terms", None)  # Malformed numeric values must not leak NaN/Infinity into model JSON.
                row["reason"] = str(exc)
            bids.append(row)
    return bids


def compare_bids(agent, case, threads, sid, terms=None):
    """Rank awardable bids and price this bidder's package against its best live rival."""
    bids = quoted_bids(agent, case, threads)
    ranked = sorted(
        (bid for bid in bids if bid["can_accept"]),
        key=lambda bid: (bid["estimated_total_cost"], bid["supplier_id"]),
    )
    alternatives = sorted(
        (bid for bid in bids if bid["valid"] and not bid["first_sheet"]),
        key=lambda bid: (bid["estimated_total_cost"], bid["supplier_id"]),
    )
    rival = next((bid for bid in ranked if bid["supplier_id"] != sid), None)
    result = {
        "standing_bids_ranked": ranked,
        "unconfirmed_alternatives": alternatives,
        "invalid_bids": [bid for bid in bids if not bid["valid"]],
        "best_standing": ranked[0] if ranked else None,
        "best_rival": rival,
        "threads": [
            {
                "supplier_id": supplier,
                "status": latest(events).get("status"),
                "buyer_messages": sum(message.get("from") == "buyer" for message in events),
                "moves_left": moves_left(case, events),
                "ready": bool(getattr(agent.threads.get(supplier), "ready", False)),
            }
            for supplier, events in threads.items()
            if events
        ],
        "match_rival": None,
        "assumptions": [
            "Ranking uses complete packages and each supplier's own standard terms.",
            "Only a live first sheet is awardable; alternatives must be proposed back and confirmed.",
            "A match price holds this bidder's other terms fixed; acceptance remains unknown.",
            "Relationship costs and match prices depend on uncertain supplier-cost estimates.",
            "Stopping one thread does not award the RFQ; the coordinator compares current bids at closing.",
        ],
    }
    if rival and "unit_price" in case["negotiable"]:
        events, target = threads[sid], rival["estimated_total_cost"]
        std, current = standard_terms(events), standing(events)[1]
        try:
            package = normalise_sheet(case, terms or {}, current, std)
            if not must_haves_ok(case, package, std):
                raise ValueError("proposed package violates a buyer must-have")
            estimate = agent.supplier_estimate(case, sid, std)
            price = levers.price_for(case, package, target, std, estimate)
            # price_for rounds to cents; verify the actual package, including price must-haves.
            matched = {**package, "unit_price": price} if finite(price) and price > 0 else None
            if matched and total_cost(case, matched, std, estimate) > target:
                matched["unit_price"] = round(price - 0.01, 2)
            if (
                matched
                and matched["unit_price"] > 0
                and must_haves_ok(case, matched, std)
                and total_cost(case, matched, std, estimate) <= target
            ):
                result["match_rival"] = {
                    "rival_supplier_id": rival["supplier_id"],
                    "rival_offer_id": rival["offer_id"],
                    "target_total_cost": target,
                    "terms": matched,
                    "estimated_total_cost": total_cost(case, matched, std, estimate),
                    "acceptance": "unknown",
                }
        except (ValueError, KeyError, TypeError, OverflowError, ZeroDivisionError) as exc:
            result["match_error"] = str(exc)
    return result


def competitive_claims(agent, case, threads, sid):
    """Reveal only a valid live rival whose unit price AND complete cost improve on our bidder."""
    bids = quoted_bids(agent, case, threads)
    own = next((bid for bid in bids if bid["supplier_id"] == sid and bid["first_sheet"]), None)
    if not own or not finite(own.get("terms", {}).get("unit_price")):
        return []
    eligible = [
        bid
        for bid in bids
        if bid["supplier_id"] != sid
        and bid["can_accept"]
        and bid["terms"]["unit_price"] < own["terms"]["unit_price"]
        and (not own["valid"] or bid["estimated_total_cost"] < own["estimated_total_cost"])
    ]
    if not eligible:
        return []
    best = min(eligible, key=lambda bid: (bid["estimated_total_cost"], bid["supplier_id"]))
    price, offer_id = best["terms"]["unit_price"], best["offer_id"]
    return [
        Claim(f"We hold a competing offer at EUR {price:.2f} per unit ({offer_id}).", [offer_id], "rival", 2.5, price)
    ]
