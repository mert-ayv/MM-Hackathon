"""One hybrid baseline for every case type, without per-supplier strategy routing.

Preparation and live interpretation share a bounded JSON contract. Code owns the menu, exact
claim sentences, all numeric state, and the auction close. Existing agents remain benchmarks.
"""

import json
import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from arena_kit.cost import closing_terms
from ..agent import standard_terms
from arena_kit.play import ENDED, latest

from .. import intel, levers
from ..agent import CseeAgent, Params
from ..negotiation import control, council, engine, evidence, memory, preparation, strategy
from ..writer import SIGN, TemplateWriter, describe
from .rfq_support import compare_bids, competitive_claims, quoted_bids
from .strategy_support import EvidenceDesk, price_package


class UnifiedAgent(CseeAgent):
    USE_TEAM = True
    PREPARE_SECONDS = 80.0
    TURN_SECONDS = 40.0
    REVIEW_MODE = "selective"
    LEAD_SECONDS = 25.0

    def __init__(self, package=None, writer=None, params=None):
        self.complete = getattr(writer, "complete", None)
        # One coherent configuration; caller variants remain useful for explicit A/B studies.
        p = replace(
            params or Params(),
            adopt_insisted=True,
            rival_only_lower=True,
            text_signals=True,
            generic_trades=True,
            value_neutral_terms=True,
            rel_anchor=True,
            final_push=0,
            push_after_final=0,
            alt_quote_claim=True,
        )
        super().__init__(package, TemplateWriter(), p)
        self.briefs, self.turns, self.observations = {}, {}, {}
        self.prepared_case = None
        self.turn_deadlines = {}
        self.source_cache, self.role_counts = {}, Counter()
        self.decision_counts = Counter()
        self.claim_families = {}
        self.evidence_records = {}

    def sources(self, case, sid, threads):
        desk = EvidenceDesk(case, self.pkg, sid, threads)
        if sid not in self.source_cache:
            parts, refs = set(case.get("parts", [])), set(case.get("refs", []))
            relevant = [
                (ref, row)
                for ref, row in desk.catalogue().items()
                if (row.get("supplier_id") or row.get("supplier")) == sid
                or ref in refs
                or (row.get("part_id") or row.get("part")) in parts
            ]
            # Prioritize recent evidence, but retain a range of source families. Fetch actual
            # document text: subjects such as "Payment of invoices" are not enough to infer cash stress.
            relevant.sort(key=lambda item: str(item[1].get("date") or item[1].get("quarter") or item[0]), reverse=True)
            static, per_kind = {}, Counter()
            for ref, row in relevant:
                kind = ref.partition(":")[0]
                if per_kind[kind] >= 6 and ref not in refs:
                    continue
                metadata = json.dumps(row, ensure_ascii=False, default=str)
                try:
                    document = desk.document(ref, limit=2400)["text"]
                except (ValueError, KeyError, TypeError, FileNotFoundError):
                    document = metadata
                static[ref] = metadata[:800] + "\n" + document if document != metadata else metadata[:2400]
                per_kind[kind] += 1
                if len(static) >= 32:
                    break
            self.source_cache[sid] = static
        rows = dict(self.source_cache[sid])
        # Keep the most recent correspondence in a dedicated, first-class view. Structured
        # claim feedback is evidence too, not buried behind older dossiers.
        events = threads.get(sid, [])
        for i in range(max(0, len(events) - 6), len(events)):
            message = events[i]
            rows[f"thread:{sid}:{i}"] = json.dumps(
                {k: message.get(k) for k in ("from", "body", "status", "term_sheets", "claim_results")},
                ensure_ascii=False,
                default=str,
            )[:5000]
            for j, attachment in enumerate(message.get("attachments") or []):
                if attachment.get("text"):
                    rows[f"attachment:{sid}:{i}:{j}"] = str(attachment["text"])[:2400]
        return rows

    def preflight(self, case):
        if not self.USE_TEAM:
            return self._single_preflight(case)
        if not self.complete or self.prepared_case == case["case_id"]:
            return
        self.prepared_case = case["case_id"]
        self.source_cache, self.role_counts = {}, Counter()
        started, dossiers = time.monotonic(), {}
        experience = memory.recall(case)
        for sid in case["suppliers"]:
            sources = self.sources(case, sid, {})
            info = intel.build(case, self.pkg, sid)
            digests = evidence.digests(case, self.pkg, sid, info.claims)
            claims = {preparation.claim_id(c): {"kind": c.kind, "text": c.sentence} for c in info.claims}
            sources = {**sources, **{f"evidence:{key}": c["text"] for key, c in claims.items()}}
            dossiers[sid] = {
                "sources": sources,
                "claims": claims,
                "profile": info.profile,
                "digests": digests,
                "experience": experience,
            }
        self.briefs = preparation.research(
            self.complete, case, dossiers, max(0, self.PREPARE_SECONDS - (time.monotonic() - started)), self.record_role
        )

    def record_role(self, key, result):
        with self.shared_lock:
            self.role_counts[result["diagnostic"]] += 1
        self.log.event("unified_role", role=key, diagnostic=result["diagnostic"], elapsed_s=result["elapsed_s"])
        logging.getLogger("csee").info("unified %s: %s (%.1fs)", key, result["diagnostic"], result["elapsed_s"])

    def _single_preflight(self, case):
        """Called by the runner before table.open, never inside a supplier's reply clock."""
        if not self.complete or self.prepared_case == case["case_id"]:
            return
        self.prepared_case = case["case_id"]
        self.source_cache = {}
        end = time.monotonic() + self.PREPARE_SECONDS

        def prepare_supplier(sid):
            sources = self.sources(case, sid, {})
            info = intel.build(case, self.pkg, sid)
            payload = {
                "case": case,
                "supplier": sid,
                "sources": sources,
                "profile_hypothesis": info.profile,
                "claims": [{"kind": c.kind, "text": c.sentence} for c in info.claims[:15]],
            }
            raw, diagnostic = strategy.ask(
                self.complete, strategy.PREPARE_SYSTEM, payload, max(0, end - time.monotonic())
            )
            raw = raw or {}
            return sid, {
                "priorities": strategy.choices(raw.get("priorities"), set(case["negotiable"]) - {"unit_price"}, 3),
                "claim_kinds": strategy.choices(raw.get("claim_kinds"), {c.kind for c in info.claims}, 4),
                "hypotheses": strategy.grounded(raw.get("hypotheses"), sources),
                "diagnostic": diagnostic,
            }

        with ThreadPoolExecutor(max_workers=min(3, len(case["suppliers"]) or 1)) as pool:
            self.briefs = dict(pool.map(prepare_supplier, case["suppliers"]))

    def prepare(self, case, threads):
        if self.prepared_case != case["case_id"]:
            self.briefs = {}  # missing preflight: never start heavy research after opening
            self.source_cache = {}
        self.turns, self.observations, self.turn_deadlines = {}, {}, {}
        self.decision_counts = Counter()
        self.claim_families = {}
        self.evidence_records = {}
        super().prepare(case, threads)
        for sid, events in threads.items():
            self.evidence_records[sid] = evidence.records(case, self.pkg, self.threads[sid].intel.claims)
            cited = {ref for m in events if m.get("from") == "buyer" for ref in m.get("refs", [])}
            self.claim_families[sid] = {
                (c.kind, c.tag)
                for c in self.threads[sid].intel.claims
                if c.kind != "rival" and any(ref in cited for ref in c.ids)
            }
        self.log.event("unified_preparation", briefs=self.briefs)

    def price(self, case, threads, sid, terms):
        return price_package(self, case, threads, sid, terms)

    def arguments(self, case, threads, sid):
        st = self.threads[sid]
        order = self.briefs.get(sid, {}).get("claim_kinds", [])
        skip = self.briefs.get(sid, {}).get("avoid_claim_ids", [])
        # Profile prose is context, not a keyword blacklist: a recommendation to replace
        # index A with B mentions both, without invalidating measured changes in either.
        claims = [
            c
            for c in st.intel.claims
            if preparation.claim_id(c) not in skip
            # Complaint-level ppm averages are not a supplier-wide defect rate. The
            # generated history claims do not establish a comparable denominator.
            and not (c.kind == "scorecard" and c.ids and all(r.startswith("qn:") for r in c.ids))
        ]
        claims.sort(key=lambda c: (order.index(c.kind) if c.kind in order else len(order), -c.strength))
        mine = latest(threads[sid]).get("term_sheets", [{}])[0].get("terms", {}).get("unit_price")
        claims = (
            competitive_claims(self, case, threads, sid) + intel.alt_quote_claims(case, self.pkg, sid, mine) + claims
        )
        with self.shared_lock:
            return {
                preparation.claim_id(c): c
                for c in claims
                if (sid, *c.ids) not in self.used_ids
                and (c.kind == "rival" or (c.kind, c.tag) not in self.claim_families.get(sid, set()))
                and tuple(c.ids) not in self.used_ids
                and (c.kind == "rival" or not any(ref in self.used_ids for ref in c.ids))
            }

    def nothing_to_win(self, case, threads, sid, theirs, std, left):
        """Protocol lookahead must not run a council or overwrite its chosen proposal."""
        st = self.threads[sid]
        saved = st.why, st.anchor_c
        try:
            supplier = self.supplier_estimate(case, sid, std)
            return engine.propose(self, case, threads, sid, theirs, std, supplier, left) is None
        finally:
            st.why, st.anchor_c = saved

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        baseline = engine.propose(self, case, threads, sid, theirs, std, supplier, left)
        if baseline is None:
            return None
        brief = self.briefs.get(sid, {})
        state = control.observe(case, threads[sid], std)
        candidates = engine.menu(
            self, case, threads, sid, baseline, std, supplier, brief.get("priorities", []), brief.get("requests", [])
        )
        if not candidates:
            self.threads[sid].why = "No valid proposal beats the alternative"
            return None
        current = closing_terms(case, theirs, std)
        control.annotate(case, candidates, current, std, supplier, state)
        arguments = self.arguments(case, threads, sid)
        sources = self.sources(case, sid, threads) if self.complete else {}
        live_sources = {ref: text for ref, text in sources.items() if ref.startswith(("thread:", "attachment:"))}
        active_refs = {
            item["source"]
            for name in ("hypotheses", "stance_evidence", "requests")
            for item in brief.get(name, [])
            if item.get("source") in sources
        }
        static_refs = sorted(active_refs) + [
            ref for ref in sources if ref not in active_refs and ref not in live_sources
        ]
        turn_sources = {**{ref: sources[ref] for ref in static_refs[:10]}, **live_sources}
        report = compare_bids(self, case, threads, sid)
        payload = {
            "case_type": case.get("type"),
            "goal": case["buyer"].get("category_goal"),
            "supplier": sid,
            "preparation": {k: v for k, v in brief.items() if k not in ("reports", "role_diagnostics")},
            "profile_hypothesis": self.threads[sid].intel.profile,
            "commercial_state": state,
            "evidence_records": {
                k: self.evidence_records[sid][k] for k in arguments if k in self.evidence_records.get(sid, {})
            },
            "sources": turn_sources,
            "live_sources": live_sources,
            "latest_reply": latest(threads[sid]),
            "allowed_terms": case.get("term_options", {}),
            "observations": self.observations.get(sid, []),
            "moves_left": left,
            "candidates": candidates,
            "claims": {k: c.sentence for k, c in arguments.items()},
            "competition": report,
            "cost_assumptions": self.price(case, threads, sid, candidates[0]["terms"]),
        }
        budget = self.TURN_SECONDS
        if sid in self.turn_deadlines:
            budget = min(budget, max(0, self.turn_deadlines[sid] - time.monotonic()))
        if self.cap_at:
            budget = min(budget, max(0, self.cap_at() - time.time() - 3))
        started = time.monotonic()
        advisers = {}
        if self.USE_TEAM and self.complete and budget > 0:
            end = started + budget

            def emit(key, row):
                self.record_role(f"{sid}/{key}", row)

            raw, diagnostic = council.decide(self.complete, payload, min(end, started + self.LEAD_SECONDS), emit)
        else:
            raw, diagnostic = strategy.ask(self.complete, strategy.TURN_SYSTEM, payload, budget)
        raw = raw or {}
        selected = next((c for c in candidates if c["id"] == raw.get("candidate_id")), candidates[0])
        if diagnostic == "ok" and selected["id"] != raw.get("candidate_id"):
            diagnostic = "invalid_candidate"
            raw = {}
        lead_selected = selected["id"]
        turn_cost_ceiling = max(candidates[0]["cost"], selected["cost"])
        adjustments = []
        # Compile an interpreted joint request inside the selected candidate's cost budget.
        requests = preparation.trade_requests([raw.get("trade_request")], case, live_sources)
        if diagnostic == "ok" and requests:
            compiled = engine.add_requests(self, case, threads, sid, [selected], requests, std, supplier)
            if len(compiled) > 1:
                selected = {**compiled[-1], "id": f"C{len(candidates)}"}
                candidates.append(selected)
                control.annotate(case, candidates, current, std, supplier, state)
                raw["paragraph"] = ""
                adjustments.append("compiled joint request; wording reset to final terms")
        review_reasons = control.review_reasons(selected, state, latest(threads[sid]))
        if self.REVIEW_MODE == "always":
            review_reasons.append("explicit review ablation")
        if (
            self.USE_TEAM
            and self.complete
            and diagnostic == "ok"
            and self.REVIEW_MODE != "off"
            and review_reasons
            and started + budget - time.monotonic() >= 8
        ):
            advisers = council.review(
                self.complete,
                {
                    **payload,
                    "candidates": candidates,
                    "selected_id": selected["id"],
                    "proposed_bundle": {
                        "candidate_id": selected["id"],
                        "alternative_ids": raw.get("alternative_ids", []),
                    },
                    "turn_cost_ceiling": turn_cost_ceiling,
                    "proposed_claim_ids": raw.get("claim_ids", []),
                    "review_reasons": review_reasons,
                },
                min(started + budget, time.monotonic() + 10),
                emit,
            )
            if advisers["diagnostic"] == "ok":
                reviewed = next((c for c in candidates if c["id"] == advisers["candidate_id"]), None)
                if (
                    reviewed
                    and reviewed["cost"] <= turn_cost_ceiling + 0.01
                    and advisers["alternative_ids"] is not None
                    and control.review_change_allowed(selected, reviewed, advisers, state, live_sources)
                ):
                    if selected["id"] != reviewed["id"] or raw.get("alternative_ids") != advisers["alternative_ids"]:
                        raw["paragraph"] = ""
                        adjustments.append("review replaced complete proposal; wording reset")
                    selected = reviewed
                    raw["alternative_ids"] = advisers["alternative_ids"]
                    raw["reason"] = advisers["reason"]
                if isinstance(raw.get("claim_ids"), list):
                    if any(k in advisers["drop_claim_ids"] for k in raw["claim_ids"]):
                        raw["paragraph"] = ""
                    raw["claim_ids"] = [k for k in raw["claim_ids"] if k not in advisers["drop_claim_ids"]]
        # Keep costly concessions conditional until a supplier quote actually compensates
        # them. Offer the trial beside a protected primary, not as the new default structure.
        if selected.get("term_concession", {}).get("compensation") == "unconfirmed":
            trial = selected
            reference = trial["term_concession"]["reference_terms"]
            restore = {f: reference[f] for f in trial["term_concession"]["fields"]}
            compiled = engine.add_requests(self, case, threads, sid, [trial], [{"terms": restore}], std, supplier)
            if len(compiled) > 1:
                protected = {**compiled[-1], "id": f"C{len(candidates)}", "kind": "protected_trade"}
                candidates.append(protected)
                control.annotate(case, candidates, current, std, supplier, state)
            else:
                protected = None
            safe = [
                c
                for c in candidates
                if c["cost"] <= turn_cost_ceiling + 0.01
                and c.get("term_concession", {}).get("compensation") != "unconfirmed"
            ]
            if not safe:
                self.threads[sid].why = "No valid protected proposal within the turn's cost budget"
                return None
            selected = protected if protected in safe else safe[0]
            raw["alternative_ids"] = list(
                dict.fromkeys(
                    [
                        trial["id"],
                        *strategy.choices(raw.get("alternative_ids"), {c["id"] for c in candidates}, 2),
                    ]
                )
            )[:2]
            raw["paragraph"] = ""
            adjustments.append("unconfirmed concession retained only as conditional alternative")
        with self.shared_lock:
            self.decision_counts[diagnostic] += 1
        observation = strategy.grounded(raw.get("observations"), payload["live_sources"] if self.USE_TEAM else sources)
        unique = {json.dumps(o, sort_keys=True): o for o in self.observations.get(sid, []) + observation}
        self.observations[sid] = list(unique.values())[-9:]
        # All components use the turn's approved cost ceiling. A reviewer switching to a
        # slightly cheaper primary must not silently delete the original protected alternative.
        sheets = [selected["terms"]]
        bundle_ids = [selected["id"]]
        alternatives = raw.get("alternative_ids")
        explicit_alternatives = (
            isinstance(alternatives, list)
            and len(alternatives) <= 2
            and all(isinstance(k, str) and any(c["id"] == k for c in candidates) for k in alternatives)
        )
        ordered = (
            [next(c for c in candidates if c["id"] == k) for k in dict.fromkeys(alternatives)]
            if explicit_alternatives
            else candidates
        )
        for candidate in ordered:
            if not explicit_alternatives and candidate["kind"] in ("baseline", "patient", "responsive"):
                continue
            if candidate["cost"] > turn_cost_ceiling + 0.01:
                continue
            if all(
                any(candidate["terms"].get(f) != t.get(f) for f in case["negotiable"] if f != "unit_price")
                for t in sheets
            ):
                sheets.append(candidate["terms"])
                bundle_ids.append(candidate["id"])
            if len(sheets) == 3:
                break
        self.turns[sid] = {
            "sheets": sheets,
            "claims": arguments,
            "claim_ids": strategy.choices(raw.get("claim_ids"), arguments, 3),
            "explicit_claims": isinstance(raw.get("claim_ids"), list)
            and len(raw["claim_ids"]) <= 3
            and all(isinstance(k, str) and k in arguments for k in raw["claim_ids"]),
            "paragraph": strategy.paragraph(raw.get("paragraph")),
            "conditional_trade": any(
                c.get("term_concession", {}).get("compensation") == "unconfirmed"
                for c in candidates
                if c["id"] in bundle_ids
            ),
        }
        self.threads[sid].why = f"unified {selected['id']}: {selected['reason']} ({diagnostic})"
        self.log.event(
            "unified_strategy",
            supplier_id=sid,
            diagnostic=diagnostic,
            model_budget_s=round(budget, 3),
            model_elapsed_s=round(time.monotonic() - started, 3),
            selected=selected["id"],
            lead_selected=lead_selected,
            final_bundle=bundle_ids,
            turn_cost_ceiling=turn_cost_ceiling,
            proposal_adjustments=adjustments,
            candidates=candidates,
            observations=observation,
            advisers=advisers,
            review_reasons=review_reasons,
            commercial_state=state,
            playbook_id=raw.get("playbook_id")
            if isinstance(raw.get("playbook_id"), str)
            and raw["playbook_id"] in {p["id"] for p in brief.get("playbook", [])}
            else None,
            reason=str(raw.get("reason", ""))[:400],
        )
        # Base bookkeeping expects unit_price even when the case fixes it.
        return closing_terms(case, selected["terms"], std)

    def sheets(self, case, sid, ours, std, supplier):
        return self.turns[sid]["sheets"]

    def report_run(self):
        try:
            memory.record_log(self.log)
        except (OSError, ValueError, TypeError, KeyError):
            logging.getLogger("csee").warning("Could not record local negotiation experience", exc_info=True)
        if self.complete and self.USE_TEAM:
            text = (
                ", ".join(f"{key}={value}" for key, value in sorted(self.role_counts.items())) or "no roles completed"
            )
            self.log.event("unified_team_summary", counts=dict(self.role_counts), decisions=dict(self.decision_counts))
            logging.getLogger("csee").warning(
                "%s unified team calls: %s; decisions: %s", self.case_id, text, dict(self.decision_counts)
            )

    def pick_claims(self, case, threads, sid):
        turn = self.turns[sid]
        pool = turn["claims"]
        ordered = turn["claim_ids"] if turn.get("explicit_claims") else list(pool)
        out, families = [], set()
        limit = 3 if turn.get("explicit_claims") or not any(m.get("from") == "buyer" for m in threads[sid]) else 2
        with self.shared_lock:
            for k in ordered:
                c = pool[k]
                identity = (sid, *c.ids) if c.kind == "rival" else tuple(c.ids)
                family = (c.kind, c.tag)
                if identity in self.used_ids or family in families:
                    continue
                if c.kind != "rival" and any(ref in self.used_ids for ref in c.ids):
                    continue
                self.used_ids.add(identity)
                if c.kind != "rival":
                    self.used_ids.update(c.ids)
                    self.claim_families.setdefault(sid, set()).add(family)
                out.append(c)
                families.add(family)
                if len(out) >= limit:
                    break
        turn["sent_claims"] = out
        return out

    def thread_move(self, case, threads, sid):
        if self.case_id != case["case_id"]:
            self.prepare(case, threads)
        self.turns.pop(sid, None)
        message = super().thread_move(case, threads, sid)
        if message and sid in self.turns:
            turn = self.turns[sid]
            lines = [
                "Good day,",
                turn["paragraph"] or "Thank you for your reply. Please consider the following proposal.",
            ]
            lines.extend(c.sentence for c in turn.get("sent_claims", []))
            if turn.get("conditional_trade"):
                lines.append(
                    "Each option is a complete conditional package: its price and other terms must be "
                    "considered together. A change to one requires repricing the package."
                )
            for i, terms in enumerate(turn["sheets"]):
                full = closing_terms(case, terms, standard_terms(threads[sid]))
                text = describe(full)
                clause = full.get("index_clause")
                text += "; index clause " + (json.dumps(clause, ensure_ascii=False) if clause else "none")
                lines.append(("We propose " if i == 0 else "Alternatively, ") + text + ".")
            message["body"] = "\n\n".join([*lines, SIGN])[:8000]
        return message

    def close(self, case, threads, force=False):
        live = [sid for sid, events in threads.items() if events and latest(events).get("status") not in ENDED]
        if not force and any(not self.threads[s].ready for s in live):
            return None
        bids = [
            b
            for b in quoted_bids(self, case, threads)
            if b["can_accept"] and b["estimated_total_cost"] < levers.alternative_cost(case)
        ]
        if bids:
            best = min(bids, key=lambda b: b["estimated_total_cost"])
            self.close_reason = "Lowest complete standing-bid cost below alternative; must-haves validated"
            return {
                "supplier_id": best["supplier_id"],
                "message": {"action": {"type": "accept", "term_sheet_id": best["offer_id"]}},
            }
        self.close_reason = "No valid standing bid beats alternative"
        return {"supplier_id": (live or case["suppliers"])[0], "message": {"action": {"type": "walk_away"}}}


class UnifiedSingleAgent(UnifiedAgent):
    """Ablation: previous one-call architecture, sharing the same engine and validators."""

    USE_TEAM = False
    PREPARE_SECONDS = 25.0
    TURN_SECONDS = 25.0


class UnifiedFastAgent(UnifiedAgent):
    """Same preparation and policy; one live strategist, no additional reviewer."""

    REVIEW_MODE = "off"


class UnifiedReviewAgent(UnifiedAgent):
    """Same preparation and policy; request review each turn if the clock permits."""

    REVIEW_MODE = "always"
