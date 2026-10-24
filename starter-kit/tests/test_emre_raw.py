"""Emre's raw-material agent: base's opening and price, plus the widest-deadband clause as a priced
alternative; every other case type plays exactly like base. Free, no arena calls."""

import json

import pytest

from arena_kit.cost import total_cost
from arena_kit.data import DataPackage
from csee.agent import CseeAgent
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


@pytest.mark.parametrize("case_id", ["case:P08", "case:P16", "case:P18"])
@pytest.mark.parametrize("with_data", [True, False])
def test_raw_keeps_base_price_and_adds_the_widest_clause(pkg, cases, case_id, with_data):
    case, p = cases[case_id], pkg if with_data else None
    ours, theirs = first_move(EmreAgent(p), case), first_move(CseeAgent(p), case)
    main, alt = ours["term_sheets"][0]["terms"], ours["term_sheets"][1]["terms"]
    assert main == theirs["term_sheets"][0]["terms"]  # base's opening offer
    widest = max(c["deadband_pct"] for c in case["term_options"]["index_clause"] if c)
    assert alt["index_clause"]["deadband_pct"] == widest
    assert total_cost(case, alt) < total_cost(case, main)  # an alternative worth taking for us
    assert "includes an index clause" in ours["body"]


def test_other_case_types_untouched(pkg, cases):
    case = next(c for c in cases.values() if c["type"] != "raw_material")
    assert first_move(EmreAgent(pkg), case) == first_move(CseeAgent(pkg), case)
