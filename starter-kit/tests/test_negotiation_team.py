"""Preparation DAG, live council integration, and bounded parallel execution. No network."""

import json
import threading
import time

import pytest
from test_unified import fixture

from arena_kit.cost import must_haves_ok, total_cost
from csee.agents.unified import UnifiedSingleAgent
from csee.negotiation import engine, preparation, strategy

SOURCE = "We have spare capacity and can trade faster payment for price and a longer delivery window."


def proof():
    return {
        "source": "doc:unseen",
        "quote": "We have spare capacity",
        "interpretation": "Capacity may support competition",
    }


def request():
    return {**proof(), "terms": {"payment_days": 14, "lead_time_days": 35}}


def dossier():
    return {"sup:alpha": {"sources": {"doc:unseen": SOURCE}, "claims": {}, "profile": {}}}


def test_four_specialists_are_parallel_then_rehearsal_then_lead():
    _, case, _ = fixture()
    barrier, lock, completed = threading.Barrier(4), threading.Lock(), set()

    def complete(system, user):
        role = system.split("ROLE: ", 1)[1].split(".", 1)[0]
        if role in preparation.SPECIALISTS:
            barrier.wait(timeout=1)
            with lock:
                completed.add(role)
            return json.dumps({"findings": [proof()], "requests": [request()]})
        if role in ("supplier_advocate", "negotiation_planner"):
            assert set(preparation.SPECIALISTS) <= completed
            with lock:
                completed.add(role)
            return json.dumps({"findings": [proof()], "requests": [request()]})
        assert {"supplier_advocate", "negotiation_planner"} <= completed
        return json.dumps({"stance": "competitive", "stance_evidence": [proof()], "requests": [request()]})

    events = []
    briefs = preparation.research(complete, case, dossier(), 3, lambda key, row: events.append((key, row)))
    assert len(events) == 7 and all(row["diagnostic"] == "ok" for _, row in events)
    brief = briefs["sup:alpha"]
    assert brief["stance"] == "competitive"
    assert brief["requests"][0]["terms"] == request()["terms"]
    assert len(brief["reports"]) == 6


def test_one_failed_specialist_and_failed_lead_preserve_grounded_trade():
    _, case, _ = fixture()

    def complete(system, user):
        if system.startswith(("ROLE: counterpart.", "ROLE: preparation_lead.")):
            return "invalid JSON"
        return json.dumps(
            {"findings": [proof()], "requests": [request()], "priorities": ["payment_days"], "claim_kinds": ["index"]}
        )

    evidence = dossier()
    evidence["sup:alpha"]["claims"] = {"E1": {"kind": "index", "text": "Index fell"}}
    briefs = preparation.research(complete, case, evidence, 2, None)
    brief = briefs["sup:alpha"]
    assert brief["diagnostic"] == "JSONDecodeError"
    assert brief["requests"] and brief["priorities"] == ["payment_days"]
    assert brief["stance"] == "balanced"
    assert brief["claim_kinds"] == ["index"]
    assert proof() in brief["hypotheses"]


@pytest.mark.parametrize(
    "bad",
    [
        {**request(), "source": "not-a-source"},
        {**request(), "quote": "This supplier will accept any price"},
        {**request(), "terms": {"unit_price": 0.01}},
        {**request(), "terms": {"payment_days": 999}},
        {**request(), "terms": {"volume_per_year": 999999}},
    ],
)
def test_unsupported_or_illegal_requests_do_not_reach_pricing(bad):
    _, case, _ = fixture()
    assert preparation.trade_requests([bad], case, {"doc:unseen": SOURCE}) == []


def test_model_stance_alone_cannot_change_opening_even_with_a_quote():
    agent, case, threads = fixture()
    sid = "sup:alpha"
    quote = threads[sid][-1]["term_sheets"][0]["terms"]
    ordinary = engine.propose(agent, case, threads, sid, quote, {}, None, 10)
    agent.briefs[sid] = {"stance": "competitive"}
    assert engine.propose(agent, case, threads, sid, quote, {}, None, 10) == ordinary
    agent.briefs[sid]["stance_evidence"] = [proof()]
    stronger = engine.propose(agent, case, threads, sid, quote, {}, None, 10)
    assert stronger == ordinary
    assert must_haves_ok(case, stronger)


