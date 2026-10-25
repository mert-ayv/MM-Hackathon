"""Replayable commercial state and bounded policy controls; no fitted supplier identities."""

from arena_kit.cost import closing_terms, must_haves_ok, total_cost


def package(case, terms, std):
    return closing_terms(case, terms, std)


def same_package(a, b):
    return {k: v for k, v in a.items() if k != "unit_price"} == {k: v for k, v in b.items() if k != "unit_price"}


def observe(case, events, std):
    """Rebuild from the transcript, including on resume. Unadopted does not mean rejected."""
    offers, ours, unadopted, gaps = [], [], {}, []
    buyer_packages, supplier_packages = [], []
    last_ask = None
    for event in events:
        sheets = event.get("term_sheets") or []
        if not sheets:
            continue
        terms = package(case, sheets[0]["terms"], std)
        if event.get("from") == "buyer":
            ours.append(terms)
            last_ask = [package(case, s["terms"], std) for s in sheets]
            buyer_packages.extend(last_ask)
            if offers and same_package(offers[-1], terms) and offers[-1].get("unit_price", 0) > 0:
                gaps.append(max(0, (offers[-1]["unit_price"] - terms["unit_price"]) / offers[-1]["unit_price"]))
        else:
            responses = [package(case, s["terms"], std) for s in sheets]
            supplier_packages.extend(responses)
            if last_ask:
                for field in case["negotiable"]:
                    if field == "unit_price":
                        continue
                    # One unadopted value per reply, not once per alternative containing it.
                    seen = set()
                    for ask in last_ask:
                        key = f"{field}={str(ask.get(field))}"
                        if key in seen:
                            continue
                        seen.add(key)
                        if not any(s.get(field) == ask.get(field) for s in responses):
                            unadopted[key] = unadopted.get(key, 0) + 1
                last_ask = None
            offers.append(terms)
    change = None
    stalls = 0
    if len(offers) >= 2 and same_package(offers[-1], offers[-2]):
        change = round(offers[-2]["unit_price"] - offers[-1]["unit_price"], 4)
        for a, b in zip(reversed(offers[:-1]), reversed(offers[1:]), strict=True):
            if not same_package(a, b) or abs(a["unit_price"] - b["unit_price"]) > 0.005:
                break
            stalls += 1
    gap = None
    if ours and offers and same_package(ours[-1], offers[-1]):
        gap = max(0, offers[-1]["unit_price"] - ours[-1]["unit_price"])
    # One hold probe after a first concession that closed at least as much distance as
    # remains. This is a policy hypothesis, not a claim that the supplier has a deep floor.
    hold = len(ours) == 1 and change is not None and change > 0 and gap is not None and change >= gap
    return {
        "buyer_rounds": len(ours),
        "comparable_price_concession": change,
        "remaining_comparable_gap": gap,
        "consecutive_stalls": stalls,
        "hold_probe_eligible": hold,
        "unadopted_terms": unadopted,
        "cumulative_comparable_gap": round(sum(gaps), 4),
        "patience": "unknown; cumulative gap is an exposure measure, not an estimated supplier limit",
        "last_buyer": ours[-1] if ours else None,
        "current_supplier": offers[-1] if offers else None,
        "buyer_packages": buyer_packages,
        "supplier_packages": supplier_packages,
        "current_supplier_packages": responses if supplier_packages else [],
    }


def opening_discount(agent, case, threads, sid):
    """A model stance alone cannot change the anchor; observed competition/drivers can."""
    goal = case["buyer"].get("category_goal")
    configured = agent.p.anchor_leverage or agent.p.anchor_below_open
    if goal != "leverage":
        return configured
    from ..agents.rfq_support import quoted_bids

    competition = any(b["supplier_id"] != sid and b["can_accept"] for b in quoted_bids(agent, case, threads))
    evidence = getattr(agent, "evidence_records", {}).get(sid, {})
    falling_driver = any(
        r.get("kind") == "index" and r.get("calculation", {}).get("change_pct", 0) < 0 for r in evidence.values()
    )
    return min(0.25, max(configured, 0.20)) if competition or falling_driver else configured


