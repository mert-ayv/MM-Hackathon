"""Cross-check plan, stream D: xc_relfloor (relationship floor + fixed track first) and xc_rfq (RFQ ratchet).
Offline, no network, no model. Both switches off = today's behaviour (checked by the smoke test and a byte-identical
replay); here the routed agents are driven through the logged P02 / P05 openings with the switches on."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from arena_kit.cost import total_cost
from arena_kit.data import DataPackage
from csee import variants
from csee.agent import FIXED_REFUSED, CseeAgent, Params
from csee.agents.router import ROUTES, resolve

CASES = {c["case_id"]: c for c in json.loads((Path(__file__).parents[1] / "csee/cases/practice.json").read_text())}
DATA = next(
    (p for p in (Path(__file__).parents[1] / "data" / "package", Path(__file__).parents[2] / "data") if p.exists()),
    Path(__file__).parents[1] / "data" / "package",
)
pytestmark = pytest.mark.skipif(not DATA.exists(), reason="no data package")

# the logged practice openings (runs/sessions): P02 Nordmark blames copper; P05 three bidders, Hrvelec at 52 days
P02_OPENING = {
    "from": "sales@70510", "status": "open", "attachments": [],
    "body": "Dear Sir or Madam,\n\nWe offer a price of EUR 370.96 per unit, Zahlungsziel 30 days net, no Preisgleitklausel.\n"
    "Regarding our cost structure, CU-NOTATION rose 47.7 % in twelve months and is 20 % of our cost.\n",
    "term_sheets": [{"term_sheet_id": "offer:70510-0", "terms": {"unit_price": 370.96, "payment_days": 30, "index_clause": None}}],
}
P05_OPENINGS = {
    "sup:70210": {"unit_price": 36.0},
    "sup:70240": {"unit_price": 31.5, "lead_time_days": 52},
    "sup:70250": {"unit_price": 38.5},
}


def reply(sid, terms, status="open", body="Our counter-offer.", n=1):
    return {"from": f"sales@{sid[4:]}", "status": status, "body": body, "attachments": [],
            "term_sheets": [{"term_sheet_id": f"offer:{sid[4:]}-{n}", "terms": dict(terms)}]}


@pytest.fixture(scope="module")
def pkg():
    p = DataPackage(DATA)
    p.lookup("")
    return p


def routed(pkg, case, **flags):
    cls, params = resolve(ROUTES[case["type"]], variants.params("base"))
    return cls(pkg, params=replace(params, **flags))


def prices(msg):
    return [(s["terms"]["unit_price"], s["terms"].get("payment_days"), s["terms"].get("index_clause")) for s in msg["term_sheets"]]


# ---------------------------------------------------------------- item 5: relationship floor + fixed track first
def floors_ok(agent, case, sid, msg, threads):
    from arena_kit.docs import standard_terms

    std = standard_terms(threads[sid])
    sup = agent.rel_estimate(case, sid, std)
    out = []
    for s in msg["term_sheets"]:
        floor = agent.rel_floor_price(case, sid, s["terms"], std, sup)
        out.append((s["terms"]["unit_price"], floor))
    return out


def test_p02_first_message_no_sheet_below_floor_and_no_clause(pkg):
    case, sid = CASES["case:P02"], "sup:70510"
    threads = {sid: [P02_OPENING]}
    on = routed(pkg, case, xc_relfloor=True)
    on.prepare(case, threads)
    msg = on.thread_move(case, threads, sid)
    assert msg and msg["term_sheets"]
    checks = floors_ok(on, case, sid, msg, threads)
    assert all(floor is not None and price >= floor - 1e-9 for price, floor in checks), checks
    assert not any(s["terms"].get("index_clause") for s in msg["term_sheets"]), prices(msg)
    # the floor sits below the supplier's estimated full cost (should-cost x 0.98 = 367.45) but far above today's anchor
    main = msg["term_sheets"][0]["terms"]
    assert 355 < main["unit_price"] < 367.45
    # today (switch off): the planner anchors 12 % below the opening value and the copper clause is in message 1
    off = routed(pkg, case)
    off.prepare(case, threads)
    msg0 = off.thread_move(case, threads, sid)
    assert msg0["term_sheets"][0]["terms"]["unit_price"] < 340
    assert any(s["terms"].get("index_clause") for s in msg0["term_sheets"])


def test_p02_clause_opens_after_a_hold(pkg):
    case, sid = CASES["case:P02"], "sup:70510"
    threads = {sid: [P02_OPENING]}
    a = routed(pkg, case, xc_relfloor=True)
    a.prepare(case, threads)
    m1 = a.thread_move(case, threads, sid)
    t2 = copy.deepcopy(threads)
    t2[sid] += [{**m1, "from": "buyer"}, reply(sid, {"unit_price": 369.7, "payment_days": 30, "index_clause": None}, n=1)]
    m2 = a.thread_move(case, t2, sid)
    assert m2 and not any(s["terms"].get("index_clause") for s in m2["term_sheets"]), "it moved: the fixed track goes on"
    t3 = copy.deepcopy(t2)
    t3[sid] += [{**m2, "from": "buyer"}, reply(sid, {"unit_price": 369.7, "payment_days": 30, "index_clause": None},
                                                body="Without movement from your side we cannot move either.", n=2)]
    assert a.held_rounds(t3[sid]) == 1
    m3 = a.thread_move(case, t3, sid)
    assert m3 and any(s["terms"].get("index_clause") for s in m3["term_sheets"]), "it held: the clause sheet is offered"
    clauses = [s["terms"]["index_clause"] for s in m3["term_sheets"] if s["terms"].get("index_clause")]
    assert all(c["deadband_pct"] == 5 for c in clauses), "widest deadband on a rising path"
    for price, floor in floors_ok(a, case, sid, m3, t3):
        assert floor is not None and price >= floor - 1e-9


def test_fixed_refusal_wording():
    yes = [
        "As we cannot offer a fixed price over a 24-month term, we propose an index clause.",
        "We are unable to offer a fixed price for a 24-month term.",
        "We cannot accept a fixed price without an index clause for a 24-month term.",
        "Please note that we cannot offer fixed pricing for extended periods.",
    ]
    no = [
        "Our AS-14404 is covered at fixed prices until March 2027, so that fall does not reach our cost.",
        "We offer a price of EUR 370.96 per unit, no Preisgleitklausel.",
    ]
    assert all(FIXED_REFUSED.search(s) for s in yes)
    assert not any(FIXED_REFUSED.search(s) for s in no)


def test_refusal_opens_the_clause_track_at_once(pkg):
    case, sid = CASES["case:P02"], "sup:70510"
    opening = {**P02_OPENING, "body": P02_OPENING["body"] + "Please note that we cannot offer a fixed price for this term."}
    threads = {sid: [opening]}
    a = routed(pkg, case, xc_relfloor=True)
    a.prepare(case, threads)
    assert a.xc_clause_allowed(case, threads, sid, 10)
    db5 = [c for c in case["term_options"]["index_clause"] if c and c["deadband_pct"] == 5][0]
    sheets = [{"unit_price": 366.0, "payment_days": 90, "index_clause": None}, {"unit_price": 364.0, "payment_days": 90, "index_clause": db5}]
    out = a.xc_relfloor_sheets(case, threads, sid, sheets, {}, a.rel_estimate(case, sid, {}), 10)
    assert any(s.get("index_clause") for s in out), "the clause sheet passes once a fixed price is refused"
    # its sheets carrying a clause against our fixed ask count as a refusal too
    plain = {sid: [P02_OPENING]}
    b = routed(pkg, case, xc_relfloor=True)
    b.prepare(case, plain)
    m1 = b.thread_move(case, plain, sid)
    t2 = {sid: plain[sid] + [{**m1, "from": "buyer"}, reply(sid, {"unit_price": 369.0, "payment_days": 30, "index_clause": db5})]}
    assert b.xc_clause_allowed(case, t2, sid, 9)


def test_supplier_sheet_below_the_floor_is_not_taken(pkg):
    """Logged P02 turn (session d6aafb79): its alternative 346.18 @ 14 d + clause carries ~120k EUR of relationship
    charge; the planner stopped ('at the relationship optimum') and base proposed that sheet back. With the switch we
    propose its terms at the floor instead."""
    case, sid = CASES["case:P02"], "sup:70510"
    db5 = [c for c in case["term_options"]["index_clause"] if c and c["deadband_pct"] == 5][0]
    ev = [
        P02_OPENING,
        {"from": "buyer", "body": "x", "term_sheets": [{"terms": {"unit_price": 345.43, "payment_days": 14, "index_clause": None}}], "refs": []},
        reply(sid, {"unit_price": 368.68, "payment_days": 14, "index_clause": None}, n=1),
        {"from": "buyer", "body": "x", "term_sheets": [{"terms": {"unit_price": 351.24, "payment_days": 14, "index_clause": None}},
                                                       {"terms": {"unit_price": 352.47, "payment_days": 30, "index_clause": None}}], "refs": []},
        {**reply(sid, {"unit_price": 369.77, "payment_days": 30, "index_clause": None}, n=2),
         "term_sheets": [{"term_sheet_id": "offer:70510-2", "terms": {"unit_price": 369.77, "payment_days": 30, "index_clause": None}},
                         {"term_sheet_id": "offer:70510-2-a", "terms": {"unit_price": 346.18, "payment_days": 14, "index_clause": db5}}]},
    ]
    threads = {sid: copy.deepcopy(ev)}
    on = routed(pkg, case, xc_relfloor=True)
    on.prepare(case, threads)
    msg = on.thread_move(case, threads, sid)
    assert msg and all(s["terms"]["unit_price"] >= 355 for s in msg["term_sheets"]), prices(msg)
    for price, floor in floors_ok(on, case, sid, msg, threads):
        assert floor is not None and price >= floor - 1e-9
    off = routed(pkg, case)
    off.prepare(case, {sid: copy.deepcopy(ev)})
    msg0 = off.thread_move(case, {sid: copy.deepcopy(ev)}, sid)
    assert msg0 and msg0["term_sheets"][0]["terms"]["unit_price"] == 346.18  # today: its alternative, proposed back


def test_never_a_zero_deadband_on_a_rising_path(pkg):
    case, sid = CASES["case:P02"], "sup:70510"
    threads = {sid: [{**P02_OPENING, "status": "final_offer"}]}
    a = routed(pkg, case, xc_relfloor=True)
    a.prepare(case, threads)
    opts = [c for c in case["term_options"]["index_clause"] if c]
    db0, db5 = [c for c in opts if c["deadband_pct"] == 0][0], [c for c in opts if c["deadband_pct"] == 5][0]
    sheets = [
        {"unit_price": 366.0, "payment_days": 90, "index_clause": None},
        {"unit_price": 364.0, "payment_days": 90, "index_clause": db0},
        {"unit_price": 364.5, "payment_days": 90, "index_clause": db5},
    ]
    out = a.xc_relfloor_sheets(case, threads, sid, sheets, {}, a.rel_estimate(case, sid, {}), 5)
    assert not any((s.get("index_clause") or {}).get("deadband_pct") == 0 for s in out)
    assert any((s.get("index_clause") or {}).get("deadband_pct") == 5 for s in out)


def test_floor_is_the_c_minimal_price(pkg):
    """Below the floor C rises again (relationship charge); just above it C rises with the price."""
    case, sid = CASES["case:P02"], "sup:70510"
    threads = {sid: [P02_OPENING]}
    a = routed(pkg, case, xc_relfloor=True)
    a.prepare(case, threads)
    sup = a.rel_estimate(case, sid, {})
    terms = {"unit_price": 365.0, "payment_days": 90, "index_clause": None}
    floor = a.rel_floor_price(case, sid, terms, {}, sup)
    c = lambda p: total_cost(case, {**terms, "unit_price": p}, {}, sup)  # noqa: E731
    assert c(floor - 2) > c(floor) and c(floor + 2) > c(floor) - 1  # a flat minimum, rounded up to the cent
    assert sup["full_cost"] == pytest.approx(374.95 * 0.98, abs=0.01)


def test_switches_off_change_nothing(pkg):
    case, sid = CASES["case:P02"], "sup:70510"
    threads = {sid: [P02_OPENING]}
    a = routed(pkg, case)
    a.prepare(case, threads)
    assert a.xc_clause_allowed(case, threads, sid, 10)
    assert a.rel_estimate(case, sid, {}) == a.supplier_estimate(case, sid, {})
    assert not a.rfq_mode(CASES["case:P05"])
    assert Params().xc_relfloor is False and Params().xc_rfq is False


# ---------------------------------------------------------------- item 7: RFQ ratchet
def p05_threads():
    case = CASES["case:P05"]
    return {sid: [reply(sid, t, body="Our quote.", n=0)] for sid, t in P05_OPENINGS.items()}, case


def first_round(pkg, **flags):
    threads, case = p05_threads()
    a = routed(pkg, case, **flags)
    a.prepare(case, threads)
    msgs = {sid: a.thread_move(case, threads, sid) for sid in case["suppliers"]}
    return a, case, threads, msgs


def test_rfq_cash_sheet_at_our_own_rate_and_90_days_main(pkg):
    a, case, threads, msgs = first_round(pkg, xc_rfq=True)
    for sid, msg in msgs.items():
        main, cash = msg["term_sheets"][0]["terms"], msg["term_sheets"][1]["terms"]
        assert main["payment_days"] == 90 and cash["payment_days"] < 90
        c_main, c_cash = total_cost(case, main), total_cost(case, cash)
        assert abs(c_cash - c_main) <= 0.01 * 4200 * 2 + 1, (sid, c_main, c_cash)  # equal C up to the cent rounding
    # today: the cash sheet is priced trade_gain (0.6 % of C) below the main sheet
    _, _, _, off = first_round(pkg)
    main, cash = off["sup:70210"]["term_sheets"][0]["terms"], off["sup:70210"]["term_sheets"][1]["terms"]
    assert total_cost(case, cash) < total_cost(case, main) * (1 - 0.005)


def test_rfq_hold_on_come_back_on_price(pkg):
    a, case, threads, msgs = first_round(pkg, xc_rfq=True)
    sid = "sup:70210"
    t2 = copy.deepcopy(threads)
    t2[sid] += [{**msgs[sid], "from": "buyer"}, reply(sid, {"unit_price": 30.5, "payment_days": 30, "lead_time_days": 35},
                                                       body="We need to clarify this internally - we will come back to you on price.")]
    m2 = a.thread_move(case, t2, sid)
    assert m2["term_sheets"][0]["terms"]["unit_price"] == msgs[sid]["term_sheets"][0]["terms"]["unit_price"]
    # today (v7a): a step toward its counter
    b, case, threads, msgs0 = first_round(pkg)
    t2 = copy.deepcopy(threads)
    t2[sid] += [{**msgs0[sid], "from": "buyer"}, reply(sid, {"unit_price": 30.5, "payment_days": 30, "lead_time_days": 35},
                                                        body="We need to clarify this internally - we will come back to you on price.")]
    assert b.thread_move(case, t2, sid)["term_sheets"][0]["terms"]["unit_price"] > msgs0[sid]["term_sheets"][0]["terms"]["unit_price"]


def agreed_round(pkg, **flags):
    """Round 2: Dralveck and Fuchsreiter agree to our main sheets, Hrvelec counters at 56 days (breaks lead <= 42)."""
    a, case, threads, msgs = first_round(pkg, **flags)
    t2 = copy.deepcopy(threads)
    for sid in ("sup:70210", "sup:70250"):
        t2[sid] += [{**msgs[sid], "from": "buyer"}, reply(sid, msgs[sid]["term_sheets"][0]["terms"], status="agreed", body="We agree.")]
    t2["sup:70240"] += [{**msgs["sup:70240"], "from": "buyer"},
                        reply("sup:70240", {"unit_price": 29.0, "payment_days": 60, "lead_time_days": 56})]
    return a, case, t2, msgs


def test_rfq_agreed_is_not_the_end_while_rounds_remain(pkg):
    a, case, t2, msgs = agreed_round(pkg, xc_rfq=True)
    leader = msgs["sup:70210"]["term_sheets"][0]["terms"]["unit_price"]  # Dralveck 28.08 @ 90 d agreed
    m_lead = a.thread_move(case, t2, "sup:70210")
    assert m_lead and m_lead["term_sheets"][0]["terms"]["unit_price"] == pytest.approx(leader * 0.98, abs=0.01)
    assert not a.threads["sup:70210"].ready
    m_other = a.thread_move(case, t2, "sup:70250")
    assert m_other and m_other["term_sheets"][0]["terms"]["unit_price"] < leader
    assert "offer:70210-1" in m_other["refs"], "the lowest agreed offer is cited to the other bidder"
    assert any("competing offer at EUR 28.08" in ln for ln in m_other["body"].splitlines())
    # the ratchet target ignores Hrvelec's 56-day sheet (must-have), close() never picks it
    assert a.xc_leader(case, t2, "sup:70250")[1] == "offer:70210-1"
    decision = a.close(case, t2, force=True)
    assert decision["supplier_id"] == "sup:70210"
    # today: both agreed threads are ready at round 2 and the case closes
    b, case, t2b, _ = agreed_round(pkg)
    assert b.thread_move(case, t2b, "sup:70210") is None and b.threads["sup:70210"].ready
    assert b.thread_move(case, t2b, "sup:70250") is None


def test_rfq_agreed_hold_without_new_evidence_is_ready(pkg):
    a, case, t2, msgs = agreed_round(pkg, xc_rfq=True)
    sid = "sup:70210"
    m3 = a.thread_move(case, t2, sid)
    t3 = copy.deepcopy(t2)
    # it agrees again, at the same price it stood at (a hold against our lower ask) - no rival below it to cite
    t3[sid] += [{**m3, "from": "buyer"}, reply(sid, t2[sid][-1]["term_sheets"][0]["terms"], status="agreed", n=2)]
    assert a.held_rounds(t3[sid]) == 1
    assert a.thread_move(case, t3, sid) is None and a.threads[sid].ready


def test_rfq_reserve_rounds_end_the_ratchet(pkg):
    a, case, t2, msgs = agreed_round(pkg, xc_rfq=True)
    short = {**case, "round_limit": 3}  # 1 message sent, 2 left = reserve + 1
    assert not a.rfq_ratchet(short, t2, "sup:70210", "agreed", 2)
    assert a.rfq_ratchet(case, t2, "sup:70210", "agreed", 9)


def test_router_x_turns_the_switches_on(monkeypatch):
    from csee.agents.router import RouterXAgent

    monkeypatch.setenv("CSEE_XFLAGS", "xc_relfloor,xc_rfq")
    r = RouterXAgent(params=variants.params("base"))
    r._route(CASES["case:P05"])
    assert r.inner.p.xc_rfq and r.inner.p.xc_relfloor and not r.inner.p.xc_push
    assert isinstance(r.inner, CseeAgent)
