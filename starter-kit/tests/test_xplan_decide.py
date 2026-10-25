"""Cross-check plan, stream B: xc_push (guarded push after a final offer), xc_hold (hold/repeat discipline),
xc_pace (tick-sized steps, committee-desk pacing). Offline, no network, no LLM; threads mirror logged sessions."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from arena_kit.cost import total_cost
from arena_kit.docs import standard_terms
from csee import xdecide
from csee.agent import CseeAgent, Params

CASES = {c["case_id"]: c for c in json.loads((Path(__file__).parents[1] / "csee/cases/practice.json").read_text())}
DATA = next(
    (p for p in (Path(__file__).parents[1] / "data" / "package", Path(__file__).parents[2] / "data") if p.exists()),
    None,
)
ALL = {"xc_push": True, "xc_hold": True, "xc_pace": True}


@pytest.fixture(scope="module")
def pkg():
    if DATA is None:
        pytest.skip("no data package")
    from arena_kit.data import DataPackage

    p = DataPackage(DATA)
    p.lookup("")
    return p


def sup(sid, status, *sheets, n=[0]):
    n[0] += 1
    return {
        "from": f"sales@{sid}",
        "status": status,
        "body": "Our offer.",
        "attachments": [],
        "term_sheets": [{"term_sheet_id": f"offer:{sid}-{n[0]}-{i}", "terms": dict(t)} for i, t in enumerate(sheets)],
    }


def buyer(*sheets):
    return {"from": "buyer", "body": "Our proposal.", "term_sheets": [{"terms": dict(t)} for t in sheets], "refs": []}


def agent(pkg, **flags):
    return CseeAgent(pkg, params=replace(Params(), **flags))


# ---------- helpers ----------
def test_push_ask_sizes():
    assert xdecide.push_ask(5.40, 0.02, 0.01) == 5.30  # P18: inside the 2 % band, agreed five times
    assert xdecide.push_ask(5.52, 0.008, 0.01) == 5.48  # P07's logged push, agreed
    assert xdecide.push_ask(5.51, 0.008, 0.01) == 5.47
    assert xdecide.push_ask(45.5, 0.008, 0.5) is None  # less than one 0.50 tick: no push (P11 "we already said")
    assert xdecide.push_ask(10.0, 0.02, 0.01) == 9.81  # strictly inside the band, never at its edge
    assert xdecide.push_ask(0, 0.02, 0.01) is None and xdecide.push_ask(5.0, 0, 0.01) is None


def test_tick_of():
    assert xdecide.tick_of([47.0, 46.5, 46.0, 45.5]) == 0.5
    assert xdecide.tick_of([138.55, 139.7, 133.9]) == 0.05
    assert xdecide.tick_of([5.6, 5.5, 5.4]) == 0.1
    assert xdecide.tick_of([372.5, 372.2]) == 0.1
    assert xdecide.tick_of([5.53, 5.51]) == 0.01
    assert xdecide.tick_of([5.5]) == 0.01


def test_desk_authority_from_meeting_notes(pkg):
    assert xdecide.desk_authority(pkg, "sup:70410") == 0.02  # Ravensteiner: "price changes above 2 % need ..."
    assert xdecide.desk_authority(pkg, "sup:70740") == 0.02  # Blankstahl
    assert xdecide.desk_authority(pkg, "sup:70710") is None  # no such note
    assert xdecide.desk_authority(None, "sup:70410") is None


def test_supplier_step_same_and_changed_structure():
    case = CASES["case:P08"]
    ev = [
        sup("sup:70710", "open", {"unit_price": 5.53, "payment_days": 90, "contract_months": 36}),
        buyer({"unit_price": 5.40, "payment_days": 90, "contract_months": 36, "index_clause": None}),
        sup("sup:70710", "final_offer", {"unit_price": 5.51, "payment_days": 90, "contract_months": 36}),
    ]
    assert xdecide.supplier_step(case, ev) == pytest.approx(0.02)
    ev2 = ev[:2] + [sup("sup:70710", "final_offer", {"unit_price": 5.51, "payment_days": 30, "contract_months": 36})]
    step = xdecide.supplier_step(case, ev2)  # structure changed: our C drop as a price equivalent
    c_prev, c_now = total_cost(case, ev[0]["term_sheets"][0]["terms"]), total_cost(case, ev2[2]["term_sheets"][0]["terms"])
    assert (step > 0) == (c_prev > c_now)
    assert xdecide.supplier_step(case, ev[:1]) is None


def test_consecutive_holds_counts_only_its_holds_against_our_moves():
    case = CASES["case:P18"]
    t = {"payment_days": 90, "contract_months": 36, "index_clause": None}
    ev = [
        sup("s", "open", {"unit_price": 6.1, **t}),
        buyer({"unit_price": 5.29, **t}),
        sup("s", "open", {"unit_price": 5.6, **t}),
        buyer({"unit_price": 5.35, **t}),
        sup("s", "open", {"unit_price": 5.5, **t}),
        buyer({"unit_price": 5.37, **t}),
        sup("s", "open", {"unit_price": 5.5, **t}),
        buyer({"unit_price": 5.38, **t}),
        sup("s", "final_offer", {"unit_price": 5.5, **t}),
    ]
    assert xdecide.consecutive_holds(case, ev) == 2  # P18 emre: 5.50 held twice against 5.37 and 5.38
    assert xdecide.consecutive_holds(case, ev[:7]) == 1
    assert xdecide.consecutive_holds(case, ev[:5]) == 0
    # our own repeat: its hold answers ours and does not count
    rep = ev[:5] + [buyer({"unit_price": 5.35, **t}), sup("s", "open", {"unit_price": 5.5, **t})]
    assert xdecide.consecutive_holds(case, rep) == 0


# ---------- xc_push: the logged 12 (P02 / P18 walked, P08 / P07 agreed, P11 same final) ----------
P02_T = {"payment_days": 90, "index_clause": None}
P02_T30 = {"payment_days": 30, "index_clause": None}


def p02_thread():
    s = "sup:70510"
    return [
        sup(s, "open", {"unit_price": 370.96, **P02_T30}),
        buyer({"unit_price": 358.48, **P02_T}, {"unit_price": 351.61, **P02_T30}),
        sup(s, "open", {"unit_price": 373.88, **P02_T}, {"unit_price": 369.76, **P02_T30}),
        buyer({"unit_price": 360.02, **P02_T}, {"unit_price": 353.12, **P02_T30}),
        sup(s, "open", {"unit_price": 373.06, **P02_T}, {"unit_price": 368.95, **P02_T30}),
        buyer({"unit_price": 360.92, **P02_T}, {"unit_price": 354.0, **P02_T30}),
        sup(s, "open", {"unit_price": 372.5, **P02_T}, {"unit_price": 368.4, **P02_T30}),
        buyer({"unit_price": 361.54, **P02_T}, {"unit_price": 354.61, **P02_T30}),
        sup(s, "final_offer", {"unit_price": 372.2, **P02_T}, {"unit_price": 368.1, **P02_T30}),
    ]


def test_push_blocked_after_micro_steps_p02(pkg):
    case, s = CASES["case:P02"], "sup:70510"
    threads = {s: p02_thread()}
    a = agent(pkg, xc_push=True)
    a.prepare(case, threads)
    assert a.thread_move(case, threads, s) is None  # accept its final: no push
    assert a.threads[s].ready and a.threads[s].xb["push"].startswith("xc_push blocked")
    assert "+0.08%" in a.threads[s].xb["push"]


def test_push_blocked_after_hold_p18(pkg):
    case, s = CASES["case:P18"], "sup:70740"
    t = {"payment_days": 90, "contract_months": 36, "index_clause": case["term_options"]["index_clause"][0]}
    threads = {
        s: [
            sup(s, "open", {"unit_price": 6.1, "payment_days": 30, "contract_months": 12, "index_clause": None}),
            buyer({"unit_price": 5.29, **t}),
            sup(s, "open", {"unit_price": 5.6, **t}),
            buyer({"unit_price": 5.35, **t}),
            sup(s, "open", {"unit_price": 5.5, **t}),
            buyer({"unit_price": 5.37, **t}),
            sup(s, "open", {"unit_price": 5.5, **t}),
            buyer({"unit_price": 5.38, **t}),
            sup(s, "final_offer", {"unit_price": 5.5, **t}),
        ]
    }
    a = agent(pkg, xc_push=True)
    a.prepare(case, threads)
    assert a.thread_move(case, threads, s) is None
    assert "hold" in a.threads[s].xb["push"]


def p08_thread(status="final_offer"):
    s = "sup:70710"
    t = {"payment_days": 90, "contract_months": 36, "index_clause": CASES["case:P08"]["term_options"]["index_clause"][0]}
    return [
        sup(s, "open", {"unit_price": 6.05, "payment_days": 30, "contract_months": 12, "index_clause": None}),
        buyer({"unit_price": 5.24, **t}),
        sup(s, "open", {"unit_price": 5.69, **t}),
        buyer({"unit_price": 5.33, **t}),
        sup(s, "open", {"unit_price": 5.58, **t}),
        buyer({"unit_price": 5.37, **t}),
        sup(s, "open", {"unit_price": 5.55, **t}),
        buyer({"unit_price": 5.39, **t}),
        sup(s, "open", {"unit_price": 5.53, **t}),
        buyer({"unit_price": 5.40, **t}),
        sup(s, status, {"unit_price": 5.51, **t}),
    ]


def test_push_fires_after_a_real_step_p08_default_size(pkg):
    case, s = CASES["case:P08"], "sup:70710"
    threads = {s: p08_thread()}
    a = agent(pkg, xc_push=True)
    a.prepare(case, threads)
    msg = a.thread_move(case, threads, s)
    assert msg and msg["term_sheets"][0]["terms"]["unit_price"] == 5.47  # 0.8 % -> smallest cent inside: 0.73 %
    assert msg["term_sheets"][0]["terms"]["payment_days"] == 90  # its own terms, only the price moves
    assert a.threads[s].pushed == 1 and "default 0.8%" in a.threads[s].xb["push"]
    # it answers with the same final: accept at once
    threads[s] += [{**msg, "from": "buyer"}, sup(s, "final_offer", {**threads[s][-1]["term_sheets"][0]["terms"]})]
    assert a.thread_move(case, threads, s) is None and a.threads[s].ready
    assert a.close(case, threads, force=True)["message"]["action"]["type"] == "accept"


def test_push_off_is_todays_behaviour(pkg):
    case, s = CASES["case:P08"], "sup:70710"
    threads = {s: p08_thread()}
    a = agent(pkg)
    a.prepare(case, threads)
    assert a.thread_move(case, threads, s) is None and a.threads[s].ready


def test_push_sized_to_documented_desk_authority(pkg):
    """P07 Leitner (meeting note: 2 %): after a 1.27 % step the push goes inside the band, not 0.8 %."""
    case, s = CASES["case:P07"], "sup:70610"
    t = {"payment_days": 90, "contract_months": 36}
    threads = {
        s: [
            sup(s, "open", {"unit_price": 5.74, "payment_days": 30, "contract_months": 12}),
            buyer({"unit_price": 4.48, **t}),
            sup(s, "open", {"unit_price": 5.59, **t}, {"unit_price": 5.52, "payment_days": 30, "contract_months": 36}),
            buyer({"unit_price": 4.65, **t}),
            sup(s, "final_offer", {"unit_price": 5.52, **t}, {"unit_price": 5.45, "payment_days": 30, "contract_months": 36}),
        ]
    }
    a = agent(pkg, xc_push=True)
    a.prepare(case, threads)
    msg = a.thread_move(case, threads, s)
    assert msg
    ask = msg["term_sheets"][0]["terms"]["unit_price"]
    assert 5.52 * 0.98 < ask <= 5.52 * (1 - 0.02 + xdecide.BAND_MARGIN) + 0.01
    assert "desk authority 2%" in a.threads[s].xb["push"]


def test_push_never_below_full_cost_in_relationship_goal(pkg):
    case, s = CASES["case:P02"], "sup:70510"
    ev = p02_thread()
    ev[-3] = sup(s, "open", {"unit_price": 378.0, **P02_T}, {"unit_price": 374.0, **P02_T30})  # a real step before the final
    threads = {s: ev}
    a = agent(pkg, xc_push=True)
    a.prepare(case, threads)
    a.threads[s].breakdown = {"full_cost": 371.0}  # its own breakdown: full cost just below its final
    msg = a.thread_move(case, threads, s)
    if msg:
        assert msg["term_sheets"][0]["terms"]["unit_price"] >= 371.0
    else:
        assert "full-cost" in a.threads[s].xb["push"]


def test_push_smaller_than_one_tick_is_no_push_p11(pkg):
    case, s = CASES["case:P11"], "sup:70140"
    t = {"ppm_commitment": 300, "chargeback_eur_per_complaint": 0.0}
    threads = {
        s: [
            sup(s, "open", {"unit_price": 47.0, "ppm_commitment": 6400}),
            buyer({"unit_price": 40.34, **t}),
            sup(s, "open", {"unit_price": 46.0, **t}),
            buyer({"unit_price": 40.89, **t}),
            sup(s, "final_offer", {"unit_price": 45.5, **t}),
        ]
    }
    a = agent(pkg, xc_push=True)
    a.prepare(case, threads)
    assert a.thread_move(case, threads, s) is None
    assert "less than one tick (0.5)" in a.threads[s].xb["push"]


def test_push_reaches_routed_agents_that_zero_final_push(pkg):
    """The routed planners / quality menu set final_push=0 in prepare; xc_push still pushes through the gate."""
    from csee import agents, variants

    case, s = CASES["case:P08"], "sup:70710"
    for name, variant in (("mert-plan-meso-raw-dc", "v16a"), ("base-d", "v14a")):
        threads = {s: p08_thread()}
        a = agents.get(name)(pkg, params=replace(variants.params(variant), xc_push=True))
        a.prepare(case, threads)
        assert a.p.final_push == 0.0 or name == "base-d"
        msg = a.thread_move(case, threads, s)
        assert msg and msg["term_sheets"][0]["terms"]["unit_price"] == 5.47, name


# ---------- xc_hold ----------
def test_hold_keeps_price_per_structure_monotone_p04(pkg):
    """P04 round 2 asked 4.39 @ 90 d/36 m after 4.63 for that structure (a reversal: hold + final)."""
    case, s = CASES["case:P04"], "sup:70620"
    threads = {
        s: [
            sup(s, "open", {"unit_price": 4.96, "payment_days": 30, "contract_months": 12}),
            buyer({"unit_price": 4.36, "payment_days": 90, "contract_months": 12}, {"unit_price": 4.63, "payment_days": 90, "contract_months": 36}),
            sup(s, "open", {"unit_price": 4.94, "payment_days": 90, "contract_months": 36}),
        ]
    }
    base = agent(pkg)
    base.prepare(case, threads)
    m0 = base.thread_move(case, threads, s)
    a = agent(pkg, xc_hold=True)
    a.prepare(case, threads)
    m1 = a.thread_move(case, threads, s)
    assert m0 and m1
    for sh in m1["term_sheets"]:
        if sh["terms"]["payment_days"] == 90 and sh["terms"]["contract_months"] == 36:
            assert sh["terms"]["unit_price"] >= 4.63
    assert m0["term_sheets"][0]["terms"]["unit_price"] < 4.63 < m1["term_sheets"][0]["terms"]["unit_price"] + 1e-9


def test_hold_never_resends_an_identical_sheet_set(pkg):
    case, s = CASES["case:P01"], "sup:70110"
    t = {"effective_date": "2027-04-01", "payment_days": 90}
    ours = [{"unit_price": 135.15, **t}, {"unit_price": 130.83, "effective_date": "2027-04-01", "payment_days": 30}]
    threads = {
        s: [
            sup(s, "open", {"unit_price": 138.55, "effective_date": "2026-11-01"}),
            buyer({"unit_price": 134.7, **t}),
            sup(s, "open", {"unit_price": 136.5, **t}),
            buyer(*ours),
            sup(s, "open", {"unit_price": 136.1, **t}),
        ]
    }
    a = agent(pkg, xc_hold=True)
    a.prepare(case, threads)
    std = standard_terms(threads[s])
    theirs = threads[s][-1]["term_sheets"][0]["terms"]
    out = a.xc_hold_sheets(case, s, threads[s], [dict(x) for x in ours], [], theirs, std, None)
    assert out is not None and xdecide.normalized(case, out) != xdecide.normalized(case, ours)
    assert out[0]["unit_price"] >= 135.15 and "xc_hold" in a.threads[s].xb["hold"]
    # a step of one of its ticks (0.05 here) or a new trade sheet, never a lower price for a known structure
    hist = xdecide.our_history(case, threads[s])
    for sh in out:
        k = xdecide.sheet_key(case, sh)
        assert k not in hist or sh["unit_price"] >= hist[k] - 1e-9


def test_hold_after_two_holds_closes_on_its_sheet(pkg):
    case, s = CASES["case:P18"], "sup:70740"
    t = {"payment_days": 90, "contract_months": 36, "index_clause": case["term_options"]["index_clause"][0]}
    threads = {
        s: [
            sup(s, "open", {"unit_price": 6.1, "payment_days": 30, "contract_months": 12, "index_clause": None}),
            buyer({"unit_price": 5.29, **t}),
            sup(s, "open", {"unit_price": 5.6, **t}),
            buyer({"unit_price": 5.35, **t}),
            sup(s, "open", {"unit_price": 5.5, **t}),
            buyer({"unit_price": 5.37, **t}),
            sup(s, "open", {"unit_price": 5.5, **t}),
            buyer({"unit_price": 5.38, **t}),
            sup(s, "open", {"unit_price": 5.5, **t}),
        ]
    }
    a = agent(pkg, xc_hold=True)
    a.prepare(case, threads)
    assert a.thread_move(case, threads, s) is None and a.threads[s].ready
    assert a.close(case, threads, force=True)["message"]["action"]["type"] == "accept"
    b = agent(pkg)
    b.prepare(case, threads)
    assert b.thread_move(case, threads, s) is not None  # today: a third small step


def test_hold_after_one_hold_changes_something_real(pkg):
    case, s = CASES["case:P18"], "sup:70740"
    t = {"payment_days": 90, "contract_months": 36, "index_clause": case["term_options"]["index_clause"][0]}
    threads = {
        s: [
            sup(s, "open", {"unit_price": 6.1, "payment_days": 30, "contract_months": 12, "index_clause": None}),
            buyer({"unit_price": 5.29, **t}),
            sup(s, "open", {"unit_price": 5.6, **t}),
            buyer({"unit_price": 5.35, **t}),
            sup(s, "open", {"unit_price": 5.5, **t}),
            buyer({"unit_price": 5.37, **t}),
            sup(s, "open", {"unit_price": 5.5, **t}),
        ]
    }
    a = agent(pkg, xc_hold=True)
    a.prepare(case, threads)
    a.threads[s].intel.claims = []  # no new evidence to add: the sheets must change
    msg = a.thread_move(case, threads, s)
    assert msg
    last = xdecide.normalized(case, threads[s][-2]["term_sheets"])
    assert xdecide.normalized(case, msg["term_sheets"]) != last
    tick = xdecide.tick_of(xdecide.their_prices(threads[s]))
    main = msg["term_sheets"][0]["terms"]
    structures = {xdecide.sheet_key(case, sh["terms"]) for sh in msg["term_sheets"]}
    moved_a_tick = xdecide.sheet_key(case, main) == xdecide.sheet_key(case, t) and main["unit_price"] >= 5.37 + tick - 1e-9
    new_structure = any(k not in xdecide.our_history(case, threads[s]) for k in structures)
    assert moved_a_tick or new_structure


# ---------- xc_pace ----------
def test_pace_step_at_least_one_tick(pkg):
    case, s = CASES["case:P11"], "sup:70140"
    t = {"ppm_commitment": 300, "chargeback_eur_per_complaint": 0.0}
    threads = {
        s: [
            sup(s, "open", {"unit_price": 47.0, "ppm_commitment": 6400}),
            buyer({"unit_price": 39.24, **t}),
            sup(s, "open", {"unit_price": 46.5, **t}),
        ]
    }
    a = agent(pkg, xc_pace=True)
    a.prepare(case, threads)
    ours = a.xc_pace_price(case, s, threads[s], {"unit_price": 39.26, **t}, {"unit_price": 46.5, **t})
    assert ours["unit_price"] == pytest.approx(39.74)  # 0.02 -> one 0.50 tick
    same = a.xc_pace_price(case, s, threads[s], {"unit_price": 40.0, **t}, {"unit_price": 46.5, **t})
    assert same["unit_price"] == 40.0  # a real step stays


def test_pace_within_one_percent_by_third_mail_for_committee_desk(pkg):
    case, s = CASES["case:P10"], "sup:70410"  # Ravensteiner: 2 % committee note
    t = {"lead_time_days": 54, "volume_per_year": 23400, "contract_months": 36}
    threads = {
        s: [
            sup(s, "open", {"unit_price": 32.2, "lead_time_days": 54, "volume_per_year": 19890, "contract_months": 12}),
            buyer({"unit_price": 28.34, **t}),
            sup(s, "open", {"unit_price": 32.0, **t}),
            buyer({"unit_price": 30.7, **t}),
            sup(s, "open", {"unit_price": 31.8, **t}),
        ]
    }
    a = agent(pkg, xc_pace=True)
    a.prepare(case, threads)
    ours = a.xc_pace_price(case, s, threads[s], {"unit_price": 30.9, **t}, {"unit_price": 31.8, **t})
    assert 31.8 * 0.99 <= ours["unit_price"] < 31.8
    # from further than two of its bands away (gap 8.8 %) no jump: rounds, not jumps
    far = {s: threads[s][:3] + [buyer({"unit_price": 29.0, **t}), sup(s, "open", {"unit_price": 31.8, **t})]}
    b = agent(pkg, xc_pace=True)
    b.prepare(case, far)
    assert b.xc_pace_price(case, s, far[s], {"unit_price": 29.6, **t}, {"unit_price": 31.8, **t})["unit_price"] == 29.6
    # a desk without the note: unchanged
    case2, s2 = CASES["case:P08"], "sup:70710"
    t2 = {"payment_days": 90, "contract_months": 36, "index_clause": None}
    threads2 = {
        s2: [
            sup(s2, "open", {"unit_price": 6.05, "payment_days": 30, "contract_months": 12, "index_clause": None}),
            buyer({"unit_price": 5.24, **t2}),
            sup(s2, "open", {"unit_price": 5.69, **t2}),
            buyer({"unit_price": 5.33, **t2}),
            sup(s2, "open", {"unit_price": 5.58, **t2}),
        ]
    }
    b = agent(pkg, xc_pace=True)
    b.prepare(case2, threads2)
    assert b.xc_pace_price(case2, s2, threads2[s2], {"unit_price": 5.37, **t2}, {"unit_price": 5.58, **t2})["unit_price"] == 5.37


def test_switches_off_first_moves_identical(pkg):
    """With every switch off nothing changes; with them on, the anchor (no history) is the same e-mail too."""
    for cid in ("case:P04", "case:P08", "case:P11"):
        case = CASES[cid]
        s = case["suppliers"][0]
        opening = {"unit_price": round(case["buyer"]["fallback_unit_price"] * 1.06, 2)}
        for f in case["negotiable"]:
            if f != "unit_price" and case.get("term_options", {}).get(f):
                opening[f] = case["term_options"][f][0]
        threads = {s: [sup(s, "open", opening)]}
        a, b = agent(pkg), agent(pkg, **ALL)
        a.prepare(case, threads)
        b.prepare(case, threads)
        ma, mb = a.thread_move(case, threads, s), b.thread_move(case, threads, s)
        assert ma == mb, cid