def test_combined_trade_is_code_priced_and_keeps_existing_candidate_ids():
    agent, case, threads = fixture()
    sid = "sup:alpha"
    main = {"unit_price": 9, "payment_days": 90, "lead_time_days": 28}
    before = engine.menu(agent, case, threads, sid, main, {}, None)
    after = engine.add_requests(agent, case, threads, sid, before, [request()], {}, None)
    assert after[: len(before)] == before
    combined = next(c for c in after if c["kind"] == "requested_trade" and c["terms"]["payment_days"] == 14)
    assert combined["terms"]["payment_days"] == 14 and combined["terms"]["lead_time_days"] == 35
    assert combined["terms"]["unit_price"] < main["unit_price"]
    assert total_cost(case, combined["terms"]) <= total_cost(case, main) + 0.01


def test_single_strategist_live_request_becomes_a_real_code_priced_sheet():
    calls = []
    source = "We need delivery in forty two days and payment within thirty days."

    def complete(system, user):
        payload = json.loads(user)
        assert system.startswith("ROLE: live_lead.")
        ref = next(k for k, text in payload["live_sources"].items() if source in text)
        calls.append("lead")
        return json.dumps(
            {
                "candidate_id": "C0",
                "alternative_ids": [],
                "claim_ids": [],
                "trade_request": {
                    "terms": {"payment_days": 30, "lead_time_days": 42},
                    "source": ref,
                    "quote": source,
                    "interpretation": "joint request",
                },
            }
        )

    agent, case, threads = fixture(complete)
    threads["sup:alpha"][-1]["body"] = source
    message = agent.thread_move(case, threads, "sup:alpha")
    assert len(message["term_sheets"]) == 1
    terms = message["term_sheets"][0]["terms"]
    assert terms["payment_days"] == 30 and terms["lead_time_days"] == 42
    assert must_haves_ok(case, terms)
    assert calls == ["lead"] and agent.role_counts["ok"] == 1


def test_short_clock_skips_advisers_and_calls_only_lead():
    roles = []

    def complete(system, user):
        roles.append(system.split(".", 1)[0])
        return '{"candidate_id":"C0"}'

    agent, case, threads = fixture(complete)
    agent.turn_deadlines["sup:alpha"] = time.monotonic() + 0.5
    assert agent.thread_move(case, threads, "sup:alpha")
    assert roles == ["ROLE: live_lead"]


def test_parallel_timeout_is_one_stage_budget_not_sum_of_roles():
    release = threading.Event()
    calls = []

    def slow(*args):
        calls.append(True)
        release.wait(1)
        return "{}"

    started = time.monotonic()
    try:
        rows = strategy.parallel(slow, {str(i): ("role", {}) for i in range(4)}, started + 0.04)
        assert len(calls) == 4
        assert all(r["diagnostic"] == "timeout" for r in rows.values())
        assert time.monotonic() - started < 0.15
    finally:
        release.set()


def test_single_call_ablation_remains_available():
    calls = []

    def complete(system, user):
        calls.append(system)
        return '{"candidate_id":"C0"}'

    base, case, threads = fixture()
    from csee.writer import LLMWriter

    agent = UnifiedSingleAgent(writer=LLMWriter(complete))
    agent.prepare(case, threads)
    assert agent.thread_move(case, threads, "sup:alpha")
    assert len(calls) == 1


def test_existing_session_skips_heavy_preparation_before_resume():
    from types import SimpleNamespace

    from csee.runner import play_case

    agent, case, threads = fixture()
    agent.preflight = lambda *_: pytest.fail("An active supplier clock must not wait for preparation")
    for events in threads.values():
        events[-1]["status"], events[-1]["attachments"] = "final_offer", []

    class Table:
        session_id, done = "existing", None
        client = SimpleNamespace(sessions=lambda set_: [{"case_id": case["case_id"], "status": "open"}])

        def __init__(self):
            self.case = case

        def open(self, case_id):
            return case, threads

        def close(self, sid, message):
            return {"deal": message["action"]["type"] == "accept"}

    assert play_case(Table(), case["case_id"], agent)["deal"]


def test_cost_equivalent_delivery_term_is_not_undone():
    agent, case, threads = fixture()
    sid = "sup:alpha"
    quote = threads[sid][-1]["term_sheets"][0]["terms"]
    assert quote["lead_time_days"] == 35
    planned = engine.propose(agent, case, threads, sid, quote, {}, None, 8)
    assert planned["lead_time_days"] == 35  # 28 also costs no delay; preserve the offered structure
