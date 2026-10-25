"""Offline regression checks for state, evidence, review and empirical memory."""

import copy
import json

import pytest
from test_unified import CASES, fixture

from arena_kit.cost import closing_terms, total_cost
from csee.intel import Claim
from csee.negotiation import control, engine, evidence, memory, preparation


def event(price, *, buyer=False, payment=30):
    return {
        "from": "buyer" if buyer else "supplier",
        "status": "open",
        "term_sheets": [
            {
                "term_sheet_id": f"offer:{price}",
                "terms": {"unit_price": price, "payment_days": payment, "lead_time_days": 35},
            }
        ],
    }


def test_hold_is_comparable_one_time_and_does_not_apply_at_last_round():
    agent, case, threads = fixture()
    events = [event(11), event(8, buyer=True), event(9)]
    threads["sup:alpha"] = events
    state = control.observe(case, events, {})
    assert state["comparable_price_concession"] == 2 and state["hold_probe_eligible"]
    quote = events[-1]["term_sheets"][0]["terms"]
    earlier = engine.propose(agent, case, threads, "sup:alpha", quote, {}, None, 8)
    late = engine.propose(agent, case, threads, "sup:alpha", quote, {}, None, 2)
    assert total_cost(case, earlier) <= total_cost(case, events[1]["term_sheets"][0]["terms"]) + 1
    assert total_cost(case, late) > total_cost(case, earlier)
    events += [event(8, buyer=True), event(9)]
    assert not control.observe(case, events, {})["hold_probe_eligible"]
    assert control.observe(case, events, {})["consecutive_stalls"] == 1
    events[-1] = event(8.9, payment=14)
    assert control.observe(case, events, {})["comparable_price_concession"] is None


def test_unadopted_terms_and_stalls_reconstruct_on_resume():
    _, case, _ = fixture()
    events = [event(11), event(8, buyer=True, payment=90), event(10), event(8.5, buyer=True, payment=90), event(10)]
    state = control.observe(case, events, {})
    assert state["unadopted_terms"]["payment_days=90"] == 2
    assert state == control.observe(case, copy.deepcopy(events), {})
    assert "unknown" in state["patience"]


def test_opening_responds_to_documented_driver_not_model_stance():
    agent, case, threads = fixture()
    case["suppliers"] = ["sup:alpha"]
    threads.pop("sup:beta")
    default = control.opening_discount(agent, case, threads, "sup:alpha")
    agent.briefs["sup:alpha"] = {"stance": "competitive", "stance_evidence": [{"quote": "spare capacity"}]}
    assert control.opening_discount(agent, case, threads, "sup:alpha") == default
    agent.evidence_records["sup:alpha"] = {"E": {"kind": "index", "calculation": {"change_pct": -5}}}
    assert control.opening_discount(agent, case, threads, "sup:alpha") > default


def test_evidence_retains_period_formula_and_uncertainty():
    _, case, _ = fixture()
    case["facts"] = {
        "idx:X@2026-01": {"value": 100, "month": "2026-01"},
        "idx:X@2026-04": {"value": 94, "month": "2026-04"},
    }
    claim = Claim("Index X fell six percent.", list(case["facts"]), "index", tag="X")
    rec = next(iter(evidence.records(case, None, [claim]).values()))
    assert rec["calculation"]["change_pct"] == -6
    assert rec["periods"] == ["2026-01", "2026-04"]
    assert rec["status"] == "calculated_from_documents" and "unverified" in rec["uncertainty"]
    claim.ids.append("idx:missing")
    assert next(iter(evidence.records(case, None, [claim]).values()))["status"] == "incomplete_sources"


