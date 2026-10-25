"""Meaningful limits on the experimental raw closing counter."""

import copy

import pytest
from test_csee_smoke import opening
from test_raw_planner import CASES, reply

from arena_kit.cost import must_haves_ok, total_cost
from csee import variants
from csee.agents.ege_frontier import (
    EgeRawDeadbandAgent,
    EgeRawDualEvidenceAgent,
    EgeRawFinalAgent,
    EgeRawForecastAgent,
    EgeRawIndexMenuAgent,
    EgeRenewalStagedAgent,
    owner_calculation_note,
)
from csee.intel import Claim


def setup(cls, case):
    sid = case["suppliers"][0]
    main = {"unit_price": 4.8, "payment_days": 90, "contract_months": 24,
            "index_clause": case["term_options"]["index_clause"][-1]}
    events = [reply(case, 0, 6.1, indexed=False),
              {"from": "buyer", "term_sheets": [{"terms": main}]},
              reply(case, 1, 5.6)]
    events[-1]["body"] = "For a multi-year agreement we must include the AS-14404 index clause."
    agent = cls(params=variants.params("v16a"))
    threads = {sid: events}
    agent.prepare(case, threads)
    agent.status_quo[sid] = "AS-14404"
    agent.threads[sid].events = events
    return agent, threads, sid, main


@pytest.fixture
def case():
    return copy.deepcopy(next(c for c in CASES if c["case_id"] == "case:P18"))


def history(case, status="final_offer", prices=(5.8, 5.6, 5.2)):
    return [{"from": "supplier", "status": status if i == len(prices)-1 else "open",
             "body": "Our offer", "term_sheets": [{"term_sheet_id": f"offer:{i}",
             "terms": {"unit_price": p, "payment_days": 30, "contract_months": 24,
                       "index_clause": case["term_options"]["index_clause"][-1]}}]}
            for i, p in enumerate(prices)]


def test_push_only_after_substantial_concessions_and_final_status(case):
    agent = EgeRawFinalAgent()
    assert agent.final_push_size(case, history(case)) == .02
    for status in ("open", "agreed", "walked_away"):
        assert agent.final_push_size(case, history(case, status)) == 0
    assert agent.final_push_size(case, history(case, prices=(5.8, 5.6, 5.55))) == 0
    assert agent.final_push_size(case, history(case, prices=(5.6, 5.2))) == 0
    assert agent.final_push_size({**case, "type": "price_increase"}, history(case)) == 0


def test_existing_once_only_and_agreement_guards_remain(case):
    agent, threads, sid, _ = setup(EgeRawFinalAgent, case)
    threads[sid][-1]["status"] = "agreed"
    assert agent.thread_move(case, threads, sid) is None
    agent, threads, sid, _ = setup(EgeRawFinalAgent, case)
    threads[sid] = history(case)
    message = agent.thread_move(case, threads, sid)
    assert message["term_sheets"][0]["terms"]["unit_price"] == 5.1
    assert agent.threads[sid].pushed == 1
    threads[sid].append({"from": "buyer", **message})
    threads[sid].append(history(case)[-1])
    assert agent.thread_move(case, threads, sid) is None


def test_deadband_candidate_keeps_coverage_and_has_no_final_push(case):
    agent, threads, sid, _ = setup(EgeRawDeadbandAgent, case)
    message = agent.thread_move(case, threads, sid)
    main = message["term_sheets"][0]["terms"]
    assert main["index_clause"]["deadband_pct"] == 3
    assert main["contract_months"] >= case["buyer"]["horizon_years"] * 12
    threads[sid][-1]["status"] = "final_offer"
    assert agent.thread_move(case, threads, sid) is None
    assert agent.p.final_push == 0 and agent.p.push_after_final == 0


def test_index_menu_buys_protection_with_price_without_changing_cash_or_coverage(case):
    agent, threads, sid, _ = setup(EgeRawIndexMenuAgent, case)
    message = agent.thread_move(case, threads, sid)
    sheets = [s["terms"] for s in message["term_sheets"]]
    assert [s["index_clause"]["deadband_pct"] for s in sheets] == [5, 3, 0]
    main = sheets[0]
    for t in sheets:
        assert must_haves_ok(case, t)
        assert t["payment_days"] == main["payment_days"]
        assert t["contract_months"] == main["contract_months"]
        assert total_cost(case, t) <= total_cost(case, main) + .001
    assert sheets[0]["unit_price"] > sheets[1]["unit_price"] > sheets[2]["unit_price"]


