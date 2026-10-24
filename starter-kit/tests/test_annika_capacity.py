"""annika-k, the capacity expert: its first e-mail, its closing, base behaviour elsewhere, and the replay bot's
fit to the two real P10 games. No arena calls; a fake model for the writer."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from test_csee_smoke import CASES, DATA, opening

from arena_kit.cost import total_cost
from arena_kit.data import DataPackage
from csee import agents, variants
from csee.agent import CseeAgent
from csee.agents.annika_capacity import SCHEDULE, AnnikaCapacityAgent
from csee.writer import LLMWriter

P10_QUOTE = """Angebot / Quote offer:70410-0
Offered terms
Unit price (EUR) 32.20
Lead time (days) 54
Volume per year (pcs) 19890
Contract term (months) 12
Our standard terms (apply to everything not stated above)
Quality commitment (ppm) 300
Chargeback per complaint (EUR) 0.00
Terms fixed by your enquiry
Payment terms (days net) 30
"""


@pytest.fixture(scope="module")
def pkg():
    p = DataPackage(DATA)
    p.lookup("")
    return p


def case_of(cid):
    return next(c for c in json.loads(CASES.read_text()) if c["case_id"] == cid)


def p10_opening():
    terms = {"unit_price": 32.2, "lead_time_days": 54, "volume_per_year": 19890, "contract_months": 12}
    return {
        "from": "sales@70410",
        "status": "open",
        "body": "We offer a price of 32.20 per unit for a volume of 19890 pcs per year.",
        "term_sheets": [{"term_sheet_id": "offer:70410-0", "terms": terms}],
        "attachments": [{"name": "quote-offer-70410-0.pdf", "text": P10_QUOTE}],
    }


def reply(status, sheets, n):
    return {
        "from": "sales@70410",
        "status": status,
        "body": "Our offer.",
        "term_sheets": [
            {"term_sheet_id": f"offer:70410-{n}" + ("" if i == 0 else "-a"), "terms": t} for i, t in enumerate(sheets)
        ],
        "attachments": [{"name": "q.pdf", "text": P10_QUOTE}],
    }


def first_move(pkg, writer=None):
    case = case_of("case:P10")
    agent = agents.get("annika-k")(pkg, writer)
    threads = {"sup:70410": [p10_opening()]}
    agent.prepare(case, threads)
    return case, agent, threads, agent.thread_move(case, threads, "sup:70410")


def test_registered_and_v14_by_default(pkg):
    agent = agents.get("annika-k")(pkg)
    assert isinstance(agent, AnnikaCapacityAgent)
    assert agent.p == variants.params("v14")


def test_p10_first_email(pkg):
    case, agent, threads, msg = first_move(pkg)
    sheets = [s["terms"] for s in msg["term_sheets"]]
    # coverage locked in every sheet: need volume (the must-have), the longest contract
    assert all(s["volume_per_year"] == 23400 and s["contract_months"] == 36 for s in sheets)
    # its own standard lead time first (its premium 1.9 EUR/u > our late cost 0.6 EUR/u), our need second
    assert [s["lead_time_days"] for s in sheets] == [54, 42]
    assert sheets[0]["unit_price"] == pytest.approx(28.34)  # 12 % below its opening, above the relationship floor
    assert sheets[0]["unit_price"] < sheets[1]["unit_price"] <= case["buyer"]["current_unit_price"]
    # should-cost (it took it into account), forecast, order history; no delivery attack on a sole source
    kinds = {r.split(":")[0] for r in msg["refs"]}
    assert kinds == {"cost", "fc", "po"}
    assert "fc:340010@2026-09" in msg["refs"]
    assert SCHEDULE in msg["body"] and "breakdown" not in msg["body"].lower()
    assert "23,400 pieces a year for 36 months" in msg["body"]
    assert all(set(s) == set(case["negotiable"]) for s in sheets)


def test_p10_final_offer_alternative_proposed_back_then_accepted(pkg):
    case, agent, threads, msg = first_move(pkg)
    sid = "sup:70410"
    base = {"volume_per_year": 23400, "contract_months": 36}
    threads[sid] += [
        {**msg, "from": "buyer"},
        reply(
            "final_offer",
            [{**base, "unit_price": 33.6, "lead_time_days": 42}, {**base, "unit_price": 31.7, "lead_time_days": 54}],
            1,
        ),
    ]
    back = agent.thread_move(case, threads, sid)
    assert back["term_sheets"][0]["terms"] == {**base, "unit_price": 31.7, "lead_time_days": 54}  # word for word
    threads[sid] += [
        {**back, "from": "buyer"},
        reply("agreed", [{**base, "unit_price": 31.7, "lead_time_days": 54}], 2),
    ]
    assert agent.thread_move(case, threads, sid) is None
    decision = agent.close(case, threads, force=True)
    assert decision["message"]["action"] == {"type": "accept", "term_sheet_id": "offer:70410-2"}


def test_p10_final_offer_standing_is_cheapest_no_push(pkg):
    case, agent, threads, msg = first_move(pkg)
    sid = "sup:70410"
    base = {"volume_per_year": 23400, "contract_months": 36}
    threads[sid] += [
        {**msg, "from": "buyer"},
        reply(
            "final_offer",
            [{**base, "unit_price": 31.4, "lead_time_days": 54}, {**base, "unit_price": 33.3, "lead_time_days": 42}],
            1,
        ),
    ]
    assert agent.thread_move(case, threads, sid) is None  # no push after a final offer
    decision = agent.close(case, threads, force=True)
    assert decision["message"]["action"] == {"type": "accept", "term_sheet_id": "offer:70410-1"}


def test_p10_open_reply_keeps_coverage(pkg):
    case, agent, threads, msg = first_move(pkg)
    sid = "sup:70410"
    threads[sid] += [
        {**msg, "from": "buyer"},
        reply("open", [{"unit_price": 31.7, "lead_time_days": 54, "volume_per_year": 19890, "contract_months": 12}], 1),
    ]
    nxt = agent.thread_move(case, threads, sid)
    assert nxt is not None
    for s in nxt["term_sheets"]:
        assert s["terms"]["volume_per_year"] == 23400 and s["terms"]["contract_months"] == 36
        assert s["terms"]["unit_price"] > 28.34  # conceding, not re-anchoring


def test_p09_must_have_and_avoided_arguments(pkg):
    case = case_of("case:P09")
    sid = case["suppliers"][0]
    op = {
        "from": f"sales@{sid}",
        "status": "open",
        "body": "Our quote.",
        "term_sheets": [
            {
                "term_sheet_id": "offer:x-0",
                "terms": {"unit_price": 16.82, "lead_time_days": 49, "volume_per_year": 13260, "payment_days": 30},
            }
        ],
        "attachments": [],
    }
    threads = {sid: [op]}
    agent = agents.get("annika-k")(pkg)
    agent.prepare(case, threads)
    msg = agent.thread_move(case, threads, sid)
    for s in msg["term_sheets"]:
        assert s["terms"]["lead_time_days"] <= 42 and s["terms"]["volume_per_year"] == 15600
        assert s["terms"]["unit_price"] <= case["buyer"]["current_unit_price"]
    # thin margin and a rising index: its profile says should-cost and index arguments backfire
    assert not any(r.startswith(("cost:", "idx:")) for r in msg["refs"])
    assert any(r.startswith("fc:") for r in msg["refs"])


def test_other_types_play_base_v14(pkg):
    case = case_of("case:P11")
    threads = {s: [opening(case, s)] for s in case["suppliers"]}
    sid = case["suppliers"][0]
    k = agents.get("annika-k")(pkg)
    b = CseeAgent(pkg, None, variants.params("v14"))
    k.prepare(case, threads)
    b.prepare(case, threads)
    mk, mb = k.thread_move(case, threads, sid), b.thread_move(case, threads, sid)
    assert mk["term_sheets"] == mb["term_sheets"] and mk["refs"] == mb["refs"]


def test_llm_writer_keeps_claims_and_schedule(pkg):
    calls = []

    def fake(system, prompt):
        calls.append(prompt)
        return "Dear Ms Zellner,\n\nwe value the partnership.\n\nBest regards\nHollerau Pumpenwerke GmbH, Purchasing"

    case, agent, threads, msg = first_move(pkg, LLMWriter(fake))
    text = msg.pop("_write")()
    assert SCHEDULE in text
    assert "fc:340010@2026-09" in text and "cost:340010" in text  # claim sentences survive verbatim
    assert "WHAT TO STRESS" in "".join(str(c) for c in calls)


def test_p10_bot_reproduces_both_real_games(pkg):
    path = Path(__file__).parents[2] / "experiments" / "capacity" / "p10_bot.py"
    spec = importlib.util.spec_from_file_location("p10_bot", path)
    bot = importlib.util.module_from_spec(spec)
    sys.modules["p10_bot"] = bot
    spec.loader.exec_module(bot)
    from csee.runner import play_case

    for variant, want in (("v1", 0.5703), ("v13", 0.6709)):
        for world in (bot.World(), bot.World(lam=1.0, fc=False, desk=True), bot.World(lam=0.0, beta=1.0)):
            res = play_case(bot.P10Table(world), "case:P10", CseeAgent(pkg, None, variants.params(variant)))
            assert res["score"] == pytest.approx(want, abs=1e-4), (variant, world)
    # the arena's C for the real v13 deal
    t = {"unit_price": 31.7, "lead_time_days": 54, "volume_per_year": 23400, "contract_months": 36}
    assert total_cost(case_of("case:P10"), t, bot.STD_TERMS) == pytest.approx(1527585.6)
