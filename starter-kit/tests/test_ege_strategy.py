"""Exercise the actual SDK tool loop against scripted HTTP responses: no model/network/quota.

These checks distinguish strategy freedom from contract validation, including unseen suppliers,
retrieval, a rejected move corrected in the same turn, model failure and late tools.
"""

import copy
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from arena_kit.data import DataPackage
from csee import localsim, runlog, variants
from csee.agents import ege
from csee.agents.ege import EgeAgent, Move, Plan
from csee.agents.strategy_support import EvidenceDesk
from csee.datapkg import shared
from csee.runner import play_case

httpx = pytest.importorskip("httpx2")
pytest.importorskip("anthropic")

ROOT = Path(__file__).parents[2]
CASES = json.loads((ROOT / "starter-kit/csee/cases/practice.json").read_text())


@pytest.fixture(scope="module")
def package():
    pkg = shared(DataPackage(ROOT / "data"))
    pkg.lookup("")
    return pkg


def setup(package, cid="case:P01", unknown=False, status="open"):
    case = copy.deepcopy(next(c for c in CASES if c["case_id"] == cid))
    if unknown:
        case.update(
            case_id="case:UNSEEN",
            suppliers=["sup:79999"],
            parts=["part:399999"],
            refs=[],
            title="A new supplier announces a price increase",
            trigger_doc="doc:new-letter",
            briefing="",
        )
        case["facts"] = {
            "cost:399999": {"unit_cost": 120.0, "supplier": "sup:79999"},
            "doc:new-letter": {"supplier": "sup:79999", "days": 30, "body": "We can discuss payment flexibility."},
            "ctr:new-contract": {"supplier": "sup:79999", "days": 90},
        }
    sid = case["suppliers"][0]
    price = {"case:P01": 138.55, "case:P02": 370.96, "case:P07": 5.74}.get(cid, 370.96)
    terms = {"unit_price": price, "payment_days": 30}
    if cid == "case:P01":
        terms["effective_date"] = "2026-11-01"
    elif cid == "case:P07":
        terms["contract_months"] = 12
    else:
        terms["index_clause"] = None
    events = [
        {
            "from": "supplier",
            "status": status,
            "body": "Our offer remains valid for thirty days.",
            "term_sheets": [{"term_sheet_id": "offer:new-0", "terms": terms}],
            "attachments": [],
        }
    ]
    threads = {sid: events}
    agent = EgeAgent(package, params=variants.params("v9"))
    agent.prepare(case, threads)
    agent.llm = True
    return agent, case, sid, threads


def plan(**overrides):
    return {
        "goal": "Find an achievable deal while protecting supply",
        "unknowns": ["Supplier reservation package"],
        "next_probe": "Explore payment flexibility",
        **overrides,
    }


def tool(name, inputs, call_id="call-1"):
    return {"type": "tool_use", "id": call_id, "name": name, "input": inputs}


class ScriptedModel:
    """Real Anthropic client/tool runner; only its HTTP transport is replaced."""

    def __init__(self, monkeypatch, steps):
        anthropic = pytest.importorskip("anthropic")
        self.requests, self.steps = [], iter(steps)

        def handle(request):
            payload = json.loads(request.content)
            self.requests.append(payload)
            step = next(self.steps)
            blocks = step(payload) if callable(step) else step
            return httpx.Response(
                200,
                json={
                    "id": f"msg-{len(self.requests)}",
                    "type": "message",
                    "role": "assistant",
                    "model": "offline-test",
                    "content": blocks,
                    "stop_reason": "tool_use",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 100, "output_tokens": 30},
                },
            )

        self.client = anthropic.Anthropic(
            api_key="offline-test", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handle))
        )
        monkeypatch.setattr(ege, "client", lambda: self.client)


