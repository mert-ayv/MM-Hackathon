"""Decision review uses public arithmetic only: no model, network, server or quota."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from arena_kit.cost import closing_terms
from csee.agents.decision_review import MAX_VALUATIONS, build_review, compact_review
from csee.agents.strategy_support import price_package

CASES = {
    case["case_id"]: case
    for case in json.loads((Path(__file__).parents[1] / "csee/cases/practice.json").read_text())
}


class ArithmeticAgent:
    def __init__(self, case, threads, full_cost=None):
        self.calls = 0
        self.threads = {
            sid: SimpleNamespace(
                breakdown=None,
                intel=SimpleNamespace(full_cost=full_cost, full_cost_source="public approximate should-cost"),
            )
            for sid in threads
        }
        self.full_cost = full_cost

    def supplier_estimate(self, case, sid, std):
        if self.full_cost is None:
            return None
        return {
            "full_cost": self.full_cost * 0.95,
            "interest_rate": 0.08,
            "standard": closing_terms(case, {"payment_days": 30}, std),
        }

    def price(self, case, threads, sid, terms):
        self.calls += 1
        return price_package(self, case, threads, sid, terms)


def setup(cid="case:P07", **terms):
    case = copy.deepcopy(CASES[cid])
    sid = "sup:unfamiliar"
    case["case_id"], case["suppliers"] = "case:unfamiliar", [sid]
    initial = {"unit_price": 5.56, "payment_days": 30, "contract_months": 24}
    if cid == "case:P02":
        initial = {"unit_price": 370.96, "payment_days": 30, "index_clause": None}
    initial.update(terms)
    threads = {
        sid: [
            {
                "from": "supplier",
                "status": "open",
                "term_sheets": [{"term_sheet_id": "offer:unfamiliar", "terms": initial}],
                "attachments": [
                    {
                        "name": "quote-test.pdf",
                        "text": "Our standard terms\nQuality commitment (ppm) 80\nPayment terms (days net) 30",
                    }
                ],
            }
        ]
    }
    agent = ArithmeticAgent(case, threads, full_cost=374.95 if cid == "case:P02" else None)
    return agent, case, threads, sid


def review(agent, case, threads, sid, **move):
    return build_review(agent, case, threads, sid, {"action": "accept", **move}, {})


def change(report, field, value, basis="standing"):
    return next(
        item
        for item in report["one_field_counterfactuals"]
        if item["basis"] == basis and item["field"] == field and item["to"] == value
    )


def test_kit_payment_value_and_neutral_contract_are_visible_for_an_unfamiliar_id():
    agent, case, threads, sid = setup()
    report = review(agent, case, threads, sid)
    assert report["standing"]["estimated_total_cost"] == pytest.approx(335852.8)
    payment = change(report, "payment_days", 90)
    assert payment["mathematical_saving"] == pytest.approx(4448)
    assert payment["estimated_total_cost"] == pytest.approx(331404.8)
    assert payment["acceptance"] == "unknown"
    neutral = change(report, "contract_months", 36)
    assert neutral["mathematical_saving"] == 0
    assert neutral["coverage"]["contract_beyond_valued_horizon_months"] == 12
    material = {lever["field"]: lever for lever in report["material_levers"]}
    assert material["payment_days"]["best_lower_cost_option"]["to"] == 90
    assert material["contract_months"]["cost_neutral_options"]
    assert any("no relationship penalty" in text for text in report["warnings"])
    json.dumps(report, allow_nan=False)


def test_short_contract_discloses_uncovered_need_and_proposal_cost_delta():
    agent, case, threads, sid = setup()
    report = review(
        agent,
        case,
        threads,
        sid,
        action="counter",
        term_sheets=[{"unit_price": 5.74, "contract_months": 12}],
    )
    proposal = report["proposed_packages"][0]
    assert proposal["terms"]["payment_days"] == 30
    assert proposal["coverage"]["uncovered_units"] == 30000
    assert proposal["coverage"]["uncovered_need_and_risk_cost"] == pytest.approx(217665)
    assert proposal["estimated_total_cost"] == pytest.approx(391027.4)
    assert proposal["delta_vs_standing"] == pytest.approx(55174.6)
    assert change(report, "contract_months", 24, "proposed:1")["mathematical_saving"] > 0


def test_payment_trade_exposes_buyer_cash_neutral_price_without_acceptance_prediction():
    agent, case, threads, sid = setup()
    report = review(agent, case, threads, sid)
    payment = change(report, "payment_days", 90)
    trade = next(item for item in report["payment_trade_values"] if item["counterfactual_id"] == payment["id"])
    assert trade["buyer_financing_cost_change"] == -4448
    expected = 5.56 * (1 + 0.08 * 30 / 360) / (1 - 0.08 * 30 / 360)
    assert trade["buyer_cash_neutral_unit_price"] == pytest.approx(expected, abs=0.00005)
    assert "acceptance is unknown" in trade["assumption"]
    assert "acceptance_probability" not in trade
    assert not any(item["field"] == "unit_price" for item in report["one_field_counterfactuals"])


def test_price_increase_review_keeps_cost_uncertainty_and_prices_index_removal():
    agent, case, threads, sid = setup("case:P02")
    clause = case["term_options"]["index_clause"][-1]
    threads[sid][0]["term_sheets"][0]["terms"]["index_clause"] = clause
    report = review(agent, case, threads, sid)
    assert report["standing"]["supplier_cost_confidence"] == "low"
    assert len(report["standing"]["sensitivity_scenarios"]) == 3
    assert change(report, "index_clause", None)["mathematical_saving"] > 0
    assert any("uncertain supplier economics" in text for text in report["warnings"])
    assert all(item["acceptance"] == "unknown" for item in report["one_field_counterfactuals"])


def test_bad_options_and_must_have_violations_are_not_presented_as_valid_changes():
    agent, case, threads, sid = setup()
    case["term_options"]["payment_days"] = [14, 30, 60, 90, 150, -1, 60.5, "late"]
    case["buyer"]["must_haves"] = [{"field": "payment_days", "op": "<=", "value": 60}]
    report = review(agent, case, threads, sid)
    values = [item["to"] for item in report["one_field_counterfactuals"] if item["field"] == "payment_days"]
    assert set(values) == {14, 60}


def test_unlisted_supplier_standard_terms_survive_omitted_negotiable_fields():
    agent, case, threads, sid = setup()
    case["negotiable"].append("ppm_commitment")
    case["term_options"]["ppm_commitment"] = [10, 20]
    report = review(agent, case, threads, sid, action="counter", term_sheets=[{"unit_price": 5.5}])
    assert report["standing"]["terms"]["ppm_commitment"] == 80
    assert report["proposed_packages"][0]["terms"]["ppm_commitment"] == 80
    assert report["proposed_packages"][0]["breakdown"]["quality"] == 28.8


def test_missing_business_bounds_do_not_create_lead_time_or_volume_ranges():
    agent, case, threads, sid = setup(contract_months=12)
    case["negotiable"].extend(["lead_time_days", "volume_per_year"])
    for field in ("lead_time_days", "volume_per_year"):
        case["fixed_terms"].pop(field)
    case["term_options"].pop("contract_months")
    report = review(agent, case, threads, sid)
    fields = {item["field"] for item in report["one_field_counterfactuals"]}
    assert not fields & {"lead_time_days", "volume_per_year"}
    coverage = change(report, "contract_months", 24)
    assert coverage["source"] == "buyer_horizon_within_contract_schema"
    assert coverage["coverage"]["uncovered_units"] == 0


def test_other_live_standing_quotes_are_compared_without_accepting_supplier_alternatives():
    agent, case, threads, sid = setup()
    other = "sup:other"
    threads[other] = copy.deepcopy(threads[sid])
    threads[other][0]["term_sheets"][0] = {
        "term_sheet_id": "offer:other",
        "terms": {"unit_price": 5.4, "payment_days": 90, "contract_months": 24},
    }
    threads[other][0]["term_sheets"].append(
        {"term_sheet_id": "offer:unconfirmed-alternative", "terms": {"unit_price": 1, "contract_months": 24}}
    )
    agent.threads[other] = agent.threads[sid]
    report = review(agent, case, threads, sid)
    assert len(report["other_live_standings"]) == 1
    assert report["other_live_standings"][0]["offer_id"] == "offer:other"
    assert report["other_live_standings"][0]["terms"]["unit_price"] == 5.4


def test_review_does_not_mutate_the_move_or_received_terms():
    agent, case, threads, sid = setup()
    move = {"action": "counter", "term_sheets": [{"unit_price": 5.4}], "review_id": "previous"}
    original = copy.deepcopy((case, threads, move))
    build_review(agent, case, threads, sid, move, {})
    assert (case, threads, move) == original


def test_large_option_sets_keep_review_work_bounded_and_report_sampling():
    agent, case, threads, sid = setup()
    for field in ("lead_time_days", "volume_per_year", "ppm_commitment", "tooling_eur", "chargeback_eur_per_complaint"):
        case["negotiable"].append(field)
        case["fixed_terms"].pop(field, None)
        case["term_options"][field] = list(range(1, 101)) if field != "volume_per_year" else list(range(29901, 30001))
    report = review(
        agent,
        case,
        threads,
        sid,
        action="counter",
        term_sheets=[{"unit_price": 5.4}, {"unit_price": 5.5}, {"unit_price": 5.6}],
    )
    assert agent.calls == report["valuation_count"] <= MAX_VALUATIONS
    assert report["truncated"]
    assert any("sampled" in text for text in report["warnings"])
    assert {item["field"] for item in report["material_levers"]} >= {"payment_days", "contract_months"}


def test_non_negotiable_draft_fields_are_reported_instead_of_silently_dropped():
    agent, case, threads, sid = setup()
    report = review(agent, case, threads, sid, action="counter", term_sheets=[{"unit_price": 5.4, "new_part": 1}])
    assert not report["proposed_packages"]
    assert "non-negotiable" in report["errors"][0]["error"]


@pytest.mark.parametrize("cid", ["case:P07", "case:P02"])
def test_compact_review_keeps_all_levers_and_sensitivity_inside_tool_budget(cid):
    agent, case, threads, sid = setup(cid)
    price = 350 if cid == "case:P02" else 5.4
    report = review(
        agent,
        case,
        threads,
        sid,
        action="counter",
        term_sheets=[{"unit_price": price + index, "payment_days": days} for index, days in enumerate((30, 60, 90))],
    )
    before = copy.deepcopy(report)
    compact = compact_review(report)
    assert len(json.dumps(compact, allow_nan=False)) < 19000
    assert {item["field"] for item in compact["material_levers"]} == {
        item["field"] for item in report["material_levers"]
    }
    for full, brief in zip(report["proposed_packages"], compact["proposed_packages"], strict=True):
        assert brief["terms"] == full["terms"]
        assert brief["breakdown"] == full["breakdown"]
        assert brief["sensitivity_scenarios"] == full["sensitivity_scenarios"]
    assert report == before
