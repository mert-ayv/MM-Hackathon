"""Cross-check plan stream A: xc_claims (claim selection) and xc_answer (answer the supplier's questions).
Offline, no network, no model. The data package is the copy at the repo root (as test_csee_smoke)."""

import json
from pathlib import Path

import pytest

from arena_kit.data import DataPackage
from csee import intel
from csee.agent import CseeAgent, Params, avoided, avoided_x, dead_kinds, detect_questions, is_dead
from csee.agents.router import ROUTES, resolve
from csee.writer import LLMWriter, TemplateWriter, strip_fixed_promises

CASES = Path(__file__).parents[1] / "csee" / "cases" / "practice.json"
DATA = next(
    (p for p in (Path(__file__).parents[1] / "data" / "package", Path(__file__).parents[2] / "data") if p.exists()),
    Path(__file__).parents[1] / "data" / "package",
)
pytestmark = pytest.mark.skipif(not CASES.exists() or not DATA.exists(), reason="no case files or data package")

# the practice bots' opening e-mails (the cost drivers they blame), from logged sessions
OPENINGS = {
    "case:P07": (5.74, {"payment_days": 30, "contract_months": 12}, "We can offer you a price of 5.74 per unit."),
    "case:P08": (
        6.05,
        {"payment_days": 30, "contract_months": 12, "index_clause": None},
        "AS-14404 rose 5.9 % in twelve months and is 45 % of our cost. PPI-C2431 rose 12.3 % in twelve months.",
    ),
    "case:P11": (47.0, {"ppm_commitment": 6400, "chargeback_eur_per_complaint": 0}, "Our offer: 47.00 per unit."),
    "case:P04": (4.96, {"payment_days": 30, "contract_months": 12}, "Our offer: 4.96 per unit."),
}


@pytest.fixture(scope="module")
def pkg():
    p = DataPackage(DATA)
    p.lookup("")
    return p


@pytest.fixture(scope="module")
def cases():
    return {c["case_id"]: c for c in json.loads(CASES.read_text())}


def threads_for(case):
    sid = case["suppliers"][0]
    price, terms, body = OPENINGS.get(case["case_id"], (case["buyer"]["current_unit_price"] * 1.06, {}, "Our quote."))
    terms = {"unit_price": price, **{f: terms.get(f) for f in case["negotiable"] if f != "unit_price" and f in terms}}
    return {sid: [{"from": f"sales@{sid}", "status": "open", "body": body, "attachments": [],
                   "term_sheets": [{"term_sheet_id": f"offer:{sid}-0", "terms": terms}]}]}


def routed(pkg, case, **flags):
    """The agent the final router plays for this case type, with the given xc_* switches (as router-x)."""
    from dataclasses import replace

    cls, params = resolve(ROUTES[case["type"]], Params())
    return cls(pkg, None, replace(params, **flags))


def picked(pkg, case, **flags):
    agent = routed(pkg, case, **flags)
    threads = threads_for(case)
    agent.prepare(case, threads)
    sid = case["suppliers"][0]
    return agent, threads, agent.pick_claims(case, threads, sid)


# ---------- item 1: claim selection ----------
def test_p08_own_quote_first(pkg, cases):
    _, _, claims = picked(pkg, cases["case:P08"], xc_claims=True)
    assert claims and claims[0].ids == ["quote:7300008"] and "EUR 5.45" in claims[0].sentence
    assert "quote:7300008" not in [i for c in picked(pkg, cases["case:P08"])[2] for i in c.ids]  # off = today


def test_p08_hedge_letter_read_symmetrically(pkg, cases):
    agent, _, _ = picked(pkg, cases["case:P08"], xc_claims=True)
    hedge = [c for c in agent.threads["sup:70710"].intel.claims if c.kind == "hedge"]
    assert len(hedge) == 1 and hedge[0].ids == ["doc:20260706-70710-M1"]
    assert "covered at fixed prices" in hedge[0].sentence and not any(ch.isdigit() for ch in hedge[0].sentence.split("(")[0])


