"""Regression cases for the isolated candidate. No hosted arena calls."""

import copy
import json
import time

import pytest
from test_csee_smoke import CASES, opening

from arena_kit.cost import total_cost
from csee import variants
from csee.agent import CseeAgent
from csee.agents.mert import MertAgent


@pytest.fixture
def case():
    return next(c for c in json.loads(CASES.read_text()) if c["case_id"] == "case:P18")


def negotiation(case, previous=5.60, current=5.50, status="open"):
    sid = case["suppliers"][0]
    clause = max((c for c in case["term_options"]["index_clause"] if c), key=lambda c: c["deadband_pct"])
    ours = {"unit_price": 5.49, "payment_days": 90, "contract_months": 24, "index_clause": clause}

    def reply(price, number, status="open"):
        m = opening(case, sid)
        m.update(status=status)
        m["term_sheets"] = [{"term_sheet_id": f"offer:{number}", "terms": {**ours, "unit_price": price}}]
        return m

    threads = {
        sid: [
            reply(6.10, -1),
            {"from": "buyer", "term_sheets": [{"terms": {**ours, "unit_price": 5.37, "index_clause": None}}]},
            reply(previous, 0),
            {"from": "buyer", "term_sheets": [{"terms": ours}]},
            reply(current, 1, status),
        ]
    }
    agent = MertAgent(params=variants.params("v16"))
    agent.prepare(case, threads)
    return agent, threads, sid, ours, reply


def test_open_conceding_supplier_gets_bounded_continuation(case):
    agent, threads, sid, ours, reply = negotiation(case)
    for number, price in enumerate([5.50, 5.495, 5.492]):
        if number:
            threads[sid].append(reply(price, number + 1))
        msg = agent.thread_move(case, threads, sid)
        if number < 2:
            assert msg is not None
            assert msg["term_sheets"][0]["terms"] == ours
            threads[sid].append({**msg, "from": "buyer"})
        else:
            assert msg is None
    assert agent.continuations[sid] == 2


@pytest.mark.parametrize("status", ["final_offer", "agreed"])
def test_final_or_agreed_offer_is_not_pushed(case, status):
    agent, threads, sid, _, _ = negotiation(case, status=status)
    assert agent.p.final_push == 0 and agent.p.push_after_final == 0
    assert agent.thread_move(case, threads, sid) is None


@pytest.mark.parametrize("previous,current", [(5.50, 5.50), (5.49, 5.50), (5.60, 5.49)])
def test_no_continuation_when_stalled_worse_or_our_ask_met(case, previous, current):
    agent, threads, sid, _, _ = negotiation(case, previous, current)
    assert agent.thread_move(case, threads, sid) is None


def test_no_continuation_near_safety_close(case):
    agent, threads, sid, _, _ = negotiation(case)
    agent.cap_at = lambda: time.time() + 20
    assert agent.thread_move(case, threads, sid) is None


def test_stopping_probe_does_not_spend_continuations(case):
    agent, threads, sid, _, _ = negotiation(case)
    theirs = threads[sid][-1]["term_sheets"][0]["terms"]
    for _ in range(3):
        assert not agent.nothing_to_win(case, threads, sid, theirs, {}, 7)
    assert agent.continuations[sid] == 0


def test_restart_preserves_continuation_bound(case):
    agent, threads, sid, ours, reply = negotiation(case)
    for i in range(2):
        threads[sid] += [{"from": "buyer", "term_sheets": [{"terms": copy.deepcopy(ours)}]}, reply(5.50, i + 2)]
    agent.prepare(case, threads)
    assert agent.continuations[sid] == 2
    assert agent.thread_move(case, threads, sid) is None


def test_clause_switch_preserves_explicit_concession_budget(case, monkeypatch):
    agent, threads, sid, ours, _ = negotiation(case)
    before = {**ours, "unit_price": 5.32, "index_clause": None}
    threads[sid][-2]["term_sheets"][0]["terms"] = before
    candidate = {**ours, "unit_price": 5.41}
    monkeypatch.setattr(CseeAgent, "next_terms", lambda *args: candidate)
    result = agent.next_terms(case, threads, sid, candidate, {}, None, 7)
    budget = total_cost(case, {**before, "unit_price": 5.41})
    assert result["unit_price"] < candidate["unit_price"]
    assert total_cost(case, result) <= budget