def confirm_review(payload):
    """A scripted model response after inspecting the deterministic review."""
    results = payload["messages"][-1]["content"]
    review = json.loads(next(block["content"] for block in results if block["type"] == "tool_result"))
    assert review["review_required"] and review["report"]["kind"] == "deterministic_economics_review"
    proposal = next(
        block["input"]
        for block in payload["messages"][-2]["content"]
        if block["type"] == "tool_use" and block["name"] == "submit_move"
    )
    return [
        tool(
            "submit_move",
            {
                **proposal,
                "review_id": review["review_id"],
                "assessment": {
                    "economics": "I compared the calculated packages, standing offer and actual alternative.",
                    "evidence": "Supplier willingness is unknown; cost comparisons are not acceptance predictions.",
                    "levers": {
                        item[
                            "field"
                        ]: "This trade is untested; the risk of another counter outweighs its potential gain."
                        for item in review["report"]["material_levers"]
                    },
                    "next_step": "Proceed with this move after considering the remaining time and supplier response.",
                    "probes": [
                        {
                            "probe_id": probe_id,
                            "action": "decline",
                            "reason": "I decline these additional trades in this scripted confirmation scenario.",
                        }
                        for probe_id in review["report"]["probe_review"]["required_ids"]
                    ],
                },
            },
            "confirm",
        )
    ]


def test_real_tool_loop_corrects_contract_then_preserves_a_concession(package, monkeypatch):
    agent, case, sid, threads = setup(package)
    case["buyer"]["must_haves"] = [{"field": "unit_price", "op": "<=", "value": 138.0}]
    agent.threads[sid].our_prices = [130.0]

    def corrected(payload):
        results = payload["messages"][-1]["content"]
        assert any("must-have" in str(block) for block in results)
        return [
            tool(
                "submit_move",
                {
                    "action": "counter",
                    "term_sheets": [{"unit_price": 137.0, "payment_days": 60, "effective_date": "2027-01-01"}],
                    "opening": "Could a shorter payment period help you improve the price?",
                    "plan": plan(),
                },
                "fixed",
            )
        ]

    model = ScriptedModel(
        monkeypatch,
        [
            [tool("submit_move", {"action": "counter", "term_sheets": [{"unit_price": 145.0}], "plan": plan()})],
            corrected,
            confirm_review,
        ],
    )
    message = agent.thread_move(case, threads, sid)
    assert len(model.requests) == 3
    assert message["term_sheets"][0]["terms"] == {
        "unit_price": 137.0,
        "payment_days": 60,
        "effective_date": "2027-01-01",
    }
    assert "shorter payment" in message["body"] and agent.plans[sid]["goal"]


def test_unknown_supplier_can_discover_and_build_a_new_argument(package, monkeypatch):
    agent, case, sid, threads = setup(package, unknown=True)
    # Remove precomputed arguments: the model has to discover evidence, not select a baseline argument.
    agent.threads[sid].intel.claims = []

    def after_search(payload):
        assert "doc:new-letter" in str(payload["messages"][-1])
        return [tool("read_document", {"data_id": "doc:new-letter"}, "read")]

    def after_read(payload):
        assert "payment flexibility" in str(payload["messages"][-1])
        return [
            tool("build_argument", {"kind": "notice_period", "refs": ["doc:new-letter", "ctr:new-contract"]}, "build")
        ]

    def after_build(payload):
        results = payload["messages"][-1]["content"]
        result = json.loads(next(block["content"] for block in results if block["type"] == "tool_result"))
        return [
            tool(
                "submit_move",
                {
                    "action": "counter",
                    "term_sheets": [{"unit_price": 134.0}],
                    "argument_keys": [result["argument_key"]],
                    "plan": plan(
                        hypotheses=[
                            {
                                "statement": "Notice is shorter than the contract requires",
                                "confidence": "high",
                                "evidence_refs": ["doc:new-letter", "ctr:new-contract"],
                            }
                        ]
                    ),
                },
                "submit",
            )
        ]

    model = ScriptedModel(
        monkeypatch,
        [
            [tool("search_evidence", {"query": "payment"})],
            after_search,
            after_read,
            after_build,
            confirm_review,
        ],
    )
    message = agent.thread_move(case, threads, sid)
    assert len(model.requests) == 5
    assert "30 days' notice" in message["body"] and "90 days" in message["body"]
    assert message["refs"] == ["doc:new-letter", "ctr:new-contract"]
    assert not any("70110" in ref for ref in message["refs"])


@pytest.mark.parametrize("action", ["ready", "accept"])
def test_model_stops_while_baseline_would_counter(package, monkeypatch, action):
    agent, case, sid, threads = setup(package)
    assert agent.rule_move(case, threads, sid)
    ScriptedModel(monkeypatch, [[tool("submit_move", {"action": action, "plan": plan()})], confirm_review])
    message = agent.thread_move(case, threads, sid)
    assert message is None if action == "ready" else message["action"]["type"] == "accept"
    assert agent.threads[sid].ready