def annotate(case, candidates, current, std, supplier, state):
    """Explain non-price concessions at an unchanged price; distinguish cheap from equivalent."""
    if not candidates:
        return candidates
    base = package(case, candidates[0]["terms"], std)
    for row in candidates:
        full = package(case, row["terms"], std)
        changes = {}
        for field in case["negotiable"]:
            if field != "unit_price" and full.get(field) != current.get(field):
                changes[field] = {
                    "from": current.get(field),
                    "to": full.get(field),
                    "unadopted_count": state["unadopted_terms"].get(f"{field}={str(full.get(field))}", 0),
                }
        row["term_changes"] = changes
        row["same_cost_band_as_baseline"] = abs(row["cost"] - candidates[0]["cost"]) <= candidates[0]["cost"] * 0.001
        # Changing only the index clause at the same price isolates protection being surrendered.
        if full.get("index_clause") != current.get("index_clause"):
            protected = {**full, "index_clause": current.get("index_clause")}
            row["index_change_cost_at_same_price"] = round(
                total_cost(case, full, std, supplier) - total_cost(case, protected, std, supplier), 2
            )
        row["probe_fields"] = [f for f in case["negotiable"] if f != "unit_price" and full.get(f) != base.get(f)]
        # Test concessions against our protected terms, not just the supplier's latest
        # demand. Adopting an index for the first time is not weakening its deadband.
        reference = dict(full)
        prior = state.get("last_buyer") or {}
        for field in case["negotiable"]:
            if field in ("unit_price", "index_clause") or field not in prior:
                continue
            restored = {**reference, field: prior[field]}
            if total_cost(case, restored, std, supplier) < total_cost(case, reference, std, supplier) - 0.01:
                reference = restored
        clause = full.get("index_clause")
        if clause:
            structures = [package(case, c["terms"], std) for c in candidates] + state.get("buyer_packages", [])
            comparable = [
                t["index_clause"]
                for t in structures
                if t.get("index_clause")
                and all(t["index_clause"].get(k) == clause.get(k) for k in ("series", "material_share", "base_month"))
            ]
            if comparable:
                protected = max(comparable, key=lambda c: c.get("deadband_pct", 0))
                restored = {**reference, "index_clause": protected}
                if total_cost(case, restored, std, supplier) < total_cost(case, reference, std, supplier) - 0.01:
                    reference = restored
        fields = [f for f in case["negotiable"] if f != "unit_price" and full.get(f) != reference.get(f)]
        quoted = False
        if fields:
            for actual in state.get("current_supplier_packages", []):
                if not same_package(actual, full):
                    continue
                quoted = any(
                    all(previous.get(f) == reference.get(f) for f in fields)
                    and must_haves_ok(case, previous, std)
                    and must_haves_ok(case, actual, std)
                    and total_cost(case, actual, std, supplier) <= total_cost(case, previous, std, supplier) + 0.01
                    for previous in state.get("supplier_packages", [])
                )
                if quoted:
                    break
        reference_price = current.get("unit_price", full["unit_price"])
        row["term_concession"] = {
            "fields": fields,
            "reference_terms": {f: reference[f] for f in case["negotiable"]},
            "cost_at_supplier_price": round(
                max(
                    0,
                    total_cost(case, {**full, "unit_price": reference_price}, std, supplier)
                    - total_cost(case, {**reference, "unit_price": reference_price}, std, supplier),
                ),
                2,
            ),
            "compensation": "supplier_quoted" if quoted else "unconfirmed" if fields else "not_required",
        }
    return candidates


def review_reasons(selected, state, latest):
    reasons = []
    if selected.get("term_concession", {}).get("compensation") == "unconfirmed":
        reasons.append("costly term concession has no observed supplier compensation")
    if any(r.get("result") == "contradicted" for r in latest.get("claim_results") or []):
        reasons.append("supplier disputed cited evidence")
    if state["consecutive_stalls"] >= 2:
        reasons.append("repeated comparable stalls")
    if any(v["unadopted_count"] >= 2 for v in selected.get("term_changes", {}).values()):
        reasons.append("selected trade was repeatedly unadopted")
    return reasons


def review_change_allowed(original, reviewed, review, state, live_sources):
    """A reviewer needs a material reason; small hypothetical cost differences are not one."""
    from .strategy import grounded

    if original["id"] == reviewed["id"]:
        return True
    reason = review.get("reason_code")
    if reason == "uncompensated_concession":
        return (
            original.get("term_concession", {}).get("compensation") == "unconfirmed"
            and reviewed.get("term_concession", {}).get("compensation") != "unconfirmed"
        )
    if reason == "supplier_constraint":
        return bool(grounded([review.get("evidence")], live_sources))
    if reason == "stalled":
        return state["consecutive_stalls"] >= 2
    return False