def test_history_claim_cannot_assert_unknown_should_cost(case):
    case["refs"] = ["cost:unavailable", "po:unavailable-a", "po:unavailable-b"]
    sid = case["suppliers"][0]
    threads = {sid: [opening(case, sid)]}
    base = CseeAgent(params=variants.params("v16"))
    base.prepare(case, threads)
    assert any("leaves clear room" in c.sentence for c in base.threads[sid].intel.claims)
    candidate = MertAgent(params=variants.params("v16"))
    candidate.prepare(case, threads)
    assert not any("leaves clear room" in c.sentence for c in candidate.threads[sid].intel.claims)
    assert any("Please compare" in c.sentence for c in candidate.threads[sid].intel.claims)


def test_infeasible_package_change_does_not_spend_extra(case, monkeypatch):
    from csee import levers

    agent, threads, sid, ours, _ = negotiation(case)
    threads[sid][-2]["term_sheets"][0]["terms"] = {**ours, "index_clause": None}
    monkeypatch.setattr(CseeAgent, "next_terms", lambda *args: ours)
    monkeypatch.setattr(levers, "price_for", lambda *args: None)
    assert agent.next_terms(case, threads, sid, ours, {}, None, 7) is None


def test_actual_sent_main_price_is_retained(case):
    from test_csee_smoke import DATA

    from arena_kit.data import DataPackage

    sid = case["suppliers"][0]
    agent = MertAgent(DataPackage(DATA), params=variants.params("base"))
    threads = {sid: [opening(case, sid)]}
    agent.prepare(case, threads)
    msg = agent.thread_move(case, threads, sid)
    assert msg["term_sheets"][0]["terms"]["index_clause"] is not None
    assert agent.threads[sid].our_prices[-1] == msg["term_sheets"][0]["terms"]["unit_price"]


def test_dialogue_uses_fixed_commitment_and_documented_approval():
    from test_csee_smoke import DATA

    from arena_kit.data import DataPackage
    from csee.agents.mert import MertDialogueAgent
    from csee.writer import LLMWriter

    case = next(c for c in json.loads(CASES.read_text()) if c["case_id"] == "case:P02")
    sid = case["suppliers"][0]
    threads = {sid: [opening(case, sid)]}
    agent = MertDialogueAgent(
        DataPackage(DATA),
        writer=LLMWriter(lambda *_: "Thank you. We propose the attached packages."),
        params=variants.params("v16"),
    )
    agent.prepare(case, threads)
    msg = agent.thread_move(case, threads, sid)
    for body in [msg["body"], msg["_write"]()]:
        assert "6110 for 12 months" in body
        assert "wider forecast is not an additional commitment" in body
        assert "responsible approver" in body
    assert all("volume_per_year" not in sh["terms"] for sh in msg["term_sheets"])


def test_dialogue_does_not_invent_approval_process(case):
    from csee.agents.mert import MertDialogueAgent

    sid = case["suppliers"][0]
    threads = {sid: [opening(case, sid)]}
    agent = MertDialogueAgent(params=variants.params("v16"))
    agent.prepare(case, threads)
    agent.threads[sid].intel.profile = {}
    msg = agent.thread_move(case, threads, sid)
    assert "responsible approver" not in msg["body"]


def test_shared_clause_is_not_removed_and_reconverted(case):
    from csee.agents.mert import MertConsistentAgent

    _, threads, sid, ours, _ = negotiation(case, previous=5.78, current=5.74)
    for m in threads[sid]:
        if m.get("from") == "buyer":
            m["term_sheets"][0]["terms"] = {**ours, "unit_price": 4.40}
    agent = MertConsistentAgent(params=variants.params("v16"))
    agent.prepare(case, threads)
    assert agent.clause_insisted(threads[sid])
    msg = agent.thread_move(case, threads, sid)
    main = msg["term_sheets"][0]["terms"]
    assert main["unit_price"] > 4.40  # the concession survives construction of the final sheets
    assert all(sh["terms"]["index_clause"] for sh in msg["term_sheets"])
