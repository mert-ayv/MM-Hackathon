"""Free smoke test: the csee agent's moves on every practice case file, with synthetic suppliers.
No arena calls, no quota. Case files are committed in csee/cases/."""

import json
from pathlib import Path

import pytest

from arena_kit.data import DataPackage
from csee import agents, variants

CASES = Path(__file__).parents[1] / "csee" / "cases" / "practice.json"
# the unpacked package (`arena data`), else the copy committed at the repo root
DATA = next(
    (p for p in (Path(__file__).parents[1] / "data" / "package", Path(__file__).parents[2] / "data") if p.exists()),
    Path(__file__).parents[1] / "data" / "package",
)
pytestmark = pytest.mark.skipif(not CASES.exists() or not DATA.exists(), reason="no case files or data package")


def opening(case, sid, price_up=1.06):
    """A supplier quote: every negotiable field at its first option, price above the current one."""
    b = case["buyer"]
    price = (b.get("current_unit_price") or b["fallback_unit_price"]) * price_up
    terms = {"unit_price": round(price, 2)}
    for f in case["negotiable"]:
        if f != "unit_price" and case.get("term_options", {}).get(f):
            terms[f] = case["term_options"][f][0]
    return {"from": f"sales@{sid}", "status": "open", "body": "Our quote.",
            "term_sheets": [{"term_sheet_id": f"offer:{sid}-0", "terms": terms}], "attachments": []}


@pytest.fixture(scope="module")
def pkg():
    p = DataPackage(DATA)
    p.lookup("")
    return p


@pytest.mark.parametrize("agent_name", list(agents.AGENTS))
@pytest.mark.parametrize("variant", list(variants.VARIANTS))
def test_every_practice_case(pkg, agent_name, variant):
    for case in json.loads(CASES.read_text()):
        agent = agents.get(agent_name)(pkg, params=variants.params(variant))
        threads = {s: [opening(case, s)] for s in case["suppliers"]}
        agent.prepare(case, threads)
        for sid in case["suppliers"]:
            msg = agent.thread_move(case, threads, sid)
            assert msg is None or msg["term_sheets"], case["case_id"]
            if msg:
                for ts in msg["term_sheets"]:
                    assert set(ts["terms"]) == set(case["negotiable"]), (case["case_id"], ts)
                # supplier answers with a small step: the agent must produce a second move or be ready
                reply = opening(case, sid, price_up=1.03)
                reply["term_sheets"][0]["term_sheet_id"] = f"offer:{sid}-1"
                threads[sid] += [{**msg, "from": "buyer"}, reply]
                agent.thread_move(case, threads, sid)
        decision = agent.close(case, threads, force=True)
        assert decision["message"]["action"]["type"] in ("accept", "walk_away"), case["case_id"]


def test_router_routes():
    """Every slot names a real agent (not the router itself) and variant; each case type gets its slot."""
    from csee.agents.router import FALLBACK, ROUTES, RouterAgent, resolve

    for route in [*ROUTES.values(), FALLBACK]:
        assert route.partition("/")[0] != "router", route
        resolve(route, variants.params("base"))  # SystemExit on an unknown agent or variant
    for case in json.loads(CASES.read_text()):
        router = RouterAgent(params=variants.params("base"))
        router._route(case)
        name = ROUTES.get(case["type"], FALLBACK).partition("/")[0]
        assert type(router.inner) is agents.get(name), case["case_id"]
