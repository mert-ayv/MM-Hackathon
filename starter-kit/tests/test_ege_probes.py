"""Probe follow-through uses negotiation history, never model/network/server calls."""

import copy

import pytest

from csee.agents.probe_tracking import MAX_PROBES, ProbeDecision, build_probe_review, resolve_probes

REASON = "The possible benefit is uncertain; this explicit choice reflects the current supplier response."


def setup():
    case = {
        "case_id": "case:unfamiliar-bundle",
        "negotiable": ["unit_price", "payment_days", "contract_months"],
    }
    sid = "sup:new-supplier"
    threads = {
        sid: [
            {
                "from": "supplier",
                "status": "open",
                "term_sheets": [{"terms": {"unit_price": 7.1, "payment_days": 30, "contract_months": 24}}],
            }
        ],
    }
    payment = {
        "basis": "standing",
        "field": "payment_days",
        "from": 30,
        "to": 90,
        "mathematical_saving": 5000,
        "cash_saving": 5000,
    }
    contract = {
        "basis": "standing",
        "field": "contract_months",
        "from": 24,
        "to": 36,
        "mathematical_saving": 0,
        "cash_saving": 0,
    }
    economics = {
        "action": "counter",
        "proposed_packages": [{"terms": {"unit_price": 6.9, "payment_days": 30}}],
        "one_field_counterfactuals": [payment, contract],
        "material_levers": [
            {"field": "payment_days", "best_lower_cost_option": payment, "cost_neutral_options": []},
            {"field": "contract_months", "best_lower_cost_option": None, "cost_neutral_options": [contract]},
        ],
    }
    return case, threads, sid, economics


def opportunity(review, field):
    return next(item for item in review["opportunities"] if item["field"] == field)


def decide(review, action="decline", **overrides):
    return [
        ProbeDecision(probe_id=probe_id, action=overrides.get(probe_id, action), reason=REASON)
        for probe_id in review["required_ids"]
    ]


def resolve(case, threads, sid, review, decisions, sheets=None, action="counter"):
    return resolve_probes(case, threads, sid, review, decisions, sheets or [], action)


def defer_payment(case, threads, sid, economics):
    review = build_probe_review(case, threads, sid, economics, {})
    payment_id = opportunity(review, "payment_days")["probe_id"]
    records, error = resolve(case, threads, sid, review, decide(review, **{payment_id: "defer"}))
    assert error is None
    return records, payment_id


def sent(threads, sid, payment_days=30):
    threads[sid].append(
        {
            "from": "buyer",
            "term_sheets": [{"terms": {"unit_price": 6.9, "payment_days": payment_days, "contract_months": 24}}],
        }
    )


def test_counter_requires_every_untested_material_opportunity_but_closing_does_not():
    case, threads, sid, economics = setup()
    review = build_probe_review(case, threads, sid, economics, {})
    assert len(review["required_ids"]) == 2
    records, error = resolve(case, threads, sid, review, [])
    assert records is None and "structured probe decisions required" in error
    records, error = resolve(case, threads, sid, review, decide(review))
    assert error is None and {record["status"] for record in records.values()} == {"declined"}
    economics["action"] = "accept"
    closing_review = build_probe_review(case, threads, sid, economics, {})
    assert not closing_review["required_ids"]
    records, error = resolve(case, threads, sid, closing_review, [], action="accept")
    assert records == {} and error is None


def test_exact_target_matters_sixty_days_does_not_test_ninety():
    case, threads, sid, economics = setup()
    sent(threads, sid, payment_days=60)
    review = build_probe_review(case, threads, sid, economics, {})
    payment = opportunity(review, "payment_days")
    assert payment["target_value"] == 90 and not payment["previously_requested"]
    assert payment["probe_id"] in review["required_ids"]
    threads[sid][-1]["term_sheets"][0]["terms"]["payment_days"] = 90
    review = build_probe_review(case, threads, sid, economics, {})
    assert opportunity(review, "payment_days")["previously_requested"]
    assert payment["probe_id"] not in review["required_ids"]
    records, error = resolve(case, threads, sid, review, decide(review))
    assert error is None and records[payment["probe_id"]]["status"] == "attempted"
    assert "acceptance remains unknown" in records[payment["probe_id"]]["reason"]


