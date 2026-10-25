"""RFQ competition and auction closing with unfamiliar bidders, no arena or model network calls."""

import copy
import json
import threading

import pytest

from arena_kit.cost import closing_terms, total_cost
from csee.agents.ege import EgeAgent, Move, Plan
from csee.agents.rfq_support import compare_bids, competitive_claims
from csee.runner import play_case


def quote(sid, price, status="open", **terms):
    return {
        "from": "supplier",
        "status": status,
        "body": "Our quotation. We can discuss the payment and delivery trade.",
        "term_sheets": [{"term_sheet_id": f"offer:{sid}-0", "terms": {"unit_price": price, **terms}}],
        "attachments": [
            {
                "name": "quote-rfq.pdf",
                "text": "Our standard terms\nPayment terms (days net) 30\n"
                "Lead time (days) 35\nQuality commitment (ppm) 80",
            }
        ],
    }


def setup():
    case = {
        "case_id": "case:UNSEEN-RFQ",
        "type": "rfq",
        "title": "RFQ for an unfamiliar assembly",
        "suppliers": ["sup:alpha", "sup:beta"],
        "parts": ["part:unfamiliar"],
        "refs": [],
        "negotiable": ["unit_price", "payment_days", "lead_time_days"],
        "fixed_terms": {
            "volume_per_year": 1000,
            "contract_months": 24,
            "effective_date": "2027-01-01",
            "incoterm": "DAP",
            "tooling_eur": 0,
            "index_clause": None,
        },
        "term_options": {"payment_days": [14, 30, 60, 90], "lead_time_days": [28, 35, 42, 56]},
        "buyer": {
            "need_per_year": 1000,
            "horizon_years": 2,
            "current_unit_price": 15,
            "fallback_unit_price": 20,
            "category_goal": "leverage",
            "interest_rate": 0.08,
            "reference_payment_days": 60,
            "need_lead_time_days": 35,
            "cost_per_defect": 100,
            "late_cost_per_day": 1000,
            "freight_eur_per_unit": {"DAP": 0, "FCA": 1},
            "must_haves": [{"field": "lead_time_days", "op": "<=", "value": 42}],
            "alternative": {"kind": "none", "terms": {}},
        },
        "round_limit": 10,
    }
    threads = {
        "sup:alpha": [quote("alpha", 11, payment_days=60, lead_time_days=35)],
        "sup:beta": [quote("beta", 10, payment_days=14, lead_time_days=42)],
    }
    agent = EgeAgent()
    agent.prepare(case, threads)
    return agent, case, threads


def test_complete_cost_ranks_a_higher_unit_price_ahead_of_a_slow_bid():
    agent, case, threads = setup()
    report = compare_bids(agent, case, threads, "sup:alpha")
    assert report["best_standing"]["supplier_id"] == "sup:alpha"
    assert report["best_rival"]["supplier_id"] == "sup:beta"
    for bid in report["standing_bids_ranked"]:
        sid = bid["supplier_id"]
        assert bid["estimated_total_cost"] == total_cost(
            case, threads[sid][0]["term_sheets"][0]["terms"], closing_terms(case, {"ppm_commitment": 80})
        )
        assert bid["terms"]["ppm_commitment"] == 80
        assert bid["terms"]["volume_per_year"] == 1000
    assert competitive_claims(agent, case, threads, "sup:alpha") == []


def test_alternatives_use_their_own_defaults_and_are_never_ranked_as_awardable():
    agent, case, threads = setup()
    main = threads["sup:beta"][0]["term_sheets"][0]["terms"]
    main.update(payment_days=90, lead_time_days=28)
    threads["sup:beta"][0]["term_sheets"].append(
        {"term_sheet_id": "offer:beta-alternative", "terms": {"unit_price": 8}}
    )
    report = compare_bids(agent, case, threads, "sup:alpha")
    alternative = report["unconfirmed_alternatives"][0]
    assert alternative["terms"]["payment_days"] == 30
    assert alternative["terms"]["lead_time_days"] == 35
    assert alternative["needs_confirmation"] and not alternative["can_accept"]
    assert alternative["estimated_total_cost"] < report["best_standing"]["estimated_total_cost"]
    assert report["best_standing"]["offer_id"] == "offer:beta-0"
    claims = competitive_claims(agent, case, threads, "sup:alpha")
    assert all(claim.ids != ["offer:beta-alternative"] for claim in claims)
    award = agent.close(case, threads, force=True)
    assert award["message"]["action"]["term_sheet_id"] == "offer:beta-0"


