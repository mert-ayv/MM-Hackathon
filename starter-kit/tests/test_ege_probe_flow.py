"""Probe promises survive turns and require a test or explicit cancellation, entirely offline."""

import copy
import json
import threading

import pytest
from test_ege_strategy import ROOT, ScriptedModel, plan, setup, tool

from arena_kit.data import DataPackage
from csee.agents.strategy_support import EvidenceDesk
from csee.datapkg import shared


@pytest.fixture(scope="module")
def package():
    package = shared(DataPackage(ROOT / "data"))
    package.lookup("")
    return package


def kit(package):
    agent, case, sid, threads = setup(package, "case:P07")
    threads[sid][0]["term_sheets"][0]["terms"].update(
        unit_price=5.56, payment_days=60, contract_months=24
    )
    return agent, case, sid, threads


def draft(price=5.4, *, sheets=None, first=False, action="counter"):
    move = {"action": action}
    if action == "counter":
        move["term_sheets"] = sheets or [{"unit_price": price, "payment_days": 60, "contract_months": 24}]
    if first:
        move["plan"] = plan()
    return move


def initial_review(agent, case, sid, threads, move):
    desk, reviews, stop = EvidenceDesk(case, agent.pkg, sid, threads), {}, threading.Event()
    checked, feedback = agent.review_submission(case, threads, sid, move, {}, desk, reviews, stop)
    assert checked is None and feedback["review_required"]
    assert feedback["report"]["probe_review"]["kind"] == "probe_follow_through_review"
    return desk, reviews, stop, feedback


def payment_probe(feedback):
    return next(
        item
        for item in feedback["report"]["probe_review"]["opportunities"]
        if item["field"] == "payment_days" and item["target_value"] == 90
    )


def confirmation(move, feedback, *, payment_action=None):
    probe_review = feedback["report"]["probe_review"]
    required = set(probe_review["required_ids"])
    selected = {
        item["probe_id"]: {
            "probe_id": item["probe_id"],
            "action": "decline",
            "reason": "I choose not to pursue this option because of the present negotiation risk.",
        }
        for item in probe_review["opportunities"]
        if item["probe_id"] in required
    }
    if payment_action:
        item = payment_probe(feedback)
        selected[item["probe_id"]] = {
            "probe_id": item["probe_id"],
            "action": payment_action,
            "reason": {
                "defer": "Test this payment option on the next buyer decision after observing the price response.",
                "test_now": "Include the exact payment option in an actual package and inspect the supplier response.",
                "decline": "Cancel the planned test because preserving this offer now outweighs its possible gain.",
            }[payment_action],
        }
    return {
        **move,
        "review_id": feedback["review_id"],
        "assessment": {
            "economics": "I compared each package with the standing offer and the published alternative cost.",
            "evidence": "Supplier willingness remains unknown; a financial saving does not imply acceptance.",
            "levers": {
                item["field"]: "This option remains uncertain; I considered its financial value and negotiation risk."
                for item in feedback["report"]["material_levers"]
            },
            "next_step": "Proceed with this chosen move and resolve the recorded payment probe on the next decision.",
            "probes": list(selected.values()),
        },
    }


def confirm(agent, case, sid, threads, context, move, *, payment_action=None):
    desk, reviews, stop, feedback = context
    raw = confirmation(move, feedback, payment_action=payment_action)
    return agent.review_submission(case, threads, sid, raw, {}, desk, reviews, stop)


def apply(agent, case, sid, threads, move):
    message = agent.apply(case, threads, sid, move, None, {})
    assert message is not False
    return message


def reply_after(threads, sid, message, price, number, status="open"):
    threads[sid].extend(
        [
            {"from": "buyer", **message},
            {
                "from": "supplier",
                "status": status,
                "body": "We adjusted price; payment remains as quoted.",
                "term_sheets": [
                    {
                        "term_sheet_id": f"offer:probe-{number}",
                        "terms": {"unit_price": price, "payment_days": 60, "contract_months": 24},
                    }
                ],
                "attachments": [],
            },
        ]
    )


