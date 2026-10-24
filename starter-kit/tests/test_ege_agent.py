"""Offline checks of the ege agent's guards: no model call, no arena, no quota. Moves are written by hand
here; check_move() must refuse invalid ones and apply() must turn valid ones into safe messages."""

import json
import re
from pathlib import Path

import pytest

from arena_kit.agents.llm import ID_RE
from arena_kit.cost import total_cost
from arena_kit.data import DataPackage
from csee import variants
from csee.agents.ege import EgeAgent, Move, Plan, check_move, clean_text, family
from csee.intel import Claim

ROOT = Path(__file__).parents[1]
CASES = ROOT / "csee" / "cases" / "practice.json"
DATA = next((p for p in (ROOT / "data" / "package", ROOT.parent / "data") if p.exists()), ROOT / "data" / "package")
pytestmark = pytest.mark.skipif(not CASES.exists() or not DATA.exists(), reason="no case files or data package")


@pytest.fixture(scope="module")
def pkg():
    p = DataPackage(DATA)
    p.lookup("")
    return p


def case(case_id):
    return next(c for c in json.loads(CASES.read_text()) if c["case_id"] == case_id)


def reply(sid, price, n, status="open", body="Our offer.", **terms):
    return {
        "from": f"sales@{sid[4:]}",
        "status": status,
        "body": body,
        "term_sheets": [{"term_sheet_id": f"offer:{sid[4:]}-{n}", "terms": {"unit_price": price, **terms}}],
        "attachments": [],
    }


def p05(pkg, status="open"):
    c = case("case:P05")
    threads = {
        "sup:70210": [reply("sup:70210", 36.0, 0, status, payment_days=30, lead_time_days=35)],
        "sup:70240": [reply("sup:70240", 31.5, 0, "open", payment_days=30, lead_time_days=35)],
        "sup:70250": [reply("sup:70250", 38.5, 0, "open", payment_days=30, lead_time_days=35)],
    }
    agent = EgeAgent(pkg, params=variants.params("v9"))
    agent.prepare(c, threads)
    agent.plans = {s: Plan(goal="Find a competitive, achievable deal").model_dump() for s in threads}
    return agent, c, threads


def decide(agent, c, threads, sid, **raw):
    arguments = agent.arguments(c, threads, sid)
    move, errors = check_move(c, {"action": "counter", **raw}, arguments)
    assert errors is None, errors
    return agent.apply(c, threads, sid, move, agent.rule_move(c, threads, sid), arguments)


HARD = {"unit_price": 25.0, "payment_days": 90, "lead_time_days": 35}


# ---------- the typed move ----------
def test_free_text_allows_questions_but_not_figures_or_leaks():
    for bad in (
        "We can pay 90 days.",
        "A price of EUR 30 works.",
        "Our budget is tight.",
        "See idx:X@2026-01.",
        "This is our limit.",
    ):
        assert clean_text(bad, 60) == "", bad
    assert clean_text("Could earlier payment help you improve the price?", 60)
    assert clean_text("An alternative with a clause could help us share risk.", 60)
    assert clean_text("Thank you for the constructive exchange so far.", 60)


def test_invalid_moves_are_refused_with_reasons(pkg):
    agent, c, threads = p05(pkg)
    args = agent.arguments(c, threads, "sup:70210")
    _, err = check_move(c, {"action": "counter", "term_sheets": [{"unit_price": 30, "tooling_eur": 0}]}, args)
    assert "not negotiable" in err
    _, err = check_move(c, {"action": "counter", "term_sheets": [HARD], "argument_keys": ["A99"]}, args)
    assert "not in the verified list" in err
    _, err = check_move(c, {"action": "counter"}, args)
    assert "at least one term sheet" in err
    _, err = check_move(c, {"action": "bargain"}, args)
    assert err
    _, err = check_move(c, {"action": "ready", "plan": {"anchor": 30, "target": 28, "walk_away": 35}}, args)
    assert err


def test_one_argument_per_data_family():
    a = Claim("Your complaint rate was 712 ppm (sc:1@2026Q3).", ["sc:1@2026Q3"], "scorecard")
    b = Claim("Your on-time delivery was 83.3% (sc:1@2026Q2).", ["sc:1@2026Q2"], "scorecard")
    c = {"case_id": "x", "negotiable": ["unit_price"]}
    _, err = check_move(
        c, {"action": "counter", "term_sheets": [{"unit_price": 1}], "argument_keys": ["A1", "A2"]}, {"A1": a, "A2": b}
    )
    assert family(a) == family(b) == "scorecard" and "same data family" in err


# ---------- what apply() sends ----------
def test_softer_than_rules_is_a_strategy_choice(pkg):
    agent, c, threads = p05(pkg)
    rule = agent.rule_move(c, threads, "sup:70210")
    msg = decide(agent, c, threads, "sup:70210", term_sheets=[{"unit_price": 34.0, "payment_days": 90}])
    assert msg["term_sheets"][0]["terms"]["unit_price"] == 34.0
    assert msg["term_sheets"][0]["terms"] != rule["terms"]