def test_p07_largest_forecast_first_one_per_round(pkg, cases):
    case = cases["case:P07"]
    agent, threads, claims = picked(pkg, case, xc_claims=True)
    assert claims[0].ids == ["fc:360011@2026-09"] and "+15.3%" in claims[0].sentence
    assert sum(c.kind == "forecast" for c in claims) == 1
    assert any(c.tag == "note" and c.ids[0].startswith("doc:") for c in claims)  # idle-capacity call note
    sid = "sup:70610"
    threads[sid] += [{"from": "buyer", "body": "x", "term_sheets": [{"terms": {"unit_price": 5.0}}]},
                     {"from": f"sales@{sid}", "status": "open", "body": "Thank you.", "term_sheets": []}]
    second = agent.pick_claims(case, threads, sid)
    fcs = [c for c in second if c.kind == "forecast"]
    assert len(fcs) == 1 and fcs[0].ids == ["fc:360012@2026-09"]  # the next-largest part, next round
    off = picked(pkg, case)[2]
    assert off[0].ids == ["fc:360010@2026-09"]  # today: the first part >= 3 %


def test_p11_keeps_a_quality_ppm_claim(pkg, cases):
    _, _, claims = picked(pkg, cases["case:P11"], xc_claims=True)
    ppm = [c for c in claims if c.tag == "ppm"]
    assert ppm and "quality" in ppm[0].sentence.lower() and "2376 ppm" in ppm[0].sentence
    assert not [c for c in picked(pkg, cases["case:P11"])[2] if c.tag == "ppm"]  # today: avoided() drops it


def test_p04_list_price_not_the_small_lot_quote(pkg, cases):
    _, _, claims = picked(pkg, cases["case:P04"], xc_claims=True)
    assert claims[0].ids == ["quote:7300004"] and "list price" in claims[0].sentence and "EUR 4.39" in claims[0].sentence


def test_never_a_rising_index(pkg, cases):
    for case in cases.values():
        agent, _, _ = picked(pkg, case, xc_claims=True)
        for st in agent.threads.values():
            assert not [c for c in st.intel.claims if c.kind == "index" and "changed +" in c.sentence]


def test_avoided_x_matches_the_named_argument_only():
    ppm = intel.Claim("On quality: your complaint rate was 2376 ppm (sc:70140@2026Q3).", ["sc:70140@2026Q3"], "scorecard", tag="ppm")
    assert avoided(ppm, "pln/energy arguments irrelevant to a quality case")  # today's substring bug
    assert not avoided_x(ppm, ["PLN/energy arguments"])
    assert avoided_x(ppm, ["Quality complaints"]) and avoided_x(ppm, ["Making the red scorecard the headline"])
    quote = intel.Claim("Your own quote (quote:7200019).", ["quote:7200019"], "own_quote", tag="own_quote")
    assert avoided_x(quote, ["Its own second-source quote:7200019 (4.63)"])
    idx = intel.Claim("x", ["idx:PPI-D351@2026-01", "idx:PPI-D351@2026-08"], "index", tag="PPI-D351")
    assert avoided_x(idx, ["PLN/energy arguments"]) and not avoided_x(idx, ["Threats to resource"])


def test_dead_kinds_after_does_not_change():
    ev = [
        {"from": "buyer", "body": "Your on-time delivery was 88.0% (sc:70710@2026Q3). Producer prices changed -2.1% "
                                  "(idx:PPI-C2431@2026-05, idx:PPI-C2431@2026-08).", "refs": []},
        {"from": "sales@x", "body": "We checked the delivery record data you cited; it holds, but it does not change our "
                                    "calculation. We checked the index change data you cited; it holds, but it does not "
                                    "change our calculation. We checked the rival quote; it does not change our calculation."},
    ]
    dead = dead_kinds(ev)
    assert ("scorecard", "otd") in dead and ("index", "PPI-C2431") in dead
    assert "rival" not in dead and ("scorecard", "ppm") not in dead
    assert is_dead(intel.Claim("x", ["sc:70710@2026Q2"], "scorecard", tag="otd"), dead)
    assert is_dead(intel.Claim("x", ["idx:PPI-C2431@2026-01", "idx:PPI-C2431@2026-08"], "index"), dead)
    assert not is_dead(intel.Claim("x", ["idx:AS-14404@2026-06", "idx:AS-14404@2026-09"], "index"), dead)


def test_weak_claims_never(pkg, cases):
    """Order history (0/94) and the delivery record (7/29, an attack on a sole-source supplier) are never cited."""
    case = cases["case:P08"]
    agent, threads, _ = picked(pkg, case, xc_claims=True, history_claims=True)
    sid = "sup:70710"
    pools = agent.xc_pools(threads[sid], agent.threads[sid].intel.claims)
    assert len(pools) == 1 and all(c.tag not in ("po", "otd") for c in pools[0])
    agent.used_ids.update(i for c in pools[0] for i in c.ids)  # everything else spent
    assert all(c.tag not in ("po", "otd") for c in agent.pick_claims(case, threads, sid))