def defer_first(agent, case, sid, threads):
    first = draft(first=True)
    context = initial_review(agent, case, sid, threads, first)
    probe_id = payment_probe(context[3])["probe_id"]
    checked, result = confirm(agent, case, sid, threads, context, first, payment_action="defer")
    assert checked is not None and result["valid"]
    assert not agent.probe_states.get(sid)  # A valid confirmation still has no binding side effects.
    message = apply(agent, case, sid, threads, checked)
    assert agent.probe_states[sid][probe_id]["status"] == "pending"
    return message, probe_id


@pytest.mark.parametrize("resolution", ["test_now", "decline"])
def test_price_only_followups_cannot_keep_deferring_the_same_payment_probe(package, resolution):
    agent, case, sid, threads = kit(package)
    first, probe_id = defer_first(agent, case, sid, threads)
    reply_after(threads, sid, first, 5.46, 1)
    second = draft(5.38)
    context = initial_review(agent, case, sid, threads, second)
    assert probe_id in context[3]["report"]["probe_review"]["required_ids"]
    before = copy.deepcopy(agent.probe_states)
    checked, result = confirm(agent, case, sid, threads, context, second, payment_action="defer")
    assert checked is None and result.get("error")
    assert agent.probe_states == before

    if resolution == "test_now":
        # A secondary package is a real probe; the primary package may retain the preferred payment.
        second = draft(
            sheets=[
                {"unit_price": 5.38, "payment_days": 60, "contract_months": 24},
                {"unit_price": 5.4, "payment_days": 90, "contract_months": 24},
            ]
        )
        context = initial_review(agent, case, sid, threads, second)
    checked, result = confirm(agent, case, sid, threads, context, second, payment_action=resolution)
    assert checked is not None and result["valid"]
    second_message = apply(agent, case, sid, threads, checked)
    expected = "attempted" if resolution == "test_now" else "declined"
    assert agent.probe_states[sid][probe_id]["status"] == expected
    if resolution == "test_now":
        assert second_message["term_sheets"][1]["terms"]["payment_days"] == 90

    reply_after(threads, sid, second_message, 5.42, 2)
    third = draft(5.37)
    context = initial_review(agent, case, sid, threads, third)
    assert not any(item["probe_id"] == probe_id for item in context[3]["report"]["probe_review"]["pending"])
    if resolution == "test_now":
        assert probe_id not in context[3]["report"]["probe_review"]["required_ids"]
    # An untested declined lever may need a fresh explicit disposition; declining never forces a test.
    checked, result = confirm(agent, case, sid, threads, context, third)
    assert checked is not None and result["valid"]
    assert apply(agent, case, sid, threads, checked)["term_sheets"][0]["terms"]["unit_price"] == 5.37


def test_pending_probe_can_be_cancelled_to_accept_a_final_offer_without_another_counter(package):
    agent, case, sid, threads = kit(package)
    message, probe_id = defer_first(agent, case, sid, threads)
    reply_after(threads, sid, message, 5.42, 1, status="final_offer")
    stopping = draft(action="accept")
    context = initial_review(agent, case, sid, threads, stopping)
    assert probe_id in context[3]["report"]["probe_review"]["required_ids"]
    checked, result = confirm(agent, case, sid, threads, context, stopping, payment_action="decline")
    assert checked is not None and result["valid"]
    accepted = apply(agent, case, sid, threads, checked)
    assert accepted["action"]["type"] == "accept"
    assert agent.probe_states[sid][probe_id]["status"] == "declined"


def test_draft_and_expired_confirmation_do_not_persist_probe_promises(package):
    agent, case, sid, threads = kit(package)
    move = draft(first=True)
    context = initial_review(agent, case, sid, threads, move)
    assert not agent.probe_states.get(sid)
    context[2].set()
    checked, result = confirm(agent, case, sid, threads, context, move, payment_action="defer")
    assert checked is None and "turn ended" in result["error"]
    assert not agent.probe_states.get(sid)