def test_full_negotiation_exercises_model_branch_with_unknown_supplier(package, monkeypatch, tmp_path):
    agent, case, sid, _ = setup(package, unknown=True)
    table = localsim.LocalTable(case, package, seed=1)
    model = ScriptedModel(
        monkeypatch,
        [
            [
                tool(
                    "submit_move",
                    {
                        "action": "counter",
                        "term_sheets": [{"unit_price": 135.0, "effective_date": "2027-04-01", "payment_days": 60}],
                        "plan": plan(),
                    },
                )
            ],
            confirm_review,
            [tool("submit_move", {"action": "accept"}, "accept")],
            confirm_review,
        ],
    )
    run = runlog.Run("ege", "sim", root=tmp_path)
    result = play_case(table, case["case_id"], agent, run=run)
    run.end()
    assert result["deal"] and len(model.requests) == 4
    events = [json.loads(line) for line in next(run.dir.glob("case_*.jsonl")).read_text().splitlines()]
    assert sum(event["type"] == "agent_move" for event in events) == 2
    assert sum(event["type"] == "strategy_applied" for event in events) == 2


def test_model_sees_package_review_and_can_revise_instead_of_confirming(package, monkeypatch):
    agent, case, sid, threads = setup(package, "case:P07")
    threads[sid][0]["term_sheets"][0]["terms"].update(unit_price=5.56, contract_months=24)
    first = {"action": "counter", "term_sheets": [{"unit_price": 5.50, "payment_days": 30}], "plan": plan()}
    reviews = []

    def revise(payload):
        review = json.loads(payload["messages"][-1]["content"][0]["content"])
        assert review["review_required"]
        payment = next(item for item in review["report"]["material_levers"] if item["field"] == "payment_days")
        assert payment["best_lower_cost_option"]["mathematical_saving"] == 4448
        assert review["report"]["proposed_packages"][0]["terms"]["payment_days"] == 30
        assert sid not in agent.plans and not agent.used_ids  # The draft had no binding effect.
        reviews.append(review["review_id"])
        return [tool("submit_move", {**first, "term_sheets": [{"unit_price": 5.50, "payment_days": 90}]}, "revise")]

    def revised_review(payload):
        review = json.loads(payload["messages"][-1]["content"][0]["content"])
        assert review["review_id"] != reviews[0]
        return confirm_review(payload)

    model = ScriptedModel(monkeypatch, [[tool("submit_move", first)], revise, revised_review])
    message = agent.thread_move(case, threads, sid)
    assert len(model.requests) == 3 and message["term_sheets"][0]["terms"]["payment_days"] == 90
    schema = next(item for item in model.requests[0]["tools"] if item["name"] == "submit_move")["input_schema"]
    assert "statement" in str(schema) and "economics" in str(schema)  # Nested plan/assessment are typed.


def test_unconfirmed_or_revised_draft_cannot_execute(package):
    agent, case, sid, threads = setup(package)
    desk, reviews, stop = EvidenceDesk(case, package, sid, threads), {}, threading.Event()
    draft = {"action": "counter", "term_sheets": [{"unit_price": 135.0}], "plan": plan()}
    move, review = agent.review_submission(case, threads, sid, draft, {}, desk, reviews, stop)
    assert move is None and review["review_required"] and sid not in agent.plans
    assessment = {
        "economics": "The draft improves cost relative to the standing offer and the alternative.",
        "evidence": "Supplier acceptance remains unknown despite the mathematical improvement.",
        "next_step": "Test this package with the supplier and inspect the next response.",
        "probes": [
            {
                "probe_id": probe_id,
                "action": "decline",
                "reason": "This test checks confirmation mechanics; I decline the additional trades.",
            }
            for probe_id in review["report"]["probe_review"]["required_ids"]
        ],
    }
    confirmed = {**draft, "review_id": review["review_id"], "assessment": assessment}
    move, result = agent.review_submission(case, threads, sid, confirmed, {}, desk, reviews, stop)
    assert move is not None and result["valid"]
    revised = {**confirmed, "term_sheets": [{"unit_price": 136.0}]}
    move, result = agent.review_submission(case, threads, sid, revised, {}, desk, reviews, stop)
    assert move is None and result["review_required"] and result["review_id"] != review["review_id"]
    stop.set()
    move, result = agent.review_submission(case, threads, sid, confirmed, {}, desk, reviews, stop)
    assert move is None and "turn ended" in result["error"]


