"""Free tests for the unified agent (starter-kit/unified): every practice case file with synthetic suppliers,
plus the guard, the risk-sharing clause sheet and the ledger parameters. No arena calls, no quota."""

import json
from pathlib import Path

import pytest

from arena_kit.data import DataPackage
from unified import agent as ua
from unified.__main__ import describe_params

CASES = Path(__file__).parents[1] / "unified" / "cases" / "practice.json"
DATA = next(
    (p for p in (Path(__file__).parents[1] / "data" / "package", Path(__file__).parents[2] / "data") if p.exists()),
    Path(__file__).parents[1] / "data" / "package",
)
pytestmark = pytest.mark.skipif(not CASES.exists() or not DATA.exists(), reason="no case files or data package")


def opening(case, sid, price_up=1.06, body="Our quote.", status="open", n=0):
    """A supplier quote: every negotiable field at its first option, price above the current one."""
    b = case["buyer"]
    price = (b.get("current_unit_price") or b["fallback_unit_price"]) * price_up
    terms = {"unit_price": round(price, 2)}
    for f in case["negotiable"]:
        if f != "unit_price" and case.get("term_options", {}).get(f):
            terms[f] = case["term_options"][f][0]
    return {
        "from": f"sales@{sid}",
        "status": status,
        "body": body,
        "term_sheets": [{"term_sheet_id": f"offer:{sid}-{n}", "terms": terms}],
        "attachments": [],
    }


@pytest.fixture(scope="module")
def pkg():
    p = DataPackage(DATA)
    p.lookup("")
    return p


@pytest.fixture(scope="module")
def cases():
    return {c["case_id"]: c for c in json.loads(CASES.read_text())}


def test_every_practice_case(pkg, cases):
    for case in cases.values():
        agent = ua.UnifiedAgent(pkg)
        threads = {s: [opening(case, s)] for s in case["suppliers"]}
        agent.prepare(case, threads)
        for sid in case["suppliers"]:
            msg = agent.thread_move(case, threads, sid)
            assert msg is None or msg["term_sheets"], case["case_id"]
            if msg:
                for ts in msg["term_sheets"]:
                    assert set(ts["terms"]) == set(case["negotiable"]), (case["case_id"], ts)
                reply = opening(case, sid, price_up=1.03, n=1)
                threads[sid] += [{**msg, "from": "buyer"}, reply]
                agent.thread_move(case, threads, sid)
        decision = agent.close(case, threads, force=True)
        assert decision["message"]["action"]["type"] in ("accept", "walk_away"), case["case_id"]


def test_type_settings_applied(pkg, cases):
    for cid, key, want in [("case:P05", "sticky_terms", False), ("case:P07", "anchor_leverage", 0.0),
                           ("case:P08", "max_claims", 1), ("case:P01", "anchor_leverage", 0.22)]:
        case = cases[cid]
        agent = ua.UnifiedAgent(pkg)
        agent.prepare(case, {s: [opening(case, s)] for s in case["suppliers"]})
        assert getattr(agent.p, key) == want, cid
    assert not hasattr(ua.Params(), "final_push") and not hasattr(ua.Params(), "push_after_final")


def test_never_counters_a_final_offer(pkg, cases):
    case = cases["case:P18"]
    sid = case["suppliers"][0]
    agent = ua.UnifiedAgent(pkg)
    threads = {sid: [opening(case, sid)]}
    msg = agent.thread_move(case, threads, sid)
    assert msg
    threads[sid] += [{**msg, "from": "buyer"}, opening(case, sid, 1.04, status="final_offer", n=1)]
    assert agent.thread_move(case, threads, sid) is None
    assert agent.threads[sid].ready


def test_walk_guard_holds_without_move(pkg, cases):
    case = cases["case:P02"]
    sid = case["suppliers"][0]
    agent = ua.UnifiedAgent(pkg)
    threads = {sid: [opening(case, sid)]}
    msg = agent.thread_move(case, threads, sid)
    threads[sid] += [{**msg, "from": "buyer"}, opening(case, sid, 1.05, n=1)]
    msg = agent.thread_move(case, threads, sid)
    assert msg  # it moved: we keep negotiating
    hold = opening(case, sid, 1.05, body="We have reviewed your offer and hold our Angebot.", n=2)
    threads[sid] += [{**msg, "from": "buyer"}, hold]
    assert agent.thread_move(case, threads, sid) is None
    assert agent.threads[sid].ready
    # the same words with a price step are not a hold
    assert not ua.UnifiedAgent.holding([opening(case, sid, 1.05), opening(case, sid, 1.04, body=hold["body"])])


def test_risk_clause_on_blamed_index(pkg, cases):
    case = cases["case:P16"]  # raw material, no relationship goal
    sid = case["suppliers"][0]
    body = "PPI-C241 rose 12.3 % in twelve months and is 38 % of our cost."
    agent = ua.UnifiedAgent(pkg)
    msg = agent.thread_move(case, {sid: [opening(case, sid, body=body)]}, sid)
    clauses = [s["terms"] for s in msg["term_sheets"] if s["terms"].get("index_clause")]
    assert clauses and clauses[0]["index_clause"]["series"] == "PPI-C241"
    assert clauses[0]["index_clause"]["deadband_pct"] == 5  # widest deadband: the cheapest clause for us
    assert "index clause on PPI-C241" in msg["body"]


def test_no_clause_that_squeezes_a_stabilise_supplier(pkg, cases):
    case = cases["case:P02"]  # stabilise: a clause sheet below its cost costs us the relationship charge
    sid = case["suppliers"][0]
    body = "CU-NOTATION rose 47.7 % in twelve months and is 20 % of our cost."
    agent = ua.UnifiedAgent(pkg)
    msg = agent.thread_move(case, {sid: [opening(case, sid, body=body)]}, sid)
    assert not any(s["terms"].get("index_clause") for s in msg["term_sheets"])


def test_claim_filter(pkg, cases):
    for case in cases.values():
        agent = ua.UnifiedAgent(pkg)
        agent.prepare(case, {s: [opening(case, s)] for s in case["suppliers"]})
        for st in agent.threads.values():
            assert all(c.kind in agent.p.claim_kinds for c in st.intel.claims), case["case_id"]


def test_ledger_params_show_type_settings():
    p = describe_params()
    assert p["by_type"] == ua.TYPE_SETTINGS and p["defaults"]["anchor_leverage"] == 0.22
