"""realsim: the calibrated supplier simulator. Fast, offline, no model, no data package needed."""

import os
import random

import pytest

from csee import realsim
from csee.realsim import Desk, RealTable, persona_for, replace

# the arena's C_open / C_best of the ten practice cases (from the logged sessions' results)
REAL = {
    "case:P01": (1153779.74, 1096815.78),
    "case:P02": (2282867.49, 2235514.05),
    "case:P03": (4246314.02, 3909043.10),
    "case:P04": (198846.33, 196529.32),
    "case:P05": (305544.96, 223424.17),
    "case:P07": (391027.40, 299241.49),
    "case:P08": (1135887.28, 960309.33),
    "case:P10": (1932492.18, 1328926.89),
    "case:P11": (817578.00, 722500.02),
    "case:P18": (295173.23, 222651.27),
}


@pytest.fixture(scope="module")
def cases():
    return {c["case_id"]: c for c in realsim.cases()}


def sheets(*terms):
    return {"term_sheets": [{"terms": t} for t in terms], "refs": []}


def test_c_open_is_the_arenas(cases):
    for cid, (c_open, _) in REAL.items():
        t = RealTable(cases[cid], None, 0)
        t.open(cid)
        assert abs(t.c_open - c_open) < 1.0, cid


def test_c_best_within_a_few_percent_of_the_room(cases):
    for cid, (c_open, c_best) in REAL.items():
        t = RealTable(cases[cid], None, 0)
        t.open(cid)
        room = c_open - c_best
        assert abs(t.c_best() - c_best) <= 0.07 * room, (cid, t.c_best(), c_best)


def test_leitner_reproduces_the_logged_p07_trajectory(cases):
    """Session 9c9c870e (router, 0.766): our 5.05/5.17/5.24/5.29 @ 90 d / 36 m drew 5.59, 5.49, 5.42, final 5.38."""
    case = cases["case:P07"]
    desk = Desk(case, persona_for(case, "sup:70610", None, random.Random(0)), random.Random(0))
    desk.opening()
    ours = [5.05, 5.17, 5.24, 5.29]
    real = [5.59, 5.49, 5.42, 5.38]
    got, statuses = [], []
    for i, p in enumerate(ours):
        msg = sheets({"unit_price": p, "payment_days": 90, "contract_months": 36})
        if i == 0:
            msg["refs"] = ["fc:360010@2026-09", "sc:70610@2026Q3"]
        r = desk.respond(msg)
        got.append(r["term_sheets"][0]["terms"]["unit_price"])
        statuses.append(r["status"])
    for g, want in zip(got, real, strict=True):
        assert abs(g - want) <= 0.04, (got, real)
    assert statuses[:3] == ["open", "open", "open"] and statuses[3] == "final_offer"
    assert r["term_sheets"][0]["terms"]["payment_days"] == 90  # it adopts our structure
    assert r["term_sheets"][1]["terms"]["payment_days"] == 30  # and offers the same value at its standard


def test_ravensteiner_prices_lead_time_and_goes_final_at_reply_two(cases):
    case = cases["case:P10"]
    desk = Desk(case, persona_for(case, "sup:70410", None, random.Random(0)), random.Random(0))
    desk.opening()
    ours = {"contract_months": 36, "volume_per_year": 23400}
    r1 = desk.respond(sheets({"unit_price": 30.91, "lead_time_days": 42, **ours}))
    main, alt = (s["terms"] for s in r1["term_sheets"])
    assert main["lead_time_days"] == 42 and alt["lead_time_days"] == 54  # its standard, off the option grid
    assert 1.5 <= main["unit_price"] - alt["unit_price"] <= 2.3  # 12 days of lead time ~ EUR 1.90 (33.60 / 31.70)
    r2 = desk.respond(sheets({"unit_price": 31.11, "lead_time_days": 56, **ours}))
    assert r2["status"] == "final_offer"
    assert abs(r2["term_sheets"][0]["terms"]["unit_price"] - 31.5) <= 0.1


def test_claims_cut_once_per_kind_and_are_marked_duplicate(cases):
    case = cases["case:P01"]
    rng = random.Random(0)
    desk = Desk(case, persona_for(case, "sup:70110", None, rng), rng)
    desk.opening()
    r = desk.respond({**sheets({"unit_price": 120.0, "payment_days": 14, "effective_date": "2027-04-01"}),
                      "refs": ["idx:LCI-C@2026-06", "idx:PPI-D351@2026-08", "fc:310010@2026-09", "po:4500001"]})
    results = [c["result"] for c in r["claim_results"]]
    assert results == ["verified", "duplicate", "verified", "verified"]
    assert "took it into account" in r["body"] and "does not change our calculation" in r["body"]
    assert "idx" not in r["body"]  # it names kinds, not IDs