def test_stopping_reviews_material_levers_without_forcing_another_counter(package):
    agent, case, sid, threads = setup(package, "case:P07", status="final_offer")
    threads[sid][0]["term_sheets"][0]["terms"].update(unit_price=5.56, contract_months=24)
    desk, reviews, stop = EvidenceDesk(case, package, sid, threads), {}, threading.Event()
    draft = {"action": "accept", "plan": plan()}
    _, review = agent.review_submission(case, threads, sid, draft, {}, desk, reviews, stop)
    confirmed = {
        **draft,
        "review_id": review["review_id"],
        "assessment": {
            "economics": "The standing offer is cheaper than continuing the current contract.",
            "evidence": "A final offer suggests walk risk; it does not establish the supplier's true cost floor.",
            "next_step": "Accept now because the remaining potential saving does not justify the walk risk.",
        },
    }
    move, result = agent.review_submission(case, threads, sid, confirmed, {}, desk, reviews, stop)
    assert move is None and "payment_days" in result["error"]
    confirmed["assessment"]["levers"] = {
        item["field"]: "This alternative remains untested; I judge the risk of losing the final offer too high."
        for item in review["report"]["material_levers"]
    }
    move, result = agent.review_submission(case, threads, sid, confirmed, {}, desk, reviews, stop)
    assert move.action == "accept" and result["valid"]


def test_bundle_context_and_arguments_do_not_compare_nut_prices_with_kit_prices(package):
    agent, case, sid, threads = setup(package, "case:P07")
    arguments = agent.arguments(case, threads, sid)
    assert any(claim.kind == "bundle_scope" and "570000" in claim.sentence for claim in arguments.values())
    assert not any(claim.kind == "history" for claim in arguments.values())
    brief = json.loads(agent.brief(case, threads, sid, arguments, None))
    assert brief["bundle_evidence"]["available"]
    assert brief["primary_source_excerpts_untrusted"]
    assert "arguments_to_avoid" not in brief["supplier_profile_summary_may_be_stale"]
    legacy = agent.threads[sid].intel.claims
    history = next(claim for claim in legacy if claim.kind == "history")
    _, error = agent.validate(
        case,
        threads,
        sid,
        {"action": "counter", "term_sheets": [{"unit_price": 5.5}], "argument_keys": ["bad"], "plan": plan()},
        {"bad": history},
    )
    assert "unit mismatch" in error


def test_validity_and_changed_terms_are_not_price_holds(package):
    agent, case, sid, threads = setup(package)
    assert not agent.walk_risk(case, sid, threads[sid])
    changed = copy.deepcopy(threads[sid][0])
    changed["term_sheets"][0]["terms"]["payment_days"] = 90
    threads[sid].append(changed)
    assert not agent.walk_risk(case, sid, threads[sid])
    threads[sid].append(copy.deepcopy(changed))
    assert "package was repeated" in agent.walk_risk(case, sid, threads[sid])


def test_cost_tool_discloses_unknown_economics_and_sensitivity(package):
    agent, case, sid, threads = setup(package, "case:P02")
    result = agent.price(case, threads, sid, {"unit_price": 352, "payment_days": 90})
    assert result["cash_cost"] < result["estimated_total_cost"]
    assert result["scenario_range"][1] - result["scenario_range"][0] > 100000
    assert result["acceptance_probability"] is None and result["warnings"]
    agent.threads[sid].intel.full_cost = None
    missing = agent.price(case, threads, sid, {})
    assert missing["scenario_range"] is None and "omitted" in missing["warnings"][-1]


@pytest.mark.parametrize(
    "sheet",
    [
        {"unit_price": float("nan")},
        {"unit_price": float("inf")},
        {"unit_price": True},
        {"unit_price": 0},
        {"unit_price": -1},
        {"unit_price": 135, "payment_days": 91},
        {"unit_price": 135, "tooling_eur": 100},
        {"unit_price": 135, "effective_date": "tomorrow"},
        {"unit_price": 135, "payment_days": float("nan")},
        {"unit_price": 135, "payment_days": None},
        {"unit_price": 135, "payment_days": 30.5},
    ],
)
def test_invalid_contracts_receive_errors_not_silent_changes(package, sheet):
    agent, case, sid, threads = setup(package)
    _, errors = agent.validate(case, threads, sid, {"action": "counter", "term_sheets": [sheet], "plan": plan()}, {})
    assert errors