@pytest.mark.parametrize("bad", ["ended", "late", "nan", "zero", "missing_id", "missing_price"])
def test_unusable_bids_cannot_anchor_competition_or_create_nonfinite_json(bad):
    agent, case, threads = setup()
    message = threads["sup:beta"][0]
    terms = message["term_sheets"][0]["terms"]
    terms.update(unit_price=1, lead_time_days=35)
    if bad == "ended":
        message["status"] = "walked_away"
    elif bad == "late":
        terms["lead_time_days"] = 56
    elif bad == "nan":
        terms["unit_price"] = float("nan")
    elif bad == "zero":
        terms["unit_price"] = 0
    elif bad == "missing_id":
        message["term_sheets"][0]["term_sheet_id"] = None
    else:
        terms.pop("unit_price")
    report = compare_bids(agent, case, threads, "sup:alpha")
    assert report["best_standing"]["supplier_id"] == "sup:alpha"
    assert report["best_rival"] is None and report["match_rival"] is None
    assert len(report["invalid_bids"]) == 1
    assert competitive_claims(agent, case, threads, "sup:alpha") == []
    assert agent.close(case, threads, force=True)["supplier_id"] == "sup:alpha"
    json.dumps(report, allow_nan=False)


def test_match_price_accounts_for_our_package_and_checks_price_rounding():
    agent, case, threads = setup()
    threads["sup:beta"][0]["term_sheets"][0]["terms"].update(payment_days=90, lead_time_days=35)
    before = copy.deepcopy(threads)
    report = compare_bids(agent, case, threads, "sup:alpha", {"payment_days": 14, "lead_time_days": 42})
    match, rival = report["match_rival"], report["best_rival"]
    assert match["terms"]["unit_price"] < rival["terms"]["unit_price"]
    assert match["estimated_total_cost"] <= rival["estimated_total_cost"]
    assert match["acceptance"] == "unknown"
    assert match["terms"]["payment_days"] == 14
    assert match["terms"]["lead_time_days"] == 42
    assert threads == before
    better_terms = compare_bids(agent, case, threads, "sup:alpha", {"payment_days": 90, "lead_time_days": 35})
    assert better_terms["match_rival"]["terms"]["unit_price"] > match["terms"]["unit_price"]


def test_competitive_claim_uses_a_live_valid_lower_cost_and_lower_price_quote():
    agent, case, threads = setup()
    threads["sup:beta"][0]["term_sheets"][0]["terms"].update(lead_time_days=35)
    claims = competitive_claims(agent, case, threads, "sup:alpha")
    assert len(claims) == 1 and claims[0].ids == ["offer:beta-0"]
    assert "EUR 10.00" in claims[0].sentence
    assert competitive_claims(agent, case, threads, "sup:beta") == []
    arguments = agent.arguments(case, threads, "sup:alpha")
    assert any(claim.ids == ["offer:beta-0"] for claim in arguments.values())
    assert not any(claim.kind == "rival" for claim in agent.arguments(case, threads, "sup:beta").values())


def test_tooling_and_supplier_quality_defaults_change_the_ranking_and_match_price():
    agent, case, threads = setup()
    case["negotiable"].append("tooling_eur")
    case["fixed_terms"].pop("tooling_eur")
    case["term_options"]["tooling_eur"] = [0, 7500]
    alpha, beta = threads["sup:alpha"][0], threads["sup:beta"][0]
    alpha["term_sheets"][0]["terms"]["tooling_eur"] = 0
    beta["term_sheets"][0]["terms"].update(lead_time_days=35, tooling_eur=7500)
    alpha["attachments"][0]["text"] = alpha["attachments"][0]["text"].replace("(ppm) 80", "(ppm) 800")
    report = compare_bids(agent, case, threads, "sup:beta", {"tooling_eur": 7500})
    assert report["best_standing"]["supplier_id"] == "sup:alpha"
    assert report["best_standing"]["terms"]["ppm_commitment"] == 800
    match = report["match_rival"]
    assert match["terms"]["unit_price"] < report["best_rival"]["terms"]["unit_price"]
    assert match["estimated_total_cost"] <= report["best_rival"]["estimated_total_cost"]
    assert match["terms"]["tooling_eur"] == 7500