def test_third_outgoing_sheet_automatically_fulfils_the_exact_probe():
    case, threads, sid, economics = setup()
    economics["proposed_packages"] = [
        {"terms": {"unit_price": 6.9, "payment_days": 30}},
        {"terms": {"unit_price": 6.8, "payment_days": 14}},
        {"terms": {"unit_price": 7.0, "payment_days": 90}},
    ]
    review = build_probe_review(case, threads, sid, economics, {})
    payment = opportunity(review, "payment_days")
    assert payment["proposed_now"] and payment["probe_id"] not in review["required_ids"]
    sheets = [item["terms"] for item in economics["proposed_packages"]]
    records, error = resolve(case, threads, sid, review, decide(review), sheets)
    assert error is None and records[payment["probe_id"]]["status"] == "attempted"


def test_self_reported_test_without_a_matching_package_is_rejected():
    case, threads, sid, economics = setup()
    review = build_probe_review(case, threads, sid, economics, {})
    payment = opportunity(review, "payment_days")
    decisions = decide(review, **{payment["probe_id"]: "test_now"})
    records, error = resolve(case, threads, sid, review, decisions, [{"payment_days": 60}])
    assert records is None and "actual outgoing package target" in error


def test_deferral_is_due_after_one_actual_buyer_message_and_cannot_be_repeated():
    case, threads, sid, economics = setup()
    records, payment_id = defer_payment(case, threads, sid, economics)
    assert records[payment_id]["due_turn"] == 1 and records[payment_id]["deferred_once"]
    for _ in range(3):  # Draft/review/model retries never advance the negotiation clock.
        same_turn = build_probe_review(case, threads, sid, economics, records)
        assert same_turn["current_turn"] == 0
        assert same_turn["pending"][0]["due_turn"] == 1
    sent(threads, sid)
    due = build_probe_review(case, threads, sid, economics, records)
    assert due["current_turn"] == 1 and payment_id in due["required_ids"]
    updated, error = resolve(case, threads, sid, due, decide(due, **{payment_id: "defer"}))
    assert updated is None and "cannot be deferred again" in error
    updated, error = resolve(
        case,
        threads,
        sid,
        due,
        decide(due, **{payment_id: "test_now"}),
        [{"payment_days": 90}],
    )
    assert error is None and updated[payment_id]["status"] == "attempted"
    assert records[payment_id]["status"] == "pending"


def test_cancellation_history_prevents_restarting_the_deferral_clock():
    case, threads, sid, economics = setup()
    records, payment_id = defer_payment(case, threads, sid, economics)
    sent(threads, sid)
    due = build_probe_review(case, threads, sid, economics, records)
    cancelled, error = resolve(case, threads, sid, due, decide(due))
    assert error is None and cancelled[payment_id]["status"] == "declined"
    sent(threads, sid)
    economics["material_levers"][0]["best_lower_cost_option"]["to"] = 90.0
    again = build_probe_review(case, threads, sid, economics, cancelled)
    assert opportunity(again, "payment_days")["probe_id"] == payment_id
    updated, error = resolve(case, threads, sid, again, decide(again, **{payment_id: "defer"}))
    assert updated is None and "cannot be deferred again" in error
    assert cancelled[payment_id]["due_turn"] == 1


def test_due_pending_probe_survives_missing_material_economics():
    case, threads, sid, economics = setup()
    records, payment_id = defer_payment(case, threads, sid, economics)
    sent(threads, sid)
    economics["material_levers"] = []
    economics["one_field_counterfactuals"] = []
    due = build_probe_review(case, threads, sid, economics, records)
    assert due["required_ids"] == [payment_id]
    assert opportunity(due, "payment_days")["target_value"] == 90
    updated, error = resolve(case, threads, sid, due, [])
    assert updated is None and "structured probe decisions" in error
    updated, error = resolve(case, threads, sid, due, decide(due))
    assert error is None and updated[payment_id]["status"] == "declined"