def test_failed_apply_does_not_persist_a_confirmed_probe(package, monkeypatch):
    agent, case, sid, threads = kit(package)
    move = draft(first=True)
    context = initial_review(agent, case, sid, threads, move)
    checked, result = confirm(agent, case, sid, threads, context, move, payment_action="defer")
    assert checked is not None and result["valid"]

    def fail_render(*args, **kwargs):
        raise ValueError("Cannot render this package")

    monkeypatch.setattr(agent, "render", fail_render)
    assert agent.apply(case, threads, sid, checked, None, {}) is False
    assert not agent.probe_states.get(sid)


def test_probe_state_is_supplier_local_and_prepare_clears_the_case(package):
    agent, case, sid, threads = kit(package)
    other = "sup:79998"
    case["suppliers"].append(other)
    threads[other] = copy.deepcopy(threads[sid])
    agent.prepare(case, threads)
    defer_first(agent, case, sid, threads)
    assert agent.probe_states[sid]
    assert not agent.probe_states.get(other)
    other_context = initial_review(agent, case, other, threads, draft(first=True))
    assert not other_context[3]["report"]["probe_review"]["pending"]
    agent.prepare(case, threads)
    assert not any(agent.probe_states.values())


@pytest.mark.parametrize("replay_scope", ["same_case_reset", "different_case", "different_supplier"])
def test_confirmed_probe_move_cannot_commit_after_reset_or_to_another_supplier(package, replay_scope):
    agent, case, sid, threads = kit(package)
    other = "sup:79998"
    if replay_scope == "different_supplier":
        case["suppliers"].append(other)
        threads[other] = copy.deepcopy(threads[sid])
        agent.prepare(case, threads)
    move = draft(first=True)
    context = initial_review(agent, case, sid, threads, move)
    checked, result = confirm(agent, case, sid, threads, context, move, payment_action="defer")
    assert checked is not None and result["valid"]
    if replay_scope == "different_case":
        case["case_id"] = "case:new-session"
    if replay_scope != "different_supplier":
        agent.prepare(case, threads)
    target_sid = other if replay_scope == "different_supplier" else sid
    before = copy.deepcopy(agent.probe_states)
    assert agent.apply(case, threads, target_sid, checked, None, {}) is False
    assert agent.probe_states == before


def test_claim_consumed_after_confirmation_cannot_commit_a_probe_promise(package):
    agent, case, sid, threads = kit(package)
    arguments = agent.arguments(case, threads, sid)
    key = next(iter(arguments))
    move = {**draft(first=True), "argument_keys": [key]}
    desk, reviews, stop = EvidenceDesk(case, agent.pkg, sid, threads), {}, threading.Event()
    _, feedback = agent.review_submission(case, threads, sid, move, arguments, desk, reviews, stop)
    assert feedback["review_required"]
    raw = confirmation(move, feedback, payment_action="defer")
    checked, result = agent.review_submission(case, threads, sid, raw, arguments, desk, reviews, stop)
    assert checked is not None and result["valid"]
    # Another supplier thread can consume shared evidence after this decision has been confirmed.
    agent.used_ids.add(arguments[key].ids[0])
    before = copy.deepcopy(agent.probe_states)
    assert agent.apply(case, threads, sid, checked, None, arguments) is False
    assert agent.probe_states == before


def test_real_sdk_review_defers_a_probe_only_after_confirmed_apply(package, monkeypatch):
    agent, case, sid, threads = kit(package)
    first = draft(first=True)
    seen = []

    def confirm_feedback(payload):
        result = next(item for item in payload["messages"][-1]["content"] if item["type"] == "tool_result")
        feedback = json.loads(result["content"])
        assert feedback["review_required"]
        assert not agent.probe_states.get(sid)
        seen.append(payment_probe(feedback)["probe_id"])
        return [tool("submit_move", confirmation(first, feedback, payment_action="defer"), "confirm-probe")]

    model = ScriptedModel(monkeypatch, [[tool("submit_move", first)], confirm_feedback])
    message = agent.thread_move(case, threads, sid)
    assert len(model.requests) == 2
    assert message["term_sheets"][0]["terms"]["payment_days"] == 60
    assert agent.probe_states[sid][seen[0]]["status"] == "pending"
