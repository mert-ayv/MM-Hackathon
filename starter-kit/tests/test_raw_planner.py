"""Raw-material planner regressions; synthetic replies, no model or arena calls."""

import copy
import json
import math
from pathlib import Path

import pytest

from arena_kit.cost import closing_terms, must_haves_ok, total_cost
from csee import variants
from csee.agents.mert import PlannerRawAgent

CASES = json.loads((Path(__file__).parents[1] / "csee/cases/practice.json").read_text())


@pytest.fixture(params=["case:P08", "case:P18"])
def case(request):
    case = copy.deepcopy(next(case for case in CASES if case["case_id"] == request.param))
    # The same policy must work without a supplier profile or familiar identifiers.
    case.update(case_id="case:unfamiliar-raw", suppliers=["sup:unfamiliar-raw"], parts=["part:unfamiliar"])
    case["refs"] = []
    return case


def reply(case, number, price, *, indexed=True, status="open", alternatives=False):
    clause = case["term_options"]["index_clause"][-1] if indexed else None
    terms = {
        "unit_price": price,
        "payment_days": 90 if indexed else 30,
        "contract_months": 24 if indexed else 12,
        "index_clause": clause,
    }
    sheets = [{"term_sheet_id": f"offer:raw-{number}", "terms": terms}]
    if alternatives:
        sheets.append(
            {
                "term_sheet_id": f"offer:raw-{number}-a",
                "terms": {**terms, "unit_price": price - 0.1, "payment_days": 30},
            }
        )
    return {
        "from": "supplier",
        "status": status,
        "body": "Our price for an indexed contract.",
        "term_sheets": sheets,
        "attachments": [],
    }


def setup(case, *, first=False, status="open"):
    sid = case["suppliers"][0]
    events = [reply(case, 0, 6.1, indexed=False)]
    if not first:
        package = {
            "unit_price": 4.69,
            "payment_days": 90,
            "contract_months": 24,
            "index_clause": case["term_options"]["index_clause"][-1],
        }
        events += [
            {"from": "buyer", "term_sheets": [{"terms": package}]},
            reply(case, 1, 5.6, alternatives=True),
            {"from": "buyer", "term_sheets": [{"terms": {**package, "unit_price": 4.82}}]},
            reply(case, 2, 5.5, status=status, alternatives=True),
        ]
    agent = PlannerRawAgent(params=variants.params("v16a"))
    threads = {sid: events}
    agent.prepare(case, threads)
    # A disclosed existing index clause triggers Emre's initial fixed -> indexed replacement.
    agent.status_quo[sid] = "AS-14404"
    return agent, threads, sid


def test_final_main_package_carries_the_planned_concession_after_clause_conversion(case):
    agent, threads, sid = setup(case, first=True)
    message = agent.thread_move(case, threads, sid)
    state = agent.threads[sid]
    sup = agent.sup_model(case, sid, {})
    values = [agent.sval(case, sup, sheet["terms"]) for sheet in message["term_sheets"]]
    assert message["term_sheets"][0]["terms"]["index_clause"] is not None
    assert 0 <= state.plan_v - max(values) < 0.011  # At most one price tick, not the old 7–8 cent loss.
    assert all(value <= values[0] + 1e-9 for value in values)


def test_confirmed_indexed_structure_survives_and_longer_trade_has_its_own_slot(case):
    agent, threads, sid = setup(case)
    message = agent.thread_move(case, threads, sid)
    sheets = [item["terms"] for item in message["term_sheets"]]
    assert all(sheet["index_clause"] for sheet in sheets)
    assert len(sheets) <= 3
    assert all(not agent.same_terms(a, b) for i, a in enumerate(sheets) for b in sheets[i + 1 :])
    long = next(sheet for sheet in sheets if sheet["contract_months"] == 36)
    main, sup = sheets[0], agent.sup_model(case, sid, {})
    assert total_cost(case, long) <= total_cost(case, main) * (1 - agent.p.trade_gain)
    assert agent.sval(case, sup, long) <= agent.sval(case, sup, main) + 1e-9
    for sheet in sheets:
        complete = closing_terms(case, sheet)
        assert complete["volume_per_year"] == case["fixed_terms"]["volume_per_year"]
        assert must_haves_ok(case, sheet)
        assert math.isfinite(total_cost(case, sheet))


def test_final_offer_alternative_is_confirmed_exactly_without_a_new_price_push(case):
    agent, threads, sid = setup(case, status="final_offer")
    offered = threads[sid][-1]["term_sheets"][1]["terms"]
    message = agent.thread_move(case, threads, sid)
    assert [item["terms"] for item in message["term_sheets"]] == [offered]
    assert agent.p.final_push == 0 and agent.p.push_after_final == 0


def test_falling_index_keeps_the_cost_minimal_deadband_in_every_package(case):
    case["buyer"]["index_paths"]["AS-14404"] = -0.06
    agent, threads, sid = setup(case)
    message = agent.thread_move(case, threads, sid)
    assert message
    assert all(item["terms"]["index_clause"]["deadband_pct"] == 0 for item in message["term_sheets"])


def test_fixed_price_case_does_not_create_a_price_trade(case):
    case["negotiable"].remove("unit_price")
    case["fixed_terms"]["unit_price"] = 6.1
    agent, threads, sid = setup(case, first=True)
    message = agent.thread_move(case, threads, sid)
    assert message
    assert all(set(item["terms"]) == set(case["negotiable"]) for item in message["term_sheets"])
