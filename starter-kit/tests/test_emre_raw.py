"""Emre's raw-material agent: the data layer reads any supplier's tables, and without data the agent
plays exactly like base (the Live Final brings suppliers practice never shows). Free, no arena calls."""

import json

import pytest

from arena_kit.data import DataPackage
from csee.agent import CseeAgent
from csee.agents import emre_data
from csee.agents.emre import EmreAgent

from test_csee_smoke import CASES, DATA, opening

pytestmark = pytest.mark.skipif(not CASES.exists() or not DATA.exists(), reason="no case files or data package")


@pytest.fixture(scope="module")
def pkg():
    return DataPackage(DATA)


@pytest.fixture(scope="module")
def cases():
    return {c["case_id"]: c for c in json.loads(CASES.read_text())}


def first_move(agent, case):
    sid = case["suppliers"][0]
    threads = {s: [opening(case, s)] for s in case["suppliers"]}
    agent.prepare(case, threads)
    return agent.thread_move(case, threads, sid)


def test_data_layer_reads_contracts_history_and_orders(pkg):
    assert emre_data.current_clause(pkg, "sup:70710") == {"series": "AS-14404", "material_share": 0.45}
    assert emre_data.typical_give(pkg, "sup:70740") == pytest.approx(3.3, abs=0.01)
    bench = emre_data.benchmark(pkg, "part:370010", "sup:70740")
    assert bench["price"] == 5.45 and len(bench["ids"]) == 2 and all(i.startswith("po:") for i in bench["ids"])


def test_data_layer_is_safe_for_strangers(pkg):
    assert emre_data.current_clause(pkg, "sup:99999") is None
    assert emre_data.benchmark(pkg, "part:999999", "sup:99999") is None
    assert 0 <= emre_data.typical_give(pkg, "sup:99999") <= 6  # the all-supplier median, from the data
    assert emre_data.typical_give(None, "sup:70710") is None


def test_raw_opening_comes_from_data_and_leads_with_the_status_quo_clause(pkg, cases):
    case = cases["case:P18"]
    msg = first_move(EmreAgent(pkg), case)
    main, alt = (s["terms"] for s in msg["term_sheets"][:2])
    plan = EmreAgent(pkg)
    plan.prepare(case, {s: [opening(case, s)] for s in case["suppliers"]})
    assert main["unit_price"] <= plan.plans[case["suppliers"][0]]["anchor"]
    assert main["index_clause"]["deadband_pct"] == max(
        c["deadband_pct"] for c in case["term_options"]["index_clause"] if c
    )
    assert alt["index_clause"] is None  # the fixed price is the alternative
    assert any(r.startswith("po:") for r in msg["refs"])  # the cheaper order price from another supplier
    assert "fixed price without index clause" in msg["body"]


@pytest.mark.parametrize("case_id", ["case:P08", "case:P16", "case:P18"])
def test_without_data_emre_plays_like_base(cases, case_id):
    case = cases[case_id]
    ours, theirs = first_move(EmreAgent(None), case), first_move(CseeAgent(None), case)
    assert ours["term_sheets"][0] == theirs["term_sheets"][0]


def test_other_case_types_untouched(pkg, cases):
    case = next(c for c in cases.values() if c["type"] != "raw_material")
    assert first_move(EmreAgent(pkg), case) == first_move(CseeAgent(pkg), case)