def test_alternative_acceptance_and_bad_deal_are_rejected(package):
    agent, case, sid, threads = setup(package)
    _, error = agent.validate(
        case, threads, sid, {"action": "accept", "offer_id": "offer:alternative", "plan": plan()}, {}
    )
    assert "FIRST" in error
    threads[sid][0]["term_sheets"][0]["terms"]["unit_price"] = 1000
    _, error = agent.validate(case, threads, sid, {"action": "accept", "plan": plan()}, {})
    assert "alternative" in error


def test_plan_updates_require_known_evidence_and_a_revision_reason(package):
    agent, case, sid, threads = setup(package)
    for proposed, expected in [
        (plan(hypotheses=[{"statement": "Supplier needs cash", "confidence": "high"}]), "evidence_refs"),
        (
            plan(
                hypotheses=[
                    {"statement": "Supplier needs cash", "confidence": "high", "evidence_refs": ["doc:invented"]}
                ]
            ),
            "unknown plan evidence",
        ),
    ]:
        _, errors = agent.validate(case, threads, sid, {"action": "ready", "plan": proposed}, {})
        assert expected in errors
    agent.plans[sid] = Plan(**plan()).model_dump()
    revised = plan(target_cost=1000000)
    _, errors = agent.validate(case, threads, sid, {"action": "ready", "plan": revised}, {})
    assert "revision_reason" in errors
    revised["revision_reason"] = "The latest reply changes the available trade."
    _, errors = agent.validate(case, threads, sid, {"action": "ready", "plan": revised}, {})
    assert errors is None


def test_source_precedence_attachment_paging_and_read_only_bounded_queries(package):
    agent, case, sid, threads = setup(package)
    ref = "sc:70110@2026Q3"
    case["facts"] = {ref: {"supplier": sid, "ppm": 777}}
    threads[sid][0]["attachments"] = [
        {
            "attachment_id": "quote:new",
            "name": "quote-new.pdf",
            "text": "x" * 6500 + "New financing evidence after the excerpt",
        }
    ]
    desk = EvidenceDesk(case, package, sid, threads)
    assert "777 ppm" in desk.build_argument("scorecard", [ref], "ppm").sentence
    assert "New financing evidence" in desk.document("attachment:quote:new", 6000)["text"]
    with pytest.raises(ValueError, match="unknown evidence"):
        desk.document("../../.env")
    with pytest.raises(ValueError, match="read-only"):
        desk.query("DELETE FROM suppliers")
    assert len(desk.query("SELECT * FROM suppliers")) == 30
    t0 = time.monotonic()
    with pytest.raises(ValueError, match="time budget"):
        desk.query(
            "WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x WHERE n<1000000000) SELECT sum(n) FROM x"
        )
    assert time.monotonic() - t0 < 2


def test_all_arguments_reject_wrong_supplier_or_stale_index_window(package):
    agent, case, sid, threads = setup(package)
    desk = EvidenceDesk(case, package, sid, threads)
    with pytest.raises(ValueError, match="another supplier"):
        desk.build_argument("scorecard", ["sc:70510@2026Q3"], "ppm")
    with pytest.raises(ValueError, match="twelve months"):
        desk.build_argument("index_change", ["idx:CU-NOTATION@2024-01", "idx:CU-NOTATION@2026-08"])


def test_timed_out_model_cannot_commit_plan_claims_or_late_tools(package, monkeypatch):
    agent, case, sid, threads = setup(package)
    release, finished = threading.Event(), threading.Event()
    late_results = []
    monkeypatch.setattr(agent, "budget", lambda: 1.0)

    def delayed(case, threads, sid, brief, tools, arguments, desk, out, stop, t0, budget, reviews=None):
        release.wait(3)
        builder = next(tool for tool in tools if tool.name == "build_argument")
        late_results.append(json.loads(builder.func("scorecard", ["sc:70110@2026Q3"], "ppm")))
        out["move"] = Move(action="ready", plan=Plan(**plan(goal="Late plan must not commit")))
        finished.set()

    monkeypatch.setattr(agent, "run_turns", delayed)
    try:
        message = agent.thread_move(case, threads, sid)
        before = set(agent.used_ids)
        assert message["term_sheets"] and sid not in agent.plans
    finally:
        release.set()
    assert finished.wait(2)
    assert "turn ended" in late_results[0]["error"] and agent.used_ids == before