def test_playbook_requires_provenance_and_an_invalidation_condition():
    source = "We require an index clause for this contract."
    item = {
        "trigger": "index_request",
        "source": "doc:X",
        "quote": source,
        "interpretation": "Offer a code-priced clause trade",
        "claim_ids": ["E1", "invented"],
        "invalidated_by": "Supplier offers a fixed price instead",
    }
    plans = preparation.playbook([item], {"doc:X": source}, {"E1": {}})
    assert plans[0]["claim_ids"] == ["E1"] and plans[0]["status"] == "conditional_hypothesis"
    assert not preparation.playbook([{**item, "invalidated_by": ""}], {"doc:X": source}, {})
    assert not preparation.playbook([{**item, "quote": "Invented claim about index"}], {"doc:X": source}, {})


@pytest.mark.parametrize(
    "mode,dispute,expected", [("selective", False, 1), ("selective", True, 2), ("off", True, 1), ("always", False, 2)]
)
def test_selective_review_and_failed_reviewer_preserve_successful_lead(mode, dispute, expected):
    calls, choices = [], []

    def complete(system, user):
        payload = json.loads(user)
        calls.append(system.split(".")[0])
        if "ROLE: deal_challenger." in system:
            assert payload["selected_id"] == choices[0]["id"]
            return "broken JSON"
        chosen = next(c for c in payload["candidates"] if c["kind"] == "payment_days")
        choices.append(chosen)
        return json.dumps({"candidate_id": chosen["id"], "alternative_ids": [], "claim_ids": []})

    agent, case, threads = fixture(complete)
    agent.REVIEW_MODE = mode
    if dispute:
        threads["sup:alpha"][-1]["claim_results"] = [{"index": 0, "result": "contradicted"}]
    msg = agent.thread_move(case, threads, "sup:alpha")
    assert len(calls) == expected
    assert msg["term_sheets"][0]["terms"] == choices[0]["terms"]


def test_weaker_index_protection_is_costed_and_reviewed():
    case = copy.deepcopy(next(c for c in CASES if c["case_id"] == "case:P18"))
    clauses = case["term_options"]["index_clause"]
    protected = next(c for c in clauses if c and c["deadband_pct"] == 5)
    weaker = next(c for c in clauses if c and c["deadband_pct"] == 3)
    current = closing_terms(case, {"unit_price": 5.3, "index_clause": protected, "payment_days": 90})
    changed = {**current, "index_clause": weaker}
    rows = [
        {"id": "C0", "terms": current, "cost": total_cost(case, current)},
        {"id": "C1", "terms": changed, "cost": total_cost(case, changed)},
    ]
    state = {"unadopted_terms": {}, "consecutive_stalls": 0}
    control.annotate(case, rows, current, {}, None, state)
    assert rows[1]["index_change_cost_at_same_price"] > 0
    assert control.review_reasons(rows[1], state, {})


def test_memory_is_deduplicated_feature_based_and_excludes_simulation(tmp_path):
    _, case, _ = fixture()
    rows = [
        {"type": "case_opened", "case": case, "opening": {"sup:alpha": {"priced": {"terms": {"unit_price": 10}}}}},
        {"type": "message_sent", "supplier_id": "sup:alpha", "sheets": [{"terms": {"unit_price": 8}}]},
        {
            "type": "result",
            "score": 0.6,
            "deal": True,
            "supplier_id": "sup:alpha",
            "run_id": "run:A",
            "session_id": "session:private",
            "case_id": "case:private",
        },
    ]
    assert memory.summarize(rows, {"set": "sim"}) is None
    row = memory.summarize(rows, {"set": "practice", "agent": "candidate", "variant": "base"})
    assert row["paths"][0]["buyer_price_ratios"] == [0.8]
    serialized = json.dumps(row)
    assert "sup:alpha" not in serialized and "case:private" not in serialized and "session:private" not in serialized
    path = tmp_path / "memory.jsonl"
    memory.append(row, path)
    memory.append(row, path)
    newcase = {**case, "case_id": "case:new", "suppliers": ["sup:new1", "sup:new2"]}
    recalled = memory.recall(newcase, path)
    assert recalled["matching_sample_count"] == 1 and recalled["samples"][0]["score"] == 0.6
    assert memory.recall({**newcase, "type": "quality"}, path)["matching_sample_count"] == 0
