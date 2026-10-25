"""Replay-shaped tests for the P18 failure, with unfamiliar supplier/case identities."""

import copy
import json

import pytest
from test_unified import CASES

from arena_kit.cost import closing_terms, total_cost
from csee.agents.unified import UnifiedAgent
from csee.negotiation import control, engine
from csee.writer import LLMWriter

SID = "sup:unseen-raw"


def case_and_terms():
    case = copy.deepcopy(next(c for c in CASES if c["case_id"] == "case:P18"))
    case.update(case_id="case:unseen-raw", suppliers=[SID], facts={}, refs=[])
    clauses = case["term_options"]["index_clause"]
    protected = next(c for c in clauses if c and c["deadband_pct"] == 5)
    weak = next(c for c in clauses if c and c["deadband_pct"] == 0)
    return case, protected, weak


def quote(terms, buyer=False):
    return {
        "from": "buyer" if buyer else "supplier",
        "status": "open",
        "body": "We require standard payment and can discuss the clause.",
        "term_sheets": [{"term_sheet_id": "offer:unseen", "terms": terms}],
        "attachments": [],
    }


def menu(case, protected):
    specs = [(4.86, 14, None), (4.81, 14, protected), (4.90, 60, None)]
    return [
        {
            "id": f"C{i}",
            "terms": {"unit_price": price, "payment_days": days, "contract_months": 24, "index_clause": clause},
            "kind": "baseline" if i == 0 else "requested_trade",
            "reason": "priced option",
            "cost": total_cost(
                case, {"unit_price": price, "payment_days": days, "contract_months": 24, "index_clause": clause}
            ),
        }
        for i, (price, days, clause) in enumerate(specs)
    ]


@pytest.mark.parametrize("mode", ["selective", "always"])
def test_cost_only_review_cannot_destroy_protected_opening(monkeypatch, mode):
    case, protected, _ = case_and_terms()
    rows, calls = menu(case, protected), []

    def model(system, user):
        calls.append(system.split(".")[0])
        if system.startswith("ROLE: deal_challenger"):
            return json.dumps(
                {
                    "candidate_id": "C2",
                    "alternative_ids": [],
                    "reason_code": "keep",
                    "reason": "C2 is slightly cheaper.",
                }
            )
        return json.dumps(
            {
                "candidate_id": "C1",
                "alternative_ids": ["C2"],
                "claim_ids": [],
                "paragraph": "We propose tying the price to the alloy index.",
            }
        )

    agent = UnifiedAgent(writer=LLMWriter(model))
    agent.REVIEW_MODE = mode
    threads = {SID: [quote({"unit_price": 6.1, "payment_days": 30, "contract_months": 12, "index_clause": None})]}
    agent.prepare(case, threads)
    monkeypatch.setattr(engine, "propose", lambda *args: rows[0]["terms"])
    monkeypatch.setattr(engine, "menu", lambda *args: copy.deepcopy(rows))
    message = agent.thread_move(case, threads, SID)
    assert message["term_sheets"][0]["terms"]["index_clause"] == protected
    assert len(message["term_sheets"]) == 2
    assert len(calls) == (1 if mode == "selective" else 2)


def test_supported_review_replaces_bundle_and_discards_stale_words(monkeypatch):
    case, protected, _ = case_and_terms()
    rows = menu(case, protected)

    def model(system, user):
        payload = json.loads(user)
        if system.startswith("ROLE: deal_challenger"):
            ref = next(iter(payload["live_sources"]))
            return json.dumps(
                {
                    "candidate_id": "C2",
                    "alternative_ids": ["C1"],
                    "reason_code": "supplier_constraint",
                    "evidence": {
                        "source": ref,
                        "quote": "We require standard payment",
                        "interpretation": "Payment request",
                    },
                    "reason": "Address payment.",
                }
            )
        return json.dumps(
            {
                "candidate_id": "C1",
                "alternative_ids": ["C2"],
                "claim_ids": [],
                "paragraph": "We propose tying the price to the alloy index.",
            }
        )

    agent = UnifiedAgent(writer=LLMWriter(model))
    agent.REVIEW_MODE = "always"
    threads = {SID: [quote({"unit_price": 6.1, "payment_days": 30, "contract_months": 12, "index_clause": None})]}
    agent.prepare(case, threads)
    monkeypatch.setattr(engine, "propose", lambda *args: rows[0]["terms"])
    monkeypatch.setattr(engine, "menu", lambda *args: copy.deepcopy(rows))
    message = agent.thread_move(case, threads, SID)
    sheets = message["term_sheets"]
    assert sheets[0]["terms"]["index_clause"] is None
    assert sheets[1]["terms"]["index_clause"] == protected
    assert rows[1]["cost"] > rows[2]["cost"]  # it survives the cheaper primary
    assert "We propose tying" not in message["body"]
    assert "index clause none" in message["body"] and '"deadband_pct": 5' in message["body"]