def test_model_failure_uses_template_fallback(package, monkeypatch):
    agent, case, sid, threads = setup(package)

    def broken(*args, **kwargs):
        raise RuntimeError("scripted model failure")

    monkeypatch.setattr(agent, "run_turns", broken)
    message = agent.thread_move(case, threads, sid)
    assert message["term_sheets"] and "_write" not in message
    assert sid not in agent.plans


def test_low_time_budget_does_not_start_model(package, monkeypatch):
    agent, case, sid, threads = setup(package)
    agent.cap_at = lambda: time.time() + 1

    def unexpected(*args, **kwargs):
        pytest.fail("model must not start when the wave is closing")

    monkeypatch.setattr(agent, "run_turns", unexpected)
    assert agent.thread_move(case, threads, sid)["term_sheets"]


def test_supplier_standard_value_is_not_silently_snapped(package):
    agent, case, sid, threads = setup(package)
    # The API allows a supplier's standard value as well as the advertised case options.
    case["term_options"]["payment_days"] = [30, 90]
    threads[sid][0]["term_sheets"][0]["terms"]["payment_days"] = 45
    move = Move(action="counter", term_sheets=[{"unit_price": 135.0, "payment_days": 45}], plan=Plan(**plan()))
    result = agent.apply(case, threads, sid, move, None, {})
    assert result["term_sheets"][0]["terms"]["payment_days"] == 45
    assert "45 days" in result["body"]


def test_fixed_price_case_can_negotiate_other_terms(package):
    agent, case, sid, threads = setup(package)
    case["negotiable"].remove("unit_price")
    case["fixed_terms"]["unit_price"] = 135.0
    threads[sid][0]["term_sheets"][0]["terms"].pop("unit_price")
    move = Move(action="counter", term_sheets=[{"payment_days": 60}], plan=Plan(**plan()))
    result = agent.apply(case, threads, sid, move, None, {})
    assert "unit_price" not in result["term_sheets"][0]["terms"]
    assert "135.00" in result["body"]
    accepted = agent.apply(case, threads, sid, Move(action="accept"), None, {})
    assert accepted["action"] == {"type": "accept", "term_sheet_id": "offer:new-0"}


@pytest.mark.parametrize("with_model", [False, True])
def test_sim_cli_exercises_the_requested_branch_without_a_silent_comparison(monkeypatch, with_model):
    # Isolate the ledger import so testing CLI parsing cannot create experiment snapshots/records.
    import csee

    rows, factories = [], []
    ledger = ModuleType("csee.ledger")
    ledger.commit = lambda: "offline-test"
    ledger.board = lambda values, *args: rows.extend(values) or "scripted board"
    ledger.label = lambda row: row["agent"]
    monkeypatch.setitem(sys.modules, "csee.ledger", ledger)
    monkeypatch.setattr(csee, "ledger", ledger, raising=False)
    spec = importlib.util.spec_from_file_location("csee._strategy_cli_test", ROOT / "starter-kit/csee/__main__.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setattr(localsim, "cases", lambda: [CASES[0]])
    monkeypatch.setattr(localsim, "LocalTable", lambda *args: object())
    monkeypatch.setattr(cli, "play_case", lambda *args, **kwargs: {"score": 0.5})

    def factory(use_llm, variant, agent):
        factories.append(use_llm)
        factory.llm = use_llm
        return lambda: SimpleNamespace(pkg=None, llm=use_llm)

    monkeypatch.setattr(cli, "agent_factory", factory)
    command = ["--no-runlog", "--agent", "ege", "sim", "--seeds", "1"]
    if with_model:
        command.append("--llm")
    cli.main(command)
    assert factories == [with_model] and rows[0]["llm"] is with_model

    if with_model:

        def missing(*args):
            missing.llm = False
            return lambda: SimpleNamespace(pkg=None, llm=False)

        monkeypatch.setattr(cli, "agent_factory", missing)
        with pytest.raises(SystemExit, match="refusing a silent"):
            cli.main(command)
