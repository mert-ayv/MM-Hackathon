"""Offline checks of the ege agent's guards: no model call, no arena, no quota. The agent's decisions are
written by hand here; apply() must turn them into safe messages (or refuse them)."""

import json
from pathlib import Path

import pytest

from arena_kit.cost import total_cost
from arena_kit.data import DataPackage
from csee import variants
from csee.agents.ege import EgeAgent

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


def reply(sid, price, n, status="open", **terms):
    t = {"unit_price": price, **terms}
    return {
        "from": f"sales@{sid[4:]}",
        "status": status,
        "body": "Our offer.",
        "term_sheets": [{"term_sheet_id": f"offer:{sid[4:]}-{n}", "terms": t}],
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
    return agent, c, threads


def decide(agent, c, threads, sid, **d):
    return agent.apply(c, threads, sid, {"_arguments": agent.arguments(c, threads, sid), **d},
                       agent.rule_move(c, threads, sid))


def test_softer_than_rules_becomes_the_rule_ask(pkg):
    agent, c, threads = p05(pkg)
    rule = agent.rule_move(c, threads, "sup:70210")
    soft = {"unit_price": 34.0, "payment_days": 90, "lead_time_days": 35}
    msg = decide(agent, c, threads, "sup:70210", action="counter", term_sheets=[soft], email_body="Hello")
    assert msg["term_sheets"][0]["terms"] == rule["terms"]


def test_harder_than_rules_is_kept(pkg):
    agent, c, threads = p05(pkg)
    hard = {"unit_price": 25.0, "payment_days": 90, "lead_time_days": 35}
    msg = decide(agent, c, threads, "sup:70210", action="counter", term_sheets=[hard], email_body="Hello")
    assert msg["term_sheets"][0]["terms"]["unit_price"] == 25.0


def test_stopping_while_rules_counter_falls_back(pkg):
    agent, c, threads = p05(pkg)
    for action in ("ready", "accept", "walk_away"):
        assert decide(agent, c, threads, "sup:70210", action=action) is False


def test_accept_after_agreed_is_the_standing_offer(pkg):
    agent, c, threads = p05(pkg, status="agreed")
    msg = decide(agent, c, threads, "sup:70210", action="accept")
    assert msg == {"action": {"type": "accept", "term_sheet_id": "offer:70210-0"}}


def test_alternative_sheets_never_cost_more_than_the_main(pkg):
    agent, c, threads = p05(pkg)
    hard = {"unit_price": 25.0, "payment_days": 90, "lead_time_days": 35}
    dear = {"unit_price": 30.0, "payment_days": 14, "lead_time_days": 35}
    msg = decide(agent, c, threads, "sup:70210", action="counter", term_sheets=[hard, dear], email_body="Hi")
    std = {}
    costs = [total_cost(c, s["terms"], std) for s in msg["term_sheets"]]
    assert len(costs) == 1 or all(x <= costs[0] for x in costs[1:])


def test_unknown_ids_are_scrubbed_and_sheet_stated(pkg):
    agent, c, threads = p05(pkg)
    hard = {"unit_price": 25.0, "payment_days": 90, "lead_time_days": 35}
    body = "Prices fell (idx:MADE-UP@2026-01).\n\nHollerau Pumpenwerke GmbH, Purchasing"
    msg = decide(agent, c, threads, "sup:70210", action="counter", term_sheets=[hard], email_body=body)
    assert "MADE-UP" not in msg["body"]
    assert "25.00" in msg["body"] and msg["body"].rstrip().endswith("Purchasing")


def test_lone_supplier_push_is_capped(pkg):
    c = case("case:P07")
    sid = c["suppliers"][0]
    threads = {sid: [reply(sid, 5.45, 4, "final_offer", payment_days=90, contract_months=36)]}
    agent = EgeAgent(pkg, params=variants.params("v9"))
    agent.prepare(c, threads)
    far = {"unit_price": 5.0, "payment_days": 90, "contract_months": 36}
    msg = decide(agent, c, threads, sid, action="counter", term_sheets=[far], email_body="Hi")
    assert msg["term_sheets"][0]["terms"]["unit_price"] >= round(5.45 * 0.99, 2)
    assert decide(agent, c, threads, sid, action="counter", term_sheets=[far], email_body="Hi") is None  # once only