@pytest.mark.parametrize("supplier_price,compensation", [(5.5, "unconfirmed"), (5.1, "supplier_quoted")])
def test_compensation_must_be_in_a_supplier_quote(supplier_price, compensation):
    case, protected, weak = case_and_terms()
    strong = {"unit_price": 5.5, "payment_days": 60, "contract_months": 24, "index_clause": protected}
    trial = {**strong, "unit_price": 4.9, "index_clause": weak}
    actual = {**trial, "unit_price": supplier_price}
    events = [quote(strong), quote(trial, buyer=True), quote(actual)]
    state = control.observe(case, events, {})
    rows = [
        {"id": "C0", "terms": strong, "cost": total_cost(case, strong)},
        {"id": "C1", "terms": trial, "cost": total_cost(case, trial)},
    ]
    control.annotate(case, rows, closing_terms(case, actual), {}, None, state)
    assert rows[1]["term_concession"]["compensation"] == compensation
    assert rows[1]["term_concession"]["cost_at_supplier_price"] > 0


def test_uncompensated_clause_stays_alternative_to_protected_primary(monkeypatch):
    case, protected, weak = case_and_terms()
    main = {"unit_price": 5.04, "payment_days": 60, "contract_months": 24, "index_clause": protected}
    trial = {**main, "unit_price": 4.93, "index_clause": weak}
    rows = [
        {
            "id": f"C{i}",
            "terms": t,
            "kind": "baseline" if i == 0 else "requested_trade",
            "reason": "priced option",
            "cost": total_cost(case, t),
        }
        for i, t in enumerate([main, trial])
    ]

    def model(*_):
        return json.dumps(
            {
                "candidate_id": "C1",
                "alternative_ids": [],
                "claim_ids": [],
                "paragraph": "We have kept your clause exactly as proposed.",
            }
        )

    agent = UnifiedAgent(writer=LLMWriter(model))
    agent.REVIEW_MODE = "off"  # the financial guard must work without a reviewer
    actual = {**trial, "unit_price": 5.5}
    threads = {SID: [quote(actual), quote({**main, "unit_price": 5.0}, buyer=True), quote(actual)]}
    agent.prepare(case, threads)
    monkeypatch.setattr(engine, "propose", lambda *args: main)
    monkeypatch.setattr(engine, "menu", lambda *args: copy.deepcopy(rows))
    message = agent.thread_move(case, threads, SID)
    assert message["term_sheets"][0]["terms"]["index_clause"] == protected
    assert message["term_sheets"][1]["terms"]["index_clause"] == weak
    assert "complete conditional package" in message["body"]
    assert "kept your clause exactly" not in message["body"]
    assert all(total_cost(case, s["terms"]) <= rows[0]["cost"] + 0.01 for s in message["term_sheets"])


def test_duplicate_alternatives_count_as_one_ignored_request():
    case, protected, weak = case_and_terms()
    strong = {"unit_price": 5.1, "payment_days": 90, "contract_months": 24, "index_clause": protected}
    ask = quote(strong, buyer=True)
    ask["term_sheets"].append({"terms": {**strong, "unit_price": 5.0}})
    reply = quote({**strong, "unit_price": 5.5, "payment_days": 60, "index_clause": weak})
    state = control.observe(case, [ask, reply], {})
    assert state["unadopted_terms"]["payment_days=90"] == 1