# ---------- item 4: answer the supplier's questions ----------
def test_detect_questions():
    assert detect_questions("A binding higher volume would help us. Which volume can you commit to?") == {"volume"}
    assert detect_questions("Which figures is that based on? Please send us the data.") == {"figures"}
    assert detect_questions("What payment terms can you offer us to make this work?") == {"payment"}
    assert detect_questions("Could we discuss faster payment terms to help us move forward?") == {"payment"}
    assert detect_questions("We commit to deliver on time.") == set()


def test_p11_answers_volume_and_payment_as_fixed(pkg, cases):
    case = cases["case:P11"]
    agent = routed(pkg, case, xc_answer=True, xc_claims=True)
    threads = threads_for(case)
    agent.prepare(case, threads)
    sid = "sup:70140"
    threads[sid] += [
        {"from": "buyer", "body": "x", "term_sheets": [{"terms": {"unit_price": 42.0, "ppm_commitment": 300, "chargeback_eur_per_complaint": 0}}]},
        {"from": f"sales@{sid}", "status": "open", "body": "Faster payment would help us more than anything. What payment "
                                                            "terms can you offer us? Which volume can you commit to?",
         "term_sheets": [{"term_sheet_id": "offer:70140-1", "terms": {"unit_price": 46.5, "ppm_commitment": 300, "chargeback_eur_per_complaint": 0}}]},
    ]
    sheets = [{"unit_price": 42.5, "ppm_commitment": 300, "chargeback_eur_per_complaint": 0}]
    answers = agent.answer_claims(case, threads, sid, sheets, [])
    text = " ".join(c.sentence for c in answers)
    assert "15,900 units a year over 12 months is fixed" in text
    assert "payment term is fixed at 60 days net" in text and "come back" not in text
    assert any(c.kind == "forecast" and c.ids == ["fc:310020@2026-09"] for c in answers)  # the verifiable reference
    body = TemplateWriter().write(case, agent, sid, threads[sid], sheets, answers, False)
    assert "On volume:" in body and "On payment:" in body


def test_answers_in_thread_move_only_with_switch(pkg, cases):
    case = cases["case:P07"]
    sid = "sup:70610"
    for flag in (True, False):
        agent = CseeAgent(pkg, None, Params(xc_answer=flag))
        threads = threads_for(case)
        agent.prepare(case, threads)
        first = agent.thread_move(case, threads, sid)
        threads[sid] += [{**first, "from": "buyer"},
                         {"from": f"sales@{sid}", "status": "open", "body": "Which volume can you commit to?",
                          "term_sheets": [{"term_sheet_id": "offer:70610-1", "terms": {**threads[sid][0]["term_sheets"][0]["terms"], "unit_price": 5.6}}]}]
        msg = agent.thread_move(case, threads, sid)
        assert msg is not None
        assert ("On volume: our requirement of 30,000 units a year" in msg["body"]) is flag


def test_strip_fixed_promises(cases):
    case = cases["case:P11"]  # payment and volume fixed
    gone = ("We are open to discussing improved payment timing as part of this agreement and will come back to you "
            "with a concrete proposal.")
    kept = "We propose EUR 42.50 per unit, a 300 ppm quality commitment, EUR 0 chargeback per complaint."
    fixed = "On payment: the payment term is fixed at 60 days net in this enquiry and is not part of this negotiation."
    text = f"Good day,\n\n{gone} {kept}\n{fixed}\n\nBest regards"
    out = strip_fixed_promises(text, case, keep={fixed})
    assert gone not in out and kept in out and fixed in out
    # a case where payment is negotiable: the sentence stays
    assert strip_fixed_promises(gone, cases["case:P07"]) == gone


def test_llm_writer_strips_promises_only_with_switch(pkg, cases):
    case = cases["case:P11"]
    sid = "sup:70140"
    promise = "We will come back to you with a concrete proposal on payment timing."

    def model(system, prompt):
        return f"Good day,\n\n{promise} We propose EUR 42.50 per unit.\n\nBest regards\nHollerau Pumpenwerke GmbH, Purchasing"

    for flag in (True, False):
        agent = CseeAgent(pkg, LLMWriter(model), Params(xc_answer=flag))
        threads = threads_for(case)
        agent.prepare(case, threads)
        text = agent.writer.write(case, agent, sid, threads[sid], [{"unit_price": 42.5, "ppm_commitment": 300,
                                                                    "chargeback_eur_per_complaint": 0}], [], False)
        assert (promise in text) is (not flag)
