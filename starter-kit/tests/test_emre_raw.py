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


def test_raw_spreads_arguments_and_pushes_after_a_final_offer(pkg, cases):
    case = cases["case:P08"]
    sid = case["suppliers"][0]
    agent, threads = EmreAgent(pkg), {sid: [opening(case, sid)]}
    agent.prepare(case, threads)
    assert agent.p.final_push > 0
    per_round = []
    for _ in range(3):
        per_round.append(len(agent.pick_claims(case, threads, sid)))
        threads[sid] += [{"from": "buyer", "term_sheets": [{"terms": {"unit_price": 1.0}}]}, opening(case, sid)]
    assert per_round[0] == 1 and per_round[1] == 1  # one per e-mail, so round 2 still argues


def test_index_falls_are_recent_disjoint_falls(pkg, cases):
    from csee.agents.emre import RECENT_MONTHS, index_falls
    from csee.intel import _month_minus

    falls = index_falls(pkg, cases["case:P08"], "AS-14404", limit=5)
    ids = [i for c in falls for i in c.ids]
    assert falls and len(ids) == len(set(ids))
    assert all("-" in c.sentence and c.kind == "index" for c in falls)
    latest = max(i for i in pkg.ids("idx:AS-14404@") if "@" in i).split("@")[1]
    assert all(c.ids[1].split("@")[1] > _month_minus(latest, RECENT_MONTHS) for c in falls)