def test_coordinator_walks_when_no_valid_quote_beats_the_actual_alternative():
    agent, case, threads = setup()
    case["buyer"]["alternative"] = {
        "kind": "quote",
        "terms": {"unit_price": 5, "payment_days": 90, "lead_time_days": 35},
    }
    assert agent.close(case, threads) is None  # The bidders may still improve.
    decision = agent.close(case, threads, force=True)
    assert decision["message"]["action"]["type"] == "walk_away"


def test_relationship_estimates_do_not_invent_an_achievable_match_price():
    agent, case, threads = setup()
    case["buyer"].update(category_goal="stabilise", sustainable_margin_pct=5, relationship_eur_per_point=100000)
    threads["sup:beta"][0]["term_sheets"][0]["terms"].update(unit_price=1, lead_time_days=35)
    agent.threads["sup:alpha"].intel.full_cost = 10
    agent.threads["sup:beta"].intel.full_cost = 0.1
    report = compare_bids(agent, case, threads, "sup:alpha")
    assert report["best_rival"]["supplier_id"] == "sup:beta"
    assert report["match_rival"] is None
    assert len(report["best_rival"]["sensitivity_scenarios"]) == 3
    assert report["best_rival"]["supplier_cost_confidence"] == "low"


def test_real_tool_loop_compares_a_new_package_and_reviews_competition(monkeypatch):
    from test_ege_strategy import ScriptedModel, confirm_review, plan, tool

    agent, case, threads = setup()
    agent.llm = True
    sid = "sup:beta"

    def propose(payload):
        result = json.loads(payload["messages"][-1]["content"][0]["content"])
        assert result["best_rival"]["supplier_id"] == "sup:alpha"
        matched = result["match_rival"]
        assert matched["terms"]["lead_time_days"] == 35
        return [tool("submit_move", {"action": "counter", "term_sheets": [matched["terms"]], "plan": plan()})]

    def confirm(payload):
        result = json.loads(payload["messages"][-1]["content"][0]["content"])
        assert result["report"]["rfq_competition"]["best_rival"]["supplier_id"] == "sup:alpha"
        return confirm_review(payload)

    model = ScriptedModel(
        monkeypatch,
        [[tool("compare_rfq_bids", {"terms": {"payment_days": 30, "lead_time_days": 35}})], propose, confirm],
    )
    message = agent.thread_move(case, threads, sid)
    assert len(model.requests) == 3
    brief = json.loads(model.requests[0]["messages"][0]["content"])
    assert brief["rfq_competition"]["best_standing"]["supplier_id"] == "sup:alpha"
    terms = message["term_sheets"][0]["terms"]
    assert terms["lead_time_days"] == 35 and terms["payment_days"] == 30
    assert total_cost(case, terms, {"ppm_commitment": 80}) <= 22016


def test_parallel_rfq_waits_for_a_later_better_bid_and_awards_current_first_sheet():
    _, case, threads = setup()
    threads["sup:beta"][0]["term_sheets"][0]["terms"].update(unit_price=15, lead_time_days=35)
    first_ready = threading.Event()

    class AuctionAgent(EgeAgent):
        def __init__(self):
            super().__init__()
            self.llm = True

        def ask_agent(self, case, threads, sid, rule, arguments):
            if sid == "sup:alpha":
                first_ready.set()
            elif not any(message.get("from") == "buyer" for message in threads[sid]):
                assert first_ready.wait(1)
                return Move(
                    action="counter",
                    term_sheets=[{"unit_price": 9, "payment_days": 30, "lead_time_days": 35}],
                    plan=Plan(goal="Test a competitive conditional package"),
                )
            return Move(action="accept", plan=Plan(goal="Preserve this quote for the coordinated award"))

    class Auction:
        session_id, done = "local-rfq", None

        def open(self, case_id):
            return case, copy.deepcopy(threads)

        def send(self, sid, message):
            assert "action" not in message  # A worker must not award before the other bidder responds.
            assert sid == "sup:beta"
            return quote("beta-improved", 9, "agreed", payment_days=30, lead_time_days=35)

        def close(self, sid, message):
            assert sid == "sup:beta"
            assert message["action"] == {"type": "accept", "term_sheet_id": "offer:beta-improved-0"}
            return {"deal": True, "supplier_id": sid}

    result = play_case(Auction(), case["case_id"], AuctionAgent())
    assert result["deal"] and result["supplier_id"] == "sup:beta"