def test_renewal_staging_preserves_unsent_evidence_and_restores_shared_budget():
    case = copy.deepcopy(next(c for c in CASES if c["case_id"] == "case:P03"))
    sid = case["suppliers"][0]
    threads = {sid: [opening(case, sid)]}
    agent = EgeRenewalStagedAgent(params=variants.params("v14a"))
    agent.prepare(case, threads)
    agent.threads[sid].intel.claims = [Claim("Cost", ["cost:test"], "should_cost"),
                                     Claim("Forecast", ["fc:test"], "forecast")]
    before = agent.p.max_claims
    assert [c.ids for c in agent.pick_claims(case, threads, sid)] == [["cost:test"]]
    assert "fc:test" not in agent.used_ids
    assert agent.p.max_claims == before
    threads[sid].append({"from": "buyer", "refs": ["cost:test"]})
    assert [c.ids for c in agent.pick_claims(case, threads, sid)] == [["fc:test"]]
    assert agent.p.max_claims == before


@pytest.mark.parametrize("growth,expected", [(1.9, True), (0, False), (-2, False)])
def test_raw_forecast_uses_only_latest_positive_growth(case, growth, expected):
    part = case["parts"][0].split(":")[-1]
    current = f"fc:{part}@2026-09"
    case["facts"] = {f"fc:{part}@2026-06": {"change_pct": 4, "part": case["parts"][0]},
                     current: {"change_pct": growth, "part": case["parts"][0]}}
    agent, threads, sid, _ = setup(EgeRawForecastAgent, case)
    claims = [c for c in agent.threads[sid].intel.claims if c.kind == "forecast"]
    assert bool(claims) is expected
    if expected:
        assert claims[0].ids == [current]
        assert "+1.9%" in claims[0].sentence
    assert agent.p.final_push == 0


def test_dual_evidence_opening_preserves_second_index_and_restores_order(case):
    sid = case["suppliers"][0]
    threads = {sid: [opening(case, sid)]}
    agent = EgeRawDualEvidenceAgent(params=variants.params("v16c"))
    agent.prepare(case, threads)
    original = [Claim("Index one", ["idx:A@1", "idx:A@2"], "index"),
                Claim("Index two", ["idx:B@1", "idx:B@2"], "index"),
                Claim("Demand", ["fc:part@latest"], "forecast")]
    agent.threads[sid].intel.claims = original
    budget = agent.p.max_claims
    assert agent.pick_claims(case, threads, sid) == [original[0], original[2]]
    assert agent.threads[sid].intel.claims is original
    assert agent.p.max_claims == budget
    assert "idx:B@1" not in agent.used_ids
    threads[sid].append({"from": "buyer"})
    assert agent.pick_claims(case, threads, sid) == [original[1]]


def test_owner_invitation_requires_actual_supplier_document():
    from types import SimpleNamespace

    bodies = {"doc:2026-09": "The owner offered to walk us through their calculation.",
              "doc:2026-10": "Sales declined to provide a calculation."}
    pkg = SimpleNamespace(facts={ref: {"supplier": "sup:a"} for ref in bodies},
                          document=lambda ref: bodies[ref])
    assert owner_calculation_note({}, pkg, "sup:a") == "doc:2026-09"
    assert owner_calculation_note({}, pkg, "sup:b") is None
    bodies["doc:2026-09"] = "Owner has not offered a cost review."
    assert owner_calculation_note({}, pkg, "sup:a") is None
    assert owner_calculation_note({}, None, "sup:a") is None


def test_modest_forecast_does_not_displace_stronger_cost_or_notice_evidence(case, monkeypatch):
    from types import SimpleNamespace

    from csee.agents.mert_dossier import PlanMesoRawDossierClaims

    original = [Claim("Cost", ["cost:test"], "should_cost"),
                Claim("Notice", ["doc:test", "ctr:test"], "notice"),
                Claim("Index", ["idx:A@1", "idx:A@2"], "index"),
                Claim("Delivery", ["sc:test"], "scorecard"),
                Claim("Hedged index", ["idx:B@1", "idx:B@2"], "index")]
    sid = case["suppliers"][0]
    part = case["parts"][0].split(":")[-1]
    case["facts"] = {f"fc:{part}@2026-09": {"change_pct": 1.9}}

    def parent_prepare(self, case, threads):
        self.threads = {sid: SimpleNamespace(intel=SimpleNamespace(claims=original.copy()))}

    monkeypatch.setattr(PlanMesoRawDossierClaims, "prepare", parent_prepare)
    agent = EgeRawForecastAgent()
    agent.prepare(case, {sid: []})
    claims = agent.threads[sid].intel.claims
    assert claims[:3] == original[:3]
    assert claims[3].kind == "forecast"
    assert claims[4:] == original[3:]