@pytest.mark.parametrize("action", ["accept", "ready", "walk_away"])
def test_final_offer_can_close_by_cancelling_pending_probe_without_another_counter(action):
    case, threads, sid, economics = setup()
    records, payment_id = defer_payment(case, threads, sid, economics)
    sent(threads, sid)
    threads[sid].append({"from": "supplier", "status": "final_offer", "body": "This is our final package."})
    economics["action"] = action
    closing = build_probe_review(case, threads, sid, economics, records)
    assert closing["required_ids"] == [payment_id]
    updated, error = resolve(case, threads, sid, closing, [], action=action)
    assert updated is None and "structured probe decisions" in error
    updated, error = resolve(case, threads, sid, closing, decide(closing), action=action)
    assert error is None and updated[payment_id]["status"] == "declined"
    updated, error = resolve(case, threads, sid, closing, decide(closing, "defer"), action=action)
    assert updated is None and "closing cannot defer" in error


def test_review_and_draft_resolution_leave_all_caller_state_unchanged():
    case, threads, sid, economics = setup()
    records, _ = defer_payment(case, threads, sid, economics)
    before = copy.deepcopy((case, threads, economics, records))
    review = build_probe_review(case, threads, sid, economics, records)
    review_before = copy.deepcopy(review)
    decisions = decide(review)
    updated, error = resolve(case, threads, sid, review, decisions)
    assert error is None and updated is not records
    assert (case, threads, economics, records) == before and review == review_before
    updated[next(iter(updated))]["reason"] = "Changed only in returned copy"
    assert records == before[-1] and review == review_before


def test_stale_or_misrouted_review_and_duplicate_decisions_are_rejected():
    case, threads, sid, economics = setup()
    review = build_probe_review(case, threads, sid, economics, {})
    choices = decide(review)
    updated, error = resolve(case, threads, sid, review, [choices[0], choices[0]])
    assert updated is None and "exactly one decision" in error
    sent(threads, sid)
    updated, error = resolve(case, threads, sid, review, choices)
    assert updated is None and "stale" in error


def test_stable_ids_ignore_comparison_order_and_prefer_standing_source():
    case, threads, sid, economics = setup()
    standing = copy.deepcopy(economics["one_field_counterfactuals"][0])
    proposed = copy.deepcopy(standing)
    proposed.update(basis="proposed:3", mathematical_saving=6000)
    economics["material_levers"][0]["best_lower_cost_option"] = proposed
    review = build_probe_review(case, threads, sid, economics, {})
    first = opportunity(review, "payment_days")
    assert first["comparison"]["basis"] == "standing"
    economics["material_levers"].reverse()
    economics["one_field_counterfactuals"].reverse()
    economics["material_levers"][1]["best_lower_cost_option"]["to"] = 90.0
    second = opportunity(build_probe_review(case, threads, sid, economics, {}), "payment_days")
    assert first["probe_id"] == second["probe_id"]


def test_index_targets_are_stable_for_reordered_dicts_but_distinct_for_different_clauses():
    case, threads, sid, economics = setup()
    case["negotiable"].append("index_clause")
    clause = {"series": "NEW-INDEX", "material_share": 0.3, "deadband_pct": 5}
    row = {"basis": "standing", "field": "index_clause", "from": None, "to": clause, "mathematical_saving": 0}
    economics["material_levers"] = [{"field": "index_clause", "cost_neutral_options": [row]}]
    first = opportunity(build_probe_review(case, threads, sid, economics, {}), "index_clause")
    row["to"] = dict(reversed(list(clause.items())))
    same = opportunity(build_probe_review(case, threads, sid, economics, {}), "index_clause")
    assert first["probe_id"] == same["probe_id"]
    row["to"]["deadband_pct"] = 3
    different = opportunity(build_probe_review(case, threads, sid, economics, {}), "index_clause")
    assert first["probe_id"] != different["probe_id"]


def test_review_bounds_new_candidates_without_dropping_pending_obligations():
    case, threads, sid, economics = setup()
    records, payment_id = defer_payment(case, threads, sid, economics)
    economics["material_levers"] = []
    for i in range(20):
        field = f"new_field_{i}"
        case["negotiable"].append(field)
        row = {"field": field, "basis": "standing", "from": 1, "to": 2, "mathematical_saving": 1}
        economics["material_levers"].append({"field": field, "best_lower_cost_option": row})
    review = build_probe_review(case, threads, sid, economics, records)
    assert len(review["opportunities"]) == MAX_PROBES
    assert review["pending"][0]["probe_id"] == payment_id
    assert payment_id in {item["probe_id"] for item in review["opportunities"]}
    assert any("all pending probes retained" in warning for warning in review["warnings"])


