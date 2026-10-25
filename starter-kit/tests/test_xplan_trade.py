"""Cross-check stream C (Params.xc_trade): the term exchange-rate engine (levers.trade_plan) and its hook in CseeAgent.

Pure arithmetic over the practice case files plus the suppliers' own paired sheets from the audits (P10 lead time,
P18 payment, P01 cash-short, P11 chargeback). No arena, no network, no model."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_csee_smoke import CASES, DATA, opening  # noqa: E402

from arena_kit.cost import total_cost  # noqa: E402
from arena_kit.data import DataPackage  # noqa: E402
from csee import agents, levers, variants  # noqa: E402
from csee.agents import router  # noqa: E402

CASE = {c["case_id"]: c for c in json.loads(CASES.read_text())}
P10_THEIRS = {"unit_price": 32.2, "lead_time_days": 54, "volume_per_year": 19890, "contract_months": 12}
P10_OURS = {"unit_price": 30.91, "volume_per_year": 23400, "contract_months": 36, "lead_time_days": 42}  # base v14s R1
P10_EST = {"interest_rate": 0.08, "ppm": 300, "standard": {"payment_days": 30, "incoterm": "DAP", "lead_time_days": 54}}
P10_LEAD_PRIOR = levers.LEAD_VALUE_PRIOR * 32.2  # ~0.097 EUR per day: a capacity-short supplier


def reply(sid, sheets, n, status="open"):
    return {
        "from": f"sales@{sid}",
        "status": status,
        "body": "Our offer.",
        "term_sheets": [{"term_sheet_id": f"offer:{sid}-{n}-{i}", "terms": t} for i, t in enumerate(sheets)],
        "attachments": [],
    }


# ---------- the supplier's own exchange rates ----------
def test_revealed_slopes_from_paired_sheets():
    ev = [
        reply(
            "70410", [{**P10_THEIRS, "unit_price": 33.6, "lead_time_days": 42}, {**P10_THEIRS, "unit_price": 31.7}], 1
        )
    ]
    slopes = levers.revealed_slopes(ev, CASE["case:P10"]["negotiable"])
    slope, lo, hi = slopes["lead_time_days"]
    assert (lo, hi) == (42, 54) and slope * 31.7 == pytest.approx(-1.9 / 12)  # it charges 0.158 EUR per day faster
    ev = [
        reply(
            "70740",
            [
                {"unit_price": 5.6, "payment_days": 90, "contract_months": 24},
                {"unit_price": 5.5, "payment_days": 30, "contract_months": 24},
            ],
            2,
        )
    ]
    slope, lo, hi = levers.revealed_slopes(ev, CASE["case:P18"]["negotiable"])["payment_days"]
    assert (lo, hi) == (30, 90) and slope * 360 == pytest.approx(0.109, abs=0.001)  # ~11 % a year
    # sheets that differ in two terms, or in a non-numeric one, reveal nothing
    ev = [
        reply(
            "x",
            [
                {"unit_price": 5.6, "payment_days": 90, "contract_months": 36},
                {"unit_price": 5.5, "payment_days": 30, "contract_months": 24},
            ],
            3,
        )
    ]
    assert levers.revealed_slopes(ev, CASE["case:P18"]["negotiable"]) == {}


def test_revealed_rate_holds_inside_its_range_prior_beyond():
    """P10: 0.158/day revealed between 42 and 54 days; 56 days is beyond what it quoted: the smaller of revealed and
    prior counts. A rate of the opposite sign to the prior (or no prior) counts for nothing beyond the range."""
    case, ours = CASE["case:P10"], {**P10_OURS}
    slopes = {"lead_time_days": (-1.9 / 12 / 30.91, 42, 54)}  # as a share of the price
    v42 = levers.its_term_value(case, ours, None, "lead_time_days", 42, 54, P10_EST, slopes, P10_LEAD_PRIOR)
    v56 = levers.its_term_value(case, ours, None, "lead_time_days", 56, 54, P10_EST, slopes, P10_LEAD_PRIOR)
    assert v42 == pytest.approx(-1.9) and v56 == pytest.approx(2 * P10_LEAD_PRIOR)
    assert levers.its_term_value(case, ours, None, "lead_time_days", 56, 54, P10_EST, slopes, 0.0) == 0.0
    # P18: 11 % revealed for 30-90 days says nothing about prepayment at 14 days: our own 8 % (neutral) applies there
    case18 = CASE["case:P18"]
    t = {"unit_price": 6.1, "payment_days": 90, "contract_months": 24, "index_clause": None}
    est = {"interest_rate": 0.08, "ppm": 0, "standard": {}}
    slopes = {"payment_days": (0.1 / 60 / 6.1, 30, 90)}
    assert levers.its_term_value(case18, t, None, "payment_days", 14, 30, est, slopes, 0) == pytest.approx(
        6.1 * 0.08 * 16 / 360
    )
    assert levers.its_term_value(case18, t, None, "payment_days", 90, 30, est, slopes, 0) == pytest.approx(-0.1)


# ---------- the plan per case (audit numbers) ----------
def test_p10_sells_two_lead_days_when_capacity_short():
    """Ravensteiner: a lead day is worth ~0.16/unit to it, costs us 2,400/day = 0.05/unit. Engine: the longest option
    (56 d) with a cut between our cost (0.10) and its value (0.19) - the record is 31.00 @ 56 d."""
    case = CASE["case:P10"]
    plan = levers.trade_plan(case, P10_OURS, P10_THEIRS, None, P10_EST, {}, P10_LEAD_PRIOR)
    r = plan["lead_time_days"]
    assert (r["ref"], r["base"], r["choice"]) == (54, 42, 56)
    mine, its = next((m, i) for v, m, i in r["rows"] if v == 56)
    assert mine == pytest.approx(2 * 2400 / 46800) and its == pytest.approx(2 * P10_LEAD_PRIOR)
    assert mine < r["cut"] < its
    # 42 days: worth -1.16 to it (prior), saves us 0.62: a bad buy; 35 days worse still
    assert r["rows"][0][0] == 35 and all(its - mine < 0 for v, mine, its in r["rows"] if v < 54)
    # coverage is never traded for price
    assert set(plan) == {"lead_time_days"}


def test_p10_without_capacity_pressure_keeps_our_lead_time():
    case = CASE["case:P10"]
    plan = levers.trade_plan(case, P10_OURS, P10_THEIRS, None, P10_EST, {}, 0.0)
    r = plan["lead_time_days"]
    assert r["choice"] == 42 and r["cut"] == 0.0


def test_p18_payment_neutral_until_revealed_then_its_30_days():
    """Werdenfels prices payment at ~11 %/yr vs our 8 %: 90 days (base's choice) costs it more than it saves us. With
    no evidence payment is a wash (keep base); once its paired sheets show the rate, take its 30 days. 14 days is
    beyond what it quoted: not chosen on a rate it never confirmed."""
    case = CASE["case:P18"]
    ours = {"unit_price": 4.75, "payment_days": 90, "contract_months": 24, "index_clause": None}
    theirs = {"unit_price": 6.1, "payment_days": 30, "contract_months": 12, "index_clause": None}
    est = {"interest_rate": 0.08, "ppm": 0, "standard": {"payment_days": 30, "incoterm": "DAP"}}
    neutral = levers.trade_plan(case, ours, theirs, None, est, {}, 0.0)
    assert neutral["payment_days"]["choice"] == 90 and neutral["payment_days"]["cut"] == 0.0
    revealed = levers.trade_plan(case, ours, theirs, None, est, {"payment_days": (0.1 / 60 / 5.5, 30, 90)}, 0.0)
    r = revealed["payment_days"]
    assert r["choice"] == 30 and r["cut"] == 0.0  # back to its own term: nothing to pay for
    assert dict((v, round(i - m, 4)) for v, m, i in r["rows"])[90] < 0  # 90 d: a net loss between us


def test_p01_cash_short_sells_14_days():
    """Brandlhuber asks for 10-day payment (cash-short, money at 14 %): 14 days is worth 0.86/unit to it and costs us
    0.49; sell it for a cut in between. The later start date saves us more than it costs it: taken at the asked
    price."""
    case = CASE["case:P01"]
    ours = {"unit_price": 134.0, "effective_date": "2027-04-01", "payment_days": 90}
    theirs = {"unit_price": 138.55, "effective_date": "2026-11-01", "payment_days": 30}
    est = {"interest_rate": 0.14, "ppm": 712, "standard": {"payment_days": 30, "incoterm": "FCA", "lead_time_days": 42}}
    plan = levers.trade_plan(case, ours, theirs, None, est, {}, 0.0)
    pay = plan["payment_days"]
    assert pay["choice"] == 14
    mine, its = next((m, i) for v, m, i in pay["rows"] if v == 14)
    assert 0 < mine < pay["cut"] < its
    date = plan["effective_date"]
    assert date["choice"] == "2027-04-01" and date["cut"] == 0.0


@pytest.mark.parametrize("cid", ["case:P02", "case:P07", "case:P08"])
def test_payment_is_neutral_at_our_own_rate(cid):
    """Suppliers that price money like we do (the P02/P07/P08 bots revealed 7-9 %/yr): no payment move, no cut."""
    case = CASE[cid]
    theirs = {f: (case["term_options"][f][0] if case["term_options"].get(f) else None) for f in case["negotiable"]}
    theirs = {k: v for k, v in theirs.items() if v is not None}
    theirs["unit_price"] = (case["buyer"].get("current_unit_price") or 1.0) * 1.06
    theirs["payment_days"] = 30
    ours = levers.best_terms(case, {**theirs, "unit_price": theirs["unit_price"] * 0.9})
    est = {"interest_rate": case["buyer"]["interest_rate"], "ppm": 0, "standard": {"payment_days": 30}}
    plan = levers.trade_plan(case, ours, theirs, None, est, {}, 0.0)
    assert plan["payment_days"]["choice"] == ours["payment_days"] and plan["payment_days"]["cut"] == 0.0


def test_p11_chargeback_is_dear_for_it_and_cheap_for_us():
    """Kalwisz runs at 2,376 ppm: EUR 150 per complaint costs it 0.36/unit and is worth 0.045/unit to us at 300 ppm.
    The engine never buys it (keeps 0) and prices it as a sell lever; a 300 ppm commitment is free to it and saves us
    2.7/unit against its 6,400 ppm standard: taken at the asked price."""
    case = CASE["case:P11"]
    std = {"payment_days": 60, "incoterm": "FCA", "chargeback_eur_per_complaint": 0, "ppm_commitment": 6400}
    ours = {"unit_price": 41.36, "ppm_commitment": 300, "chargeback_eur_per_complaint": 0}
    theirs = {"unit_price": 47.0}
    est = {"interest_rate": 0.14, "ppm": 2376, "standard": std}
    plan = levers.trade_plan(case, ours, theirs, std, est, {}, 0.0)
    cb = plan["chargeback_eur_per_complaint"]
    assert cb["ref"] == 0 and cb["choice"] == 0
    mine, its = next((m, i) for v, m, i in cb["rows"] if v == 150)
    assert its == pytest.approx(-2376e-6 * 150) and mine == pytest.approx(-300e-6 * 150)
    assert its < mine < 0  # its loss exceeds our gain: a chargeback is ours to sell, never to buy
    assert plan["ppm_commitment"]["choice"] == 300 and plan["ppm_commitment"]["cut"] == 0.0


# ---------- the agent hook ----------
@pytest.fixture(scope="module")
def pkg():
    if not DATA.exists():
        pytest.skip("no data package")
    p = DataPackage(DATA)
    p.lookup("")
    return p


def p10_agent(pkg, flag):
    case = CASE["case:P10"]
    agent = agents.get("base-d")(pkg, params=replace(variants.params("v14s"), xc_trade=flag))  # the capacity route
    threads = {"sup:70410": [reply("70410", [P10_THEIRS], 0)]}
    agent.prepare(case, threads)
    return case, agent, threads


def test_switch_off_is_todays_behaviour(pkg):
    case, agent, threads = p10_agent(pkg, False)
    msg = agent.thread_move(case, threads, "sup:70410")
    st = agent.threads["sup:70410"]
    assert [s["terms"] for s in msg["term_sheets"]] == [P10_OURS] and st.xc_plan is None and st.xc_cut == 0.0
    assert "trade" not in st.why


def test_switch_on_sells_lead_time_and_concedes_on_its_scale(pkg):
    case, agent, threads = p10_agent(pkg, True)
    msg = agent.thread_move(case, threads, "sup:70410")
    st = agent.threads["sup:70410"]
    sheets = [s["terms"] for s in msg["term_sheets"]]
    main = sheets[0]
    assert main["lead_time_days"] == 56 and main["volume_per_year"] == 23400 and main["contract_months"] == 36
    cut = round(P10_OURS["unit_price"] - main["unit_price"], 2)
    assert 0.10 <= cut <= 0.20 and st.xc_cut == pytest.approx(cut)
    # the alternative shows the exchange: 42 days back, at a price that is not dearer for us
    alt = next(s for s in sheets[1:] if s["lead_time_days"] == 42)
    assert alt["unit_price"] > main["unit_price"] and total_cost(case, alt) <= total_cost(case, main)
    # round 2: it answers 31.70 @ 54 d. Our step is the same 0.20 as without the engine (on its scale), not 0.20 less
    threads["sup:70410"] += [
        {**msg, "from": "buyer"},
        reply("70410", [{**P10_THEIRS, "unit_price": 31.7, "volume_per_year": 23400, "contract_months": 36}], 1),
    ]
    msg2 = agent.thread_move(case, threads, "sup:70410")
    main2 = msg2["term_sheets"][0]["terms"]
    assert main2["lead_time_days"] == 56 and round(main2["unit_price"] - main["unit_price"], 2) == 0.20


ROUTED = {
    "price_increase": "case:P01",
    "renewal": "case:P03",
    "rfq": "case:P05",
    "raw_material": "case:P08",
    "capacity": "case:P10",
    "quality": "case:P11",
    "bundling": "case:P07",
}


@pytest.mark.parametrize("ctype", sorted(router.ROUTES))
def test_routed_agents_reach_the_engine(pkg, ctype):
    """Every ROUTES slot (the agents router-x plays) runs the engine on its first move."""
    case = CASE[ROUTED[ctype]]
    cls, params = router.resolve(router.ROUTES[ctype], None)
    agent = cls(pkg, None, replace(params, xc_trade=True))
    threads = {s: [opening(case, s)] for s in case["suppliers"]}
    agent.prepare(case, threads)
    sid = case["suppliers"][0]
    msg = agent.thread_move(case, threads, sid)
    assert msg and msg["term_sheets"]
    st = agent.threads[sid]
    assert st.xc_base is not None, st.why  # the hook ran
    assert st.xc_plan is not None  # every practice type has a tradeable term with options
    for ts in msg["term_sheets"]:
        assert set(ts["terms"]) == set(case["negotiable"])