def test_harder_than_rules_is_kept(pkg):
    agent, c, threads = p05(pkg)
    msg = decide(agent, c, threads, "sup:70210", term_sheets=[HARD])
    assert msg["term_sheets"][0]["terms"]["unit_price"] == 25.0


def test_holding_supplier_is_evidence_not_a_policy_override(pkg):
    agent, c, threads = p05(pkg)
    threads["sup:70210"] += [
        {"from": "buyer", "term_sheets": [{"terms": HARD}], "body": "x"},
        reply("sup:70210", 36.0, 1, body="Our offer remains unchanged.", payment_days=30, lead_time_days=35),
    ]
    rule = agent.rule_move(c, threads, "sup:70210")
    msg = decide(agent, c, threads, "sup:70210", term_sheets=[{**HARD, "unit_price": 20.0}])
    assert msg["term_sheets"][0]["terms"]["unit_price"] == 20.0
    assert msg["term_sheets"][0]["terms"] != rule["terms"]


def test_stopping_while_rules_counter_is_allowed(pkg):
    agent, c, threads = p05(pkg)
    args = agent.arguments(c, threads, "sup:70210")
    for action in ("ready", "accept"):
        move, _ = check_move(c, {"action": action}, args)
        result = agent.apply(c, threads, "sup:70210", move, agent.rule_move(c, threads, "sup:70210"), args)
        assert result is None  # RFQ awards wait for the other supplier threads and the coordinator.
        assert agent.threads["sup:70210"].ready


def test_rfq_accept_after_agreed_preserves_the_quote_for_coordinator_comparison(pkg):
    agent, c, threads = p05(pkg, status="agreed")
    args = agent.arguments(c, threads, "sup:70210")
    move, _ = check_move(c, {"action": "accept"}, args)
    msg = agent.apply(c, threads, "sup:70210", move, None, args)
    assert msg is None and agent.threads["sup:70210"].ready
    assert agent.close(c, threads) is None  # Two bidders still have room to negotiate.
    award = agent.close(c, threads, force=True)
    assert award["supplier_id"] == "sup:70240"
    assert award["message"]["action"]["term_sheet_id"] == "offer:70240-0"


def test_alternative_sheets_can_trade_cost_for_acceptability(pkg):
    agent, c, threads = p05(pkg)
    msg = decide(agent, c, threads, "sup:70210", term_sheets=[HARD, {**HARD, "unit_price": 30.0}])
    costs = [total_cost(c, s["terms"]) for s in msg["term_sheets"]]
    assert len(costs) == 2 and costs[1] > costs[0]


def test_email_states_every_sheet_and_only_given_ids(pkg):
    agent, c, threads = p05(pkg)
    args = agent.arguments(c, threads, "sup:70210")
    key = next(iter(args))
    msg = decide(
        agent,
        c,
        threads,
        "sup:70210",
        term_sheets=[HARD, {**HARD, "unit_price": 24.5, "payment_days": 30}],
        argument_keys=[key],
        opening="We value working with you.",
        closing="We look forward to your reply.",
    )
    body = msg["body"]
    for s in msg["term_sheets"]:
        assert f"{s['terms']['unit_price']:.2f}" in body
    assert args[key].sentence in body
    assert {m.group(0) for m in ID_RE.finditer(body)} <= set(args[key].ids)
    assert "We value working with you." in body and body.rstrip().endswith("Purchasing")


def test_index_clause_is_written_out(pkg):
    c = case("case:P02")
    sid = c["suppliers"][0]
    threads = {sid: [reply(sid, 370.96, 0, payment_days=30, index_clause=None)]}
    agent = EgeAgent(pkg, params=variants.params("v9"))
    agent.prepare(c, threads)
    clause = [o for o in c["term_options"]["index_clause"] if o and o["deadband_pct"] == 5][0]
    body = EgeAgent.render(
        c,
        threads[sid],
        Move(action="counter", term_sheets=[{}]),
        [],
        [
            {"unit_price": 352.0, "payment_days": 90, "index_clause": None},
            {"unit_price": 350.0, "payment_days": 90, "index_clause": clause},
        ],
        False,
    )
    assert "fixed price without index clause" in body and re.search(r"price clause on CU-NOTATION.*5 % deadband", body)


def test_lone_supplier_can_be_pushed_after_a_final_offer(pkg):
    c = case("case:P07")
    sid = c["suppliers"][0]
    threads = {
        sid: [reply(sid, 5.45, 4, "final_offer", body="This is our final offer.", payment_days=90, contract_months=36)]
    }
    agent = EgeAgent(pkg, params=variants.params("v9"))
    agent.prepare(c, threads)
    agent.plans[sid] = Plan(goal="Explore a final conditional trade").model_dump()
    msg = decide(agent, c, threads, sid, term_sheets=[{"unit_price": 5.0, "payment_days": 90}])
    assert msg["term_sheets"][0]["terms"]["unit_price"] == 5.0
