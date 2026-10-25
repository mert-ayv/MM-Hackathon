"""Code-generated candidate packages. No supplier IDs, case IDs, or model arithmetic.

The shared value-based policy supplies a default. Alternative trades preserve or improve its buyer
cost; pace choices are explicitly costed. Estimates are exposed as estimates, not hard floors.
"""

import json
import math

from arena_kit.cost import RELATIONSHIP_GOALS, closing_terms, complete_offer, must_haves_ok, total_cost
from arena_kit.play import standing

from .. import levers
from ..agents.strategy_support import finite, normalise_sheet
from . import control


def key(terms):
    return json.dumps(terms, sort_keys=True)


def valid(case, terms, current, std):
    try:
        sheet = normalise_sheet(case, terms, current, std)
        if not must_haves_ok(case, sheet, std):
            return None
        if not finite(total_cost(case, sheet, std)):
            return None
        return sheet
    except (ValueError, TypeError, KeyError, OverflowError, ZeroDivisionError):
        return None


def at_value(case, terms, target, value_fn, std):
    """Invert the affine supplier-value function; fixed prices are never synthesized."""
    if "unit_price" not in case["negotiable"]:
        return dict(terms)
    full = closing_terms(case, terms, std)
    a, b = value_fn({**full, "unit_price": 1}), value_fn({**full, "unit_price": 2})
    if not finite(a) or not finite(b) or b <= a:
        return None
    price = round(1 + (target - a) / (b - a), 2)
    return {**terms, "unit_price": price} if finite(price) and price > 0 else None


def propose(agent, case, threads, sid, theirs, std, supplier, left):
    """A shared value-based concession policy, conditioned on goals and observed packages.

    Concessions are measured in estimated supplier value rather than comparing prices on different
    payment/index packages. Term search uses that same budget. No fitted supplier persona is needed.
    """
    st, p = agent.threads[sid], agent.p
    offered = closing_terms(case, theirs, std)
    if not finite(offered.get("unit_price")):
        return None
    value_fn = agent.value_fn(case, sid, std)
    their_value = value_fn(offered)
    previous = next(
        (
            m["term_sheets"][0]["terms"]
            for m in reversed(threads[sid])
            if m.get("from") == "buyer" and m.get("term_sheets")
        ),
        None,
    )
    relation = case["buyer"].get("category_goal") in RELATIONSHIP_GOALS
    if previous:
        previous_value = value_fn(closing_terms(case, previous, std))
        share = p.concede_late if agent.rounds_left(sid, left) <= 3 else p.concede_early
        state = control.observe(case, threads[sid], std)
        if state["hold_probe_eligible"] and agent.rounds_left(sid, left) > 3:
            share = 0.0  # one bounded test, only after a comparable substantial concession
        # Advance proportionally to the remaining value gap. The old follow-step cap can
        # collapse to penny-sized moves even when a meaningful reciprocal trade is available.
        target = previous_value + share * max(0, their_value - previous_value)
    else:
        discount = p.anchor_below_open if relation else control.opening_discount(agent, case, threads, sid)
        if "capacity" in agent.signals(sid, threads[sid]) and relation:
            discount = min(discount, 0.04)
        anchor = offered["unit_price"] * (1 - discount)
        current = case["buyer"].get("current_unit_price")
        if case.get("type") == "price_increase" and current:
            anchor = min(anchor, current)
        if relation and supplier:
            optimum = levers.cost_minimal_price(case, offered, std, supplier, hi=offered["unit_price"])
            anchor = max(anchor, optimum)
        target = value_fn({**offered, "unit_price": anchor})
    terms = complete_offer(case, offered)
    fixed_price = "unit_price" not in case["negotiable"]
    terms = at_value(case, terms, target, value_fn, std)
    if terms is None:
        return None
    # A shared index structure is retained unless a new supplier package changes it.
    keep_clause = previous and previous.get("index_clause") and offered.get("index_clause")
    for _ in range(2):
        changed = False
        for field in case["negotiable"]:
            if field == "unit_price":
                continue
            candidates = []
            for option in levers.options(case, field) or [terms.get(field)]:
                if field == "index_clause" and keep_clause and option is None:
                    continue
                candidate = at_value(case, {**terms, field: option}, target, value_fn, std)
                if candidate is None or not must_haves_ok(case, candidate, std):
                    continue
                c = total_cost(case, candidate, std, supplier)
                if finite(c):
                    candidates.append((c, candidate))
            if candidates:
                low = min(c for c, _ in candidates)
                # Preserve a cost-equivalent supplier package. Otherwise each new turn can
                # undo the lead-time/payment concession selected in the previous turn.
                near = [(c, t) for c, t in candidates if c <= low + 0.01]
                _, chosen = min(near, key=lambda row: (row[1].get(field) != terms.get(field), row[0]))
                changed |= chosen != terms
                terms = chosen
        if not changed:
            break
    if not fixed_price:
        # Relationship penalties can make a lower price worse; respect the cost optimum.
        if relation and supplier:
            optimum = levers.cost_minimal_price(case, terms, std, supplier, hi=offered["unit_price"])
            terms["unit_price"] = round(max(terms["unit_price"], optimum), 2)
        # Never retract our own price for this exact package, including a previous alternative.
        for message in threads[sid]:
            if message.get("from") != "buyer":
                continue
            for sheet in message.get("term_sheets") or []:
                old = sheet["terms"]
                if all(old.get(f) == terms.get(f) for f in case["negotiable"] if f != "unit_price"):
                    terms["unit_price"] = max(terms["unit_price"], old.get("unit_price", 0))
        cap = levers.price_cap(case)
        if cap is not None:
            terms["unit_price"] = min(terms["unit_price"], cap)
    if not must_haves_ok(case, terms, std):
        return None
    our_cost = total_cost(case, terms, std, supplier)
    if must_haves_ok(case, theirs, std) and total_cost(case, theirs, std, supplier) <= our_cost:
        st.why = "Standing offer costs no more than next reciprocal proposal"
        return None
    if our_cost >= levers.alternative_cost(case):
        st.why = "No cost-improving proposal within this concession budget"
        return None
    if not previous:
        st.anchor_c = (our_cost, total_cost(case, offered, std, supplier))
    return terms