def test_oversized_pending_ledger_fails_explicitly_without_silently_dropping_records():
    case, threads, sid, economics = setup()
    records = {
        f"probe:existing-{i}": {
            "probe_id": f"probe:existing-{i}",
            "field": "payment_days",
            "target_value": 30 + i,
            "status": "pending",
            "due_turn": 1,
        }
        for i in range(MAX_PROBES + 1)
    }
    original = copy.deepcopy(records)
    review = build_probe_review(case, threads, sid, economics, records)
    assert "none were dropped" in review["error"]
    assert len(review["pending"]) == MAX_PROBES + 1
    updated, error = resolve(case, threads, sid, review, [])
    assert updated is None and "exceed" in error
    assert records == original


@pytest.mark.parametrize("inherit_standard", [False, True, "null"])
def test_first_standing_offer_fulfils_pending_target_without_a_buyer_request(inherit_standard):
    case, threads, sid, economics = setup()
    records, payment_id = defer_payment(case, threads, sid, economics)
    sent(threads, sid)
    quote = {
        "from": "supplier",
        "status": "final_offer",
        "term_sheets": [{"terms": {"unit_price": 6.95, "payment_days": 90}}],
    }
    if inherit_standard:
        quote["term_sheets"][0]["terms"].pop("payment_days")
        if inherit_standard == "null":
            quote["term_sheets"][0]["terms"]["payment_days"] = None
        quote["attachments"] = [
            {
                "name": "quote-new.pdf",
                "text": "Our standard terms\nPayment terms (days net) 90",
            }
        ]
    threads[sid].append(quote)
    economics["action"] = "accept"
    closing = build_probe_review(case, threads, sid, economics, records)
    payment = opportunity(closing, "payment_days")
    assert payment["currently_offered"] and not payment["previously_requested"]
    assert payment["status"] == "fulfilled" and payment_id not in closing["required_ids"]
    updated, error = resolve(case, threads, sid, closing, [], action="accept")
    assert error is None and updated[payment_id]["status"] == "fulfilled"
    optional = [{"probe_id": payment_id, "action": "decline", "reason": REASON}]
    updated, error = resolve(case, threads, sid, closing, optional, action="accept")
    assert error is None and updated[payment_id]["status"] == "fulfilled"


def test_supplier_alternative_does_not_fulfil_pending_target_in_first_standing_sheet():
    case, threads, sid, economics = setup()
    records, payment_id = defer_payment(case, threads, sid, economics)
    sent(threads, sid)
    threads[sid].append(
        {
            "from": "supplier",
            "status": "final_offer",
            "term_sheets": [
                {"terms": {"unit_price": 6.9, "payment_days": 30}},
                {"terms": {"unit_price": 7.0, "payment_days": 90}},
            ],
        }
    )
    economics["action"] = "accept"
    closing = build_probe_review(case, threads, sid, economics, records)
    assert not opportunity(closing, "payment_days")["currently_offered"]
    assert payment_id in closing["required_ids"]
    updated, error = resolve(case, threads, sid, closing, [], action="accept")
    assert updated is None and "structured probe decisions" in error


def test_unsent_attempted_ledger_entry_does_not_hide_an_untested_target():
    case, threads, sid, economics = setup()
    economics["proposed_packages"] = [{"terms": {"payment_days": 90}}]
    drafted = build_probe_review(case, threads, sid, economics, {})
    payment_id = opportunity(drafted, "payment_days")["probe_id"]
    constructed, error = resolve(case, threads, sid, drafted, decide(drafted), [{"payment_days": 90}])
    assert error is None and constructed[payment_id]["status"] == "attempted"
    # The transport never appended that proposed message to actual negotiation history.
    economics["proposed_packages"] = [{"terms": {"payment_days": 30}}]
    next_review = build_probe_review(case, threads, sid, economics, constructed)
    assert opportunity(next_review, "payment_days")["status"] == "untested"
    assert payment_id in next_review["required_ids"]
    updated, error = resolve(case, threads, sid, next_review, [])
    assert updated is None and "structured probe decisions" in error