def test_push_after_final_walks_or_agrees_by_persona(cases):
    # Werdenfels (P18) leaves on a counter below its final offer; Donautal (P08) agrees to a 0.5 % push after a step
    for cid, sid, walks in (("case:P18", "sup:70740", True), ("case:P08", "sup:70710", False)):
        case = cases[cid]
        rng = random.Random(1)
        desk = Desk(case, persona_for(case, sid, None, rng), rng)
        desk.opening()
        clause = next(c for c in case["term_options"]["index_clause"] if c and c["deadband_pct"] == 5)
        ours = {"payment_days": 90, "contract_months": 24, "index_clause": clause}
        r = None
        for price in (4.7, 4.9, 5.05, 5.15, 5.2):
            r = desk.respond(sheets({**ours, "unit_price": price}))
            if r["status"] == "final_offer":
                break
        assert r["status"] == "final_offer", cid
        final = r["term_sheets"][0]["terms"]["unit_price"]
        push = desk.respond(sheets({**ours, "unit_price": round(final * 0.995, 2)}))
        assert push["status"] == ("walked_away" if walks else "agreed"), cid


def test_nordmark_walks_when_we_stay_below_its_floor(cases):
    case = cases["case:P02"]
    rng = random.Random(0)
    desk = Desk(case, persona_for(case, "sup:70510", None, rng), rng)
    desk.opening()
    statuses = [desk.respond(sheets({"unit_price": p, "payment_days": 90}))["status"] for p in (352, 354, 355.5, 357)]
    assert statuses[-1] == "walked_away" and "walked_away" not in statuses[:3]
    # and agrees at once to a copper-clause sheet near its floor (the logged 362 @ 90 d, deadband 5: 0.733)
    desk = Desk(case, persona_for(case, "sup:70510", None, rng), rng)
    desk.opening()
    clause = next(c for c in case["term_options"]["index_clause"] if c and c["deadband_pct"] == 5)
    fixed, hedged = {"unit_price": 330.85, "payment_days": 90}, {"unit_price": 362.0, "payment_days": 90}
    r = desk.respond(sheets(fixed, {**hedged, "index_clause": clause}))
    assert r["status"] == "agreed" and r["term_sheets"][0]["terms"]["unit_price"] == 362.0


def test_repeating_our_sheet_is_a_hold_and_our_own_sheet_proposed_back_is_agreed(cases):
    case = cases["case:P11"]
    rng = random.Random(0)
    desk = Desk(case, persona_for(case, "sup:70140", None, rng), rng)
    desk.opening()
    r1 = desk.respond(sheets({"unit_price": 41.36, "ppm_commitment": 300, "chargeback_eur_per_complaint": 0}))
    r2 = desk.respond(sheets({"unit_price": 41.36, "ppm_commitment": 300, "chargeback_eur_per_complaint": 0}))
    assert r2["term_sheets"][0]["terms"]["unit_price"] == r1["term_sheets"][0]["terms"]["unit_price"]
    assert "unchanged" in r2["body"]
    back = desk.respond(sheets(r2["term_sheets"][0]["terms"]))
    assert back["status"] == "agreed"


def test_unseen_suppliers_get_type_priors_and_perturbation(cases):
    p13 = persona_for(cases["case:P13"], "sup:70230", None, random.Random(0))
    p16 = persona_for(cases["case:P16"], "sup:70720", None, random.Random(0))
    assert p13.needs_clause_months is None and p16.needs_clause_months == 24
    assert 0 < p13.floor < p13.opening["unit_price"] and p13.tick == 0.1
    floors = {persona_for(cases["case:P09"], "sup:70220", None, random.Random(s), perturb=True).floor for s in range(4)}
    assert len(floors) == 4
    t = RealTable(cases["case:P09"], None, 3, perturb=True)
    t.open("case:P09")
    assert t.c_open > t.c_best() > 0


def test_opening_mail_is_the_real_one_for_practice_suppliers(cases):
    t = RealTable(cases["case:P02"], None, 0)
    _, threads = t.open("case:P02")
    first = threads["sup:70510"][0]
    assert "CU-NOTATION rose 47.7 %" in first["body"] and first["status"] == "open"
    assert first["term_sheets"][0]["terms"] == {"unit_price": 370.96, "payment_days": 30, "index_clause": None}
    att = first["attachments"][0]
    assert att["name"].startswith("quote") and "Our standard terms" in att["text"]


def test_router_plays_a_case_end_to_end(cases):
    os.environ["ANTHROPIC_API_KEY"] = ""
    from csee.agents.router import resolve
    from csee.runner import play_case

    cls, params = resolve("base/base", None)
    case = cases["case:P04"]
    res = play_case(RealTable(case, None, 0), case["case_id"], cls(None, None, params))
    assert res["deal"] and 0.0 <= res["score"] <= 1.0
    assert res["c_open"] == pytest.approx(REAL["case:P04"][0], abs=1.0)


def test_persona_replace_is_pure():
    p = realsim.PERSONAS["sup:70610"]
    q = replace(p, floor=1.0)
    assert q.floor == 1.0 and p.floor != 1.0