def menu(agent, case, threads, sid, main, std, supplier, priorities=(), requests=()):
    """Baseline, bounded pace choices, and cost-neutral term exchanges (maximum 12)."""
    current = threads[sid][-1].get("term_sheets", [{}])[0].get("terms", {})
    main = valid(case, {k: v for k, v in main.items() if k in case["negotiable"]}, current, std)
    if main is None:
        return []
    baseline_cost = total_cost(case, main, std, supplier)
    alternative = levers.alternative_cost(case)
    out, seen = [], set()

    def add(terms, why, family):
        terms = valid(case, terms, current, std)
        if terms is None or key(terms) in seen:
            return
        c = total_cost(case, terms, std, supplier)
        if not finite(c) or c >= alternative:
            return
        seen.add(key(terms))
        out.append({"id": f"C{len(out)}", "terms": terms, "cost": round(c, 2), "kind": family, "reason": why})

    add(main, "Deterministic policy proposal", "baseline")
    if not out:
        return []
    previous = next(
        (
            m["term_sheets"][0]["terms"]
            for m in reversed(threads[sid])
            if m.get("from") == "buyer" and m.get("term_sheets")
        ),
        None,
    )
    # Price paths are comparable only on identical non-price packages.
    same = previous and all(previous.get(f) == main.get(f) for f in case["negotiable"] if f != "unit_price")
    if same and "unit_price" in case["negotiable"] and finite(previous.get("unit_price")):
        last, proposed = previous["unit_price"], main["unit_price"]
        if proposed > last:
            patient = round(last + (proposed - last) / 2, 2)
            if patient > last:
                add({**main, "unit_price": patient}, "Smaller reciprocal step while supplier still moves", "patient")
        # Supplier ticks observed on the SAME package; no fixed two-cent concession.
        offers = [
            m["term_sheets"][0]["terms"] for m in threads[sid] if m.get("from") != "buyer" and m.get("term_sheets")
        ]
        if len(offers) >= 2 and all(
            offers[-1].get(f) == offers[-2].get(f) for f in case["negotiable"] if f != "unit_price"
        ):
            p0, p1 = offers[-2].get("unit_price"), offers[-1].get("unit_price")
            if finite(p0) and finite(p1) and p0 > p1 > last:
                responsive = round(min(p1 - 0.01, last + max(proposed - last, p0 - p1)), 2)
                if responsive > proposed:
                    candidate = {**main, "unit_price": responsive}
                    # A bounded exploration cost, never a model-defined budget.
                    if total_cost(case, candidate, std, supplier) <= baseline_cost * 1.015:
                        add(candidate, "Reciprocate an observed supplier price step", "responsive")

    # Actual supplier alternatives are useful probes, not just textual requests. Price their
    # non-price structures at our budget; never treat a historical alternative as acceptable.
    quoted_requests = [
        {"terms": {f: sh["terms"][f] for f in case["negotiable"]
                   if f != "unit_price" and f in sh["terms"] and sh["terms"][f] != main.get(f)},
         "source": sh.get("term_sheet_id")}
        for sh in threads[sid][-1].get("term_sheets", [])
    ]
    requests = [*requests, *[r for r in quoted_requests if 1 <= len(r["terms"]) <= 3]]

    if "unit_price" not in case["negotiable"]:
        return add_requests(agent, case, threads, sid, out, requests, std, supplier)
    # Competition is a real priced option, not merely a line in the strategist's prompt.
    from ..agents.rfq_support import quoted_bids

    rivals = [
        b["estimated_total_cost"]
        for b in quoted_bids(agent, case, threads)
        if b["supplier_id"] != sid and b["can_accept"]
    ]
    if rivals:
        price = levers.price_for(case, main, min(baseline_cost, min(rivals) * 0.99), std, supplier)
        if price and (not same or price >= previous["unit_price"]):
            add({**main, "unit_price": price}, "Beat a live rival on complete estimated buyer cost", "competition")
    fields = sorted((f for f in case["negotiable"] if f != "unit_price"), key=lambda f: (f not in priorities, f))
    trades = []
    for field in fields:
        for value in levers.options(case, field):
            if value == main.get(field):
                continue
            # Once both parties offer an index clause, do not silently retract it.
            if field == "index_clause" and value is None and previous and previous.get(field) and current.get(field):
                continue
            terms = {**main, field: value}
            price = levers.price_for(case, terms, baseline_cost, std, supplier)
            if price is None or not math.isfinite(price) or price <= 0:
                continue
            terms["unit_price"] = price
            if total_cost(case, terms, std, supplier) > baseline_cost + 0.01:
                terms["unit_price"] = round(price - 0.01, 2)
            if total_cost(case, terms, std, supplier) > baseline_cost + 0.01:
                continue
            # Do not offer a lower price for the exact package already offered by us.
            prior = [m["term_sheets"] for m in threads[sid] if m.get("from") == "buyer" and m.get("term_sheets")]
            if any(
                all(sh["terms"].get(f) == terms.get(f) for f in case["negotiable"] if f != "unit_price")
                and sh["terms"].get("unit_price", 0) > terms["unit_price"]
                for sheets in prior
                for sh in sheets
            ):
                continue
            if valid(case, terms, current, std):
                value_fn = agent.value_fn(case, sid, std)
                gain = value_fn(closing_terms(case, terms, std)) - value_fn(closing_terms(case, main, std))
                trades.append((field in priorities, gain, field, terms))
    # Keep breadth across levers rather than filling the menu with payment variants.
    used_fields = set()
    for _, gain, field, terms in sorted(trades, key=lambda t: (t[0], t[1]), reverse=True):
        if field in used_fields or len(out) >= 12:
            continue
        add(terms, f"Trade {field} at no higher estimated buyer cost; supplier value change {gain:.3f}", field)
        used_fields.add(field)
    return add_requests(agent, case, threads, sid, out, requests, std, supplier)


