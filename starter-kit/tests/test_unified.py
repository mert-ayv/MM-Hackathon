"""Unified strategy boundaries. No network, no real model, no arena quota."""

import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_ege_rfq import setup

from arena_kit.cost import closing_terms, must_haves_ok
from csee.agents.unified import UnifiedAgent
from csee.intel import Claim
from csee.localsim import LocalTable
from csee.negotiation import engine, strategy
from csee.runner import play_case
from csee.writer import LLMWriter

CASES = json.loads((Path(__file__).parents[1] / "csee/cases/practice.json").read_text())
HOSTED = {"P01", "P02", "P03", "P04", "P05", "P07", "P08", "P10", "P11", "P18"}


def fixture(complete=None):
    _, case, threads = setup()
    agent = UnifiedAgent(writer=LLMWriter(complete) if complete else None)
    agent.prepare(case, threads)
    return agent, case, threads


@pytest.mark.parametrize(
    "case", [c for c in CASES if c["case_id"].split(":")[-1] in HOSTED], ids=lambda c: c["case_id"]
)
def test_unseen_identifiers_all_types_produce_valid_offers(case):
    case = copy.deepcopy(case)
    case["case_id"] = "case:UNSEEN"
    case["suppliers"] = [f"sup:unknown{i}" for i, _ in enumerate(case["suppliers"])]
    case["parts"], case["refs"], case["facts"] = ["part:unknown"], [], {}
    table = LocalTable(case, None, seed=17)
    _, threads = table.open(case["case_id"])
    agent = UnifiedAgent()
    agent.prepare(case, threads)
    for sid in case["suppliers"]:
        message = agent.thread_move(case, threads, sid)
        if message is None:
            assert agent.threads[sid].ready
            continue
        assert 1 <= len(message["term_sheets"]) <= 3
        for row in message["term_sheets"]:
            assert set(row["terms"]) == set(case["negotiable"])
            assert must_haves_ok(case, row["terms"])
            full = closing_terms(case, row["terms"])
            for field, value in case.get("fixed_terms", {}).items():
                assert full[field] == value


def test_model_can_select_a_priced_trade_but_cannot_change_its_terms():
    seen = []

    def complete(system, user):
        request = json.loads(user)
        if system.startswith("ROLE: reply_analyst."):
            return "{}"
        chosen = next(c for c in request["candidates"] if c["kind"] == "payment_days")
        seen.append(chosen)
        return json.dumps(
            {
                "candidate_id": chosen["id"],
                "terms": {"unit_price": 0.01},
                "paragraph": "We guarantee 999999 units.",
                "claim_ids": ["invented"],
            }
        )

    agent, case, threads = fixture(complete)
    message = agent.thread_move(case, threads, "sup:alpha")
    assert message["term_sheets"][0]["terms"] == seen[0]["terms"]
    assert "999999" not in message["body"]
    assert not message["refs"]
    assert "_write" not in message  # the lead supplies wording; no additional writer call


@pytest.mark.parametrize("response", ["invalid JSON", '{"candidate_id":"missing"}', '{"action":"accept"}'])
def test_invalid_model_output_preserves_deterministic_proposal(response):
    agent, case, threads = fixture(lambda *args: response)
    expected, _, _ = fixture()
    actual = agent.thread_move(case, threads, "sup:alpha")
    default = expected.thread_move(case, threads, "sup:alpha")
    assert actual["term_sheets"] == default["term_sheets"]


def test_timeout_returns_without_late_state_mutation():
    release, entered = threading.Event(), threading.Event()

    def complete(*args):
        entered.set()
        release.wait(2)
        return '{"candidate_id":"C0"}'

    try:
        raw, status = strategy.ask(complete, "system", {}, 0.01)
        assert entered.is_set() and raw is None and status == "timeout"
    finally:
        release.set()


def test_preparation_happens_before_session_opens_and_does_not_spend_model_time_on_close():
    agent, case, threads = fixture()
    order = []

    def preflight(case_file):
        assert case_file == case
        order.append("prepare")

    agent.preflight = preflight

    class Table:
        session_id, done = "offline", None

        def __init__(self):
            self.case = case

        def open(self, case_id):
            order.append("open")
            for events in threads.values():
                events[-1]["status"] = "final_offer"
                events[-1]["attachments"] = []
            return case, threads

        def close(self, sid, message):
            return {"deal": message["action"]["type"] == "accept"}

    play_case(Table(), case["case_id"], agent)
    assert order == ["prepare", "open"]


