"""Turn-local reviews and persistent follow-through for model-chosen negotiation probes.

This module neither chooses a strategy nor sends a message. It records whether an exact term
target was requested, deferred once, or declined. A request is evidence of an attempt, never proof
that a supplier can or cannot accept it. Callers commit returned records only after applying a
confirmed move; building a review and resolving a draft are pure operations.
"""

import hashlib
import json
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..agent import standard_terms
from arena_kit.play import ENDED

MAX_PROBES = 12
EPS = 0.02


class ProbeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    probe_id: str = Field(min_length=1, max_length=80)
    action: Literal["test_now", "defer", "decline"]
    reason: str = Field(min_length=20, max_length=600)


def _canonical(value):
    # Integral JSON numbers identify the same term target; booleans retain their own type.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _value_key(value):
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _probe_id(field, value):
    key = json.dumps([field, _canonical(value)], sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "probe:" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _buyer_turn(events):
    """Only supplier-facing buyer messages advance a deferred probe's deadline."""
    return sum(message.get("from") == "buyer" for message in events)


def _sheet_terms(sheet):
    return sheet.get("terms", sheet) if isinstance(sheet, dict) else {}


def _matches(sheets, field, target):
    expected = _value_key(target)
    return any(field in (terms := _sheet_terms(sheet)) and _value_key(terms[field]) == expected for sheet in sheets)


def _was_requested(events, field, target):
    return any(
        message.get("from") == "buyer" and _matches(message.get("term_sheets") or [], field, target)
        for message in events
    )


def _currently_offered(case, events, field, target):
    """Only a live FIRST standing sheet or its actual standard terms fulfils a target."""
    last = next((message for message in reversed(events) if message.get("from") != "buyer"), {})
    sheets = last.get("term_sheets") or []
    if last.get("status") in ENDED or not sheets:
        return False
    # Buyer-plan defaults are not evidence of supplier agreement to a target. Published closing
    # terms use the supplier's standard, then case fixed terms, then the actual first sheet.
    offered = {}
    plan_fields = {"payment_days", "lead_time_days", "volume_per_year", "contract_months", "incoterm"}
    for layer in (standard_terms(events), case.get("fixed_terms", {}), _sheet_terms(sheets[0])):
        offered.update({key: value for key, value in layer.items() if value is not None or key not in plan_fields})
    return field in offered and _value_key(offered[field]) == _value_key(target)


def _comparison(row):
    keep = (
        "basis",
        "field",
        "from",
        "to",
        "source",
        "estimated_total_cost",
        "mathematical_saving",
        "cash_saving",
        "coverage",
    )
    return {key: deepcopy(row[key]) for key in keep if key in row}


def _candidates(case, economics):
    """Best lower-cost and neutral candidates, preferring their standing-offer comparisons."""
    rows = economics.get("one_field_counterfactuals") or []
    found = {}
    for lever in economics.get("material_levers") or []:
        field = lever.get("field")
        if field not in case.get("negotiable", []) or field == "unit_price":
            continue
        candidates = [lever.get("best_lower_cost_option"), *(lever.get("cost_neutral_options") or [])]
        for row in candidates:
            if not isinstance(row, dict) or "to" not in row:
                continue
            target = row["to"]
            comparable = [
                item
                for item in rows
                if item.get("field") == field
                and "to" in item
                and _value_key(item["to"]) == _value_key(target)
                and item.get("mathematical_saving", -1) >= -EPS
            ]
            standing = next((item for item in comparable if item.get("basis") == "standing"), None)
            selected = standing or row
            probe_id = _probe_id(field, target)
            candidate = {
                "probe_id": probe_id,
                "field": field,
                "target_value": deepcopy(target),
                "comparison": _comparison(selected),
                "acceptance": "unknown",
            }
            if probe_id not in found or selected.get("basis") == "standing":
                found[probe_id] = candidate
    return list(found.values())


def build_probe_review(case, threads, sid, economics_report, records):
    """Build JSON feedback without changing records or treating draft packages as sent.

    ``records`` is a per-supplier dict keyed by stable probe IDs. ``current_turn`` counts existing
    buyer messages, so a defer created at turn N becomes due after buyer message N+1 is in history.
    At most twelve IDs are active in a normal review; new candidates are bounded before pending
    obligations. An invalid oversized pending ledger produces an explicit error rather than loss.
    """
    snapshot = deepcopy(records or {})
    events = threads[sid]
    turn = _buyer_turn(events)
    pending = [deepcopy(record) for record in snapshot.values() if record.get("status") == "pending"]
    pending.sort(key=lambda record: (record.get("due_turn", turn), record["probe_id"]))
    review = {
        "kind": "probe_follow_through_review",
        "case_id": case.get("case_id"),
        "supplier_id": sid,
        "current_turn": turn,
        "opportunities": [],
        "pending": pending,
        "required_ids": [],
        "records": snapshot,
        "warnings": [],
        "note": "A mathematical benefit is not an acceptance prediction. An attempted target is not impossible.",
    }
    if len(pending) > MAX_PROBES:
        review["error"] = f"{len(pending)} pending probes exceed the {MAX_PROBES}-ID review bound; none were dropped."
        return review

    proposals = [item.get("terms", {}) for item in economics_report.get("proposed_packages") or []]
    candidates = {item["probe_id"]: item for item in _candidates(case, economics_report)}
    # Keep pending targets even after their economic comparison disappears or a new target is best.
    selected = []
    for record in pending:
        selected.append(
            candidates.pop(
                record["probe_id"],
                {
                    "probe_id": record["probe_id"],
                    "field": record["field"],
                    "target_value": deepcopy(record["target_value"]),
                    "comparison": deepcopy(record.get("comparison", {})),
                    "acceptance": "unknown",
                },
            )
        )
    remaining = list(candidates.values())
    # Previously attempted targets should not hide unexplored opportunities under the review cap.
    remaining.sort(key=lambda item: _was_requested(events, item["field"], item["target_value"]))
    slots = MAX_PROBES - len(selected)
    selected.extend(remaining[:slots])
    if len(remaining) > slots:
        review["warnings"].append(
            f"{len(remaining) - slots} new candidates omitted by the {MAX_PROBES}-ID bound; "
            "all pending probes retained."
        )

    counter = economics_report.get("action") == "counter"
    for item in selected:
        previous = snapshot.get(item["probe_id"], {})
        requested = _was_requested(events, item["field"], item["target_value"])
        proposed = _matches(proposals, item["field"], item["target_value"])
        offered = _currently_offered(case, events, item["field"], item["target_value"])
        # apply() can construct a message that the transport later drops. A ledger entry alone
        # does not establish an actual request or a continuing supplier offer.
        unobserved = previous.get("status") in ("attempted", "fulfilled") and not requested and not offered
        item.update(
            {
                "status": "fulfilled"
                if offered
                else "attempted"
                if requested
                else ("untested" if unobserved else previous.get("status", "untested")),
                "previously_requested": requested,
                "proposed_now": proposed,
                "currently_offered": offered,
                "deferred_once": previous.get("deferred_once", False),
                "due_turn": previous.get("due_turn"),
            }
        )
        review["opportunities"].append(item)
        unresolved = not requested and not proposed and not offered
        pending_required = previous.get("status") == "pending" and (
            not counter or turn >= previous.get("due_turn", turn)
        )
        if unresolved and ((counter and item["status"] != "attempted") or pending_required):
            review["required_ids"].append(item["probe_id"])
    return review


def resolve_probes(case, threads, sid, probe_review, decisions, sheets, action):
    """Validate confirmation and return new records, never mutating the review or caller state.

    Call with complete outgoing sheets (plain dictionaries or ``{"terms": ...}`` wrappers).
    ``test_now`` must occur in one of these packages; every alternative counts. Closing actions
    can decline pending probes with a reason and never have to send another counter.
    """
    if probe_review.get("error"):
        return None, probe_review["error"]
    if (
        probe_review.get("case_id") != case.get("case_id")
        or probe_review.get("supplier_id") != sid
        or probe_review.get("current_turn") != _buyer_turn(threads[sid])
    ):
        return None, "probe review is stale or belongs to another case/supplier; request a fresh review"
    if action not in ("counter", "accept", "ready", "walk_away"):
        return None, "unknown probe decision action"
    try:
        parsed = [
            decision if isinstance(decision, ProbeDecision) else ProbeDecision.model_validate(decision)
            for decision in (decisions or [])
        ]
    except (ValidationError, TypeError, ValueError) as exc:
        return None, f"invalid probe decision: {exc}"
    if len(parsed) > MAX_PROBES:
        return None, f"at most {MAX_PROBES} probe decisions are allowed"
    by_id = {item.probe_id: item for item in parsed}
    if len(by_id) != len(parsed):
        return None, "provide exactly one decision per probe_id"
    opportunities = {item["probe_id"]: item for item in probe_review.get("opportunities") or []}
    if unknown := set(by_id) - set(opportunities):
        return None, f"unknown probe IDs: {sorted(unknown)}"
    if any(len(item.reason.strip()) < 20 for item in parsed):
        return None, "probe reasons need at least twenty non-padding characters"

    records = deepcopy(probe_review.get("records") or {})
    turn = probe_review["current_turn"]
    completed = set()
    for probe_id, item in opportunities.items():
        old = records.get(probe_id, {})
        previously_requested = _was_requested(threads[sid], item["field"], item["target_value"])
        tested_now = action == "counter" and _matches(sheets or [], item["field"], item["target_value"])
        offered = _currently_offered(case, threads[sid], item["field"], item["target_value"])
        decision = by_id.get(probe_id)
        record = {
            **deepcopy(old),
            "probe_id": probe_id,
            "field": item["field"],
            "target_value": deepcopy(item["target_value"]),
            "created_turn": old.get("created_turn", turn),
            "deferred_once": old.get("deferred_once", False),
            "comparison": deepcopy(item.get("comparison", {})),
        }
        if offered:
            if decision and decision.action == "defer":
                return None, f"{probe_id}: target is already in the first standing offer; do not defer it"
            record.update(
                {
                    "status": "fulfilled",
                    "resolved_turn": turn,
                    "reason": "The exact target is in the first live standing offer or its supplier standard terms.",
                }
            )
            records[probe_id] = record
            completed.add(probe_id)
            continue
        if decision and decision.action == "test_now" and not tested_now:
            return None, f"{probe_id}: test_now must match an actual outgoing package target"
        if previously_requested or tested_now:
            if decision and decision.action != "test_now":
                return None, f"{probe_id}: target is already requested; do not defer or decline the executed test"
            record.update(
                {
                    "status": "attempted",
                    "resolved_turn": turn,
                    "reason": decision.reason
                    if decision
                    else (
                        "This exact target is in an actual buyer package; acceptance remains unknown."
                        if previously_requested
                        else "This exact target is in the confirmed outgoing package; acceptance remains unknown."
                    ),
                }
            )
            records[probe_id] = record
            completed.add(probe_id)
            continue
        if decision is None:
            continue
        if decision.action == "defer":
            if action != "counter":
                return None, f"{probe_id}: closing cannot defer an unresolved probe; decline it with a reason"
            if old.get("status") == "pending" or old.get("deferred_once"):
                return None, f"{probe_id}: a once-deferred target cannot be deferred again; test it or decline it"
            record.update(
                {
                    "status": "pending",
                    "due_turn": turn + 1,
                    "deferred_once": True,
                    "deferred_turn": turn,
                    "reason": decision.reason,
                }
            )
        else:  # decline; test_now without a matching package was rejected above
            record.update(
                {
                    "status": "declined",
                    "resolved_turn": turn,
                    "declined_turn": turn,
                    "reason": decision.reason,
                }
            )
        records[probe_id] = record
        completed.add(probe_id)

    missing = set(probe_review.get("required_ids") or []) - completed
    if missing:
        return None, (
            "structured probe decisions required for "
            + ", ".join(sorted(missing))
            + "; test the exact target now, defer it once, or explicitly decline/cancel it"
        )
    if sum(record.get("status") == "pending" for record in records.values()) > MAX_PROBES:
        return None, f"at most {MAX_PROBES} pending probes are allowed"
    return records, None