def add_requests(agent, case, threads, sid, candidates, requests, std, supplier):
    """Price grounded multi-term requests, preserving existing candidate IDs for live advisers."""
    if not candidates:
        return candidates
    out = list(candidates)
    main = candidates[0]["terms"]
    target = total_cost(case, main, std, supplier)
    current = standing(threads[sid])[1]
    for request in requests:
        change = request.get("terms") or {}
        if not change or any(
            f == "unit_price" or f not in case["negotiable"] or v not in (levers.options(case, f) or [])
            for f, v in change.items()
        ):
            continue
        terms = {**main, **change}
        if "unit_price" in case["negotiable"]:
            price = levers.price_for(case, terms, target, std, supplier)
            if not price or not finite(price):
                continue
            terms["unit_price"] = price
            if total_cost(case, terms, std, supplier) > target + 0.01:
                terms["unit_price"] = round(price - 0.01, 2)
        terms = valid(case, terms, current, std)
        if not terms or any(terms == row["terms"] for row in out):
            continue
        c = total_cost(case, terms, std, supplier)
        if not finite(c) or c > target + 0.01 or c >= levers.alternative_cost(case):
            continue
        retracts = False
        for message in threads[sid]:
            if message.get("from") != "buyer":
                continue
            for sheet in message.get("term_sheets") or []:
                old = sheet["terms"]
                if all(old.get(f) == terms.get(f) for f in case["negotiable"] if f != "unit_price"):
                    retracts |= old.get("unit_price", 0) > terms.get("unit_price", 0)
                if current.get("index_clause") and old.get("index_clause") and terms.get("index_clause") is None:
                    retracts = True
        if retracts:
            continue
        out.append(
            {
                "id": f"C{len(out)}",
                "terms": terms,
                "cost": round(c, 2),
                "kind": "requested_trade",
                "reason": f"Grounded trade of {', '.join(change)}; code-priced at no higher buyer cost",
                "source": request.get("source"),
            }
        )
        if len(out) >= 18:
            break
    return out