def test_parallel_threads_reserve_shared_evidence_once():
    agent, case, threads = fixture()
    common = Claim("A verified shared fact (fc:shared).", ["fc:shared"], "forecast")
    for sid in threads:
        agent.turns[sid] = {"claims": {"A0": common}, "claim_ids": ["A0"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        selected = list(pool.map(lambda sid: agent.pick_claims(case, threads, sid), threads))
    assert sum(len(claims) for claims in selected) == 1


def test_grounding_requires_an_exact_existing_source_excerpt():
    sources = {"reply": "We can offer faster payment in exchange for a better price."}
    good = {"source": "reply", "quote": "faster payment in exchange", "interpretation": "payment trade"}
    bad = {"source": "reply", "quote": "we are desperate for cash"}
    assert strategy.grounded([good, bad, {**good, "source": "unknown"}], sources) == [good]


def test_fixed_price_is_preserved_and_no_price_trades_are_generated():
    agent, case, threads = fixture()
    case["negotiable"].remove("unit_price")
    case["fixed_terms"]["unit_price"] = 11
    main = {"payment_days": 60, "lead_time_days": 35}
    rows = engine.menu(agent, case, threads, "sup:alpha", main, {}, None)
    assert len(rows) == 1
    assert "unit_price" not in rows[0]["terms"]
    assert closing_terms(case, rows[0]["terms"])["unit_price"] == 11


def test_alternatives_are_not_awarded_and_final_offer_does_not_trigger_model():
    def forbidden(*args):
        pytest.fail("No model call should be made for a final offer")

    agent, case, threads = fixture(forbidden)
    for events in threads.values():
        events[-1]["status"] = "final_offer"
    chosen = copy.deepcopy(threads["sup:alpha"][-1]["term_sheets"][0])
    chosen["term_sheet_id"] = "offer:alternative"
    chosen["terms"]["unit_price"] = 7
    threads["sup:alpha"][-1]["term_sheets"].append(chosen)
    message = agent.thread_move(case, threads, "sup:alpha")
    assert message["term_sheets"][0]["terms"] == chosen["terms"]
    close = agent.close(case, threads, force=True)
    assert close["message"]["action"].get("term_sheet_id") != "offer:alternative"


def test_rfq_cost_comparison_uses_delivery_and_each_bidders_defaults():
    agent, case, threads = fixture()
    chosen = agent.close(case, threads, force=True)
    assert chosen["supplier_id"] == "sup:alpha"  # higher price, much lower delivery cost


def test_preflight_outputs_are_clamped_and_grounded_and_used_in_the_live_menu():
    def complete(system, user):
        return json.dumps(
            {
                "priorities": ["unit_price", "payment_days", "invented"],
                "claim_kinds": ["invented"],
                "hypotheses": [
                    {
                        "source": "doc:test",
                        "quote": "We need faster payment",
                        "interpretation": "Explore a payment trade",
                    }
                ],
            }
        )

    agent, case, threads = fixture(complete)
    case["facts"] = {"doc:test": {"supplier_id": "sup:alpha", "text": "We need faster payment"}}
    agent.preflight(case)
    agent.prepare(case, threads)
    brief = agent.briefs["sup:alpha"]
    assert brief["priorities"] == ["payment_days"]
    assert brief["claim_kinds"] == []
    assert len(brief["hypotheses"]) == 1
    assert agent.briefs["sup:beta"]["hypotheses"] == []


def test_package_repricing_preserves_supplier_value_across_payment_trade():
    agent, case, threads = fixture()
    sid = "sup:alpha"
    value = agent.value_fn(case, sid, {})
    original = closing_terms(case, {"unit_price": 10, "payment_days": 90, "lead_time_days": 35})
    target = value(original)
    traded = engine.at_value(case, {**original, "payment_days": 14}, target, value, {})
    assert traded["unit_price"] < original["unit_price"]
    assert abs(value(traded) - target) < 0.011


def test_strategy_can_withhold_irrelevant_claims_without_consuming_them():
    agent, case, threads = fixture()
    claim = Claim("This index fell (idx:example).", ["idx:example"], "index")
    agent.turns["sup:alpha"] = {"claims": {"A0": claim}, "claim_ids": [], "explicit_claims": True}
    assert agent.pick_claims(case, threads, "sup:alpha") == []
    assert not agent.used_ids


def test_late_reply_budget_skips_the_model():
    def forbidden(*args):
        pytest.fail("Expired turn must not start a model call")

    agent, case, threads = fixture(forbidden)
    agent.turn_deadlines["sup:alpha"] = time.monotonic() - 1
    assert agent.thread_move(case, threads, "sup:alpha")["term_sheets"]


def test_strategy_uses_bounded_provider_call():
    def complete(*args):
        pytest.fail("Strategy must use the bounded provider entry point")

    seen = []

    def bounded(system, user, budget):
        seen.append(budget)
        return '{"candidate_id":"C0"}'

    complete.bounded = bounded
    raw, status = strategy.ask(complete, "system", {}, 0.5)
    assert raw == {"candidate_id": "C0"} and status == "ok"
    assert len(seen) == 1 and 0 < seen[0] <= 0.5  # queue/serialization time uses the same budget


def test_anthropic_strategy_limits_output_and_retries_without_changing_writer(monkeypatch):
    from types import SimpleNamespace

    import anthropic

    from csee.llm import complete_from_env

    requests, options = [], []

    class Client:
        def __init__(self, **kwargs):
            self.messages = self

        def with_options(self, **kwargs):
            options.append(kwargs)
            return self

        def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(usage=SimpleNamespace(), content=[SimpleNamespace(type="text", text="{}")])

    monkeypatch.setattr(anthropic, "Anthropic", Client)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    complete = complete_from_env()
    complete.bounded("system", "user", 25)
    assert requests[-1]["max_tokens"] == 4096
    assert options == [{"timeout": 24.75, "max_retries": 0}]
    complete("system", "user")
    assert requests[-1]["max_tokens"] == 16000
    assert len(options) == 1


@pytest.mark.parametrize("lookahead", ["missing_field", "alternative"])
def test_protocol_lookahead_does_not_run_or_overwrite_live_council(lookahead):
    calls = []

    def complete(system, user):
        role = system.split("ROLE: ")[1].split(".")[0]
        calls.append(role)
        if role == "live_lead":
            assert calls.count(role) == 1
            return '{"candidate_id":"C0", "claim_ids":[], "alternative_ids":[]}'
        return "{}"

    agent, case, threads = fixture(complete)
    sheets = threads["sup:alpha"][-1]["term_sheets"]
    if lookahead == "missing_field":
        sheets[0]["terms"].pop("lead_time_days")
    else:
        other = copy.deepcopy(sheets[0])
        other["term_sheet_id"] = "offer:alternative"
        other["terms"]["unit_price"] -= 0.1
        sheets.append(other)
    message = agent.thread_move(case, threads, "sup:alpha")
    assert calls.count("live_lead") == 1
    assert len(calls) == 1
    assert message["term_sheets"] == [{"terms": agent.turns["sup:alpha"]["sheets"][0]}]


def test_profile_index_mentions_do_not_blacklist_measured_changes_and_history_is_not_recycled():
    agent, case, threads = fixture()
    sid = "sup:alpha"
    st = agent.threads[sid]
    st.intel.profile["arguments_to_avoid"] = [
        {"argument": "keeping PPI-X", "why": "that index spiked; AS-X is better for us"}
    ]
    index = Claim("AS-X fell 5% in three months.", ["idx:AS-X@a", "idx:AS-X@b"], "index", tag="AS-X")
    history = Claim("Old orders were cheaper.", ["po:1", "po:2"], "history", tag="po")
    recycled = Claim("Other old orders were cheaper.", ["po:3", "po:4"], "history", tag="po")
    dubious = Claim("Complaints averaged 1000 ppm.", ["qn:1", "qn:2"], "scorecard", tag="ppm")
    st.intel.claims = [index, history, recycled, dubious]
    pool = agent.arguments(case, threads, sid)
    assert index in pool.values() and dubious not in pool.values()
    agent.turns[sid] = {"claims": pool, "claim_ids": [], "explicit_claims": False}
    agent.pick_claims(case, threads, sid)
    assert not any(c.kind == "history" for c in agent.arguments(case, threads, sid).values())


def test_truncated_provider_output_is_distinguished_and_never_partially_accepted(caplog):
    from csee.llm import CompletionText

    text = CompletionText('{"candidate_id":"C0"}', stop_reason="max_tokens", output_tokens=4096)
    raw, diagnostic = strategy.ask(lambda *args: text, "system", {}, 1)
    assert raw is None and diagnostic == "output_limit"
    assert "output_tokens=4096" in caplog.text
    raw, diagnostic = strategy.ask(lambda *args: '{"private":', "system", {}, 1)
    assert raw is None and diagnostic == "JSONDecodeError"
    assert "chars=11 pos=11" in caplog.text
    assert '"private"' not in caplog.text
