"""NEGOTIATE, the price path: anchor, concessions that follow the supplier's steps, the terms we hold
or adopt, patience while it still concedes, and repricing a changed package (never a second gift)."""

import math
import time

from arena_kit.cost import RELATIONSHIP_GOALS, closing_terms, complete_offer, must_haves_ok, total_cost
from arena_kit.play import latest, standing

from . import levers

MAX_CONTINUATIONS = 2  # resend our last package at most this often while the supplier still concedes
CONTINUATION_REASON = "open supplier still conceding: hold last package"


class Concede:
    """Mixin of UnifiedAgent (needs self.p, self.threads, self.pkg, self.shared_lock, ...)."""

    def floor_price(self, st):
        full = (st.breakdown or {}).get("full_cost") or st.intel.full_cost
        return full * (1 + self.p.floor_margin) if full else None

    def nothing_to_win(self, case, threads, sid, theirs, std, left):
        """next_terms would stop here (its sheet is as cheap as ours): the moment to close this thread."""
        supplier = self.supplier_estimate(case, sid, std)
        saved = (list(self.threads[sid].our_prices), list(self.threads[sid].their_prices))
        try:
            return self.next_terms(case, threads, sid, theirs, std, supplier, left) is None
        finally:
            self.threads[sid].our_prices, self.threads[sid].their_prices = saved

    def rounds_left(self, sid, left):
        """Messages we can still send in this thread: the round limit, or in the Live Final how many rounds
        fit before the runner's safety close (8-minute waves, replies up to a minute: ~5-7 rounds, not 10)."""
        cap = self.cap_at() if self.cap_at else None
        if not cap:
            return left
        times = self.threads[sid].round_s
        per_round = max(sum(times[-3:]) / len(times[-3:]) if times else 45.0, 15.0)
        fit = int(max(cap - time.time(), 0) // per_round)
        return min(left, fit)

    # ---------- NEGOTIATE: base concession path, plus patience and package-change repricing ----------
    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        proposal = self.base_terms(case, threads, sid, theirs, std, supplier, left)
        if "unit_price" not in case["negotiable"]:
            return proposal
        st, events = self.threads[sid], threads[sid]
        previous = self.last_proposal(events)
        if previous is None or previous.get("unit_price") is None:
            return proposal
        if proposal is None:
            # close_gap would stop here; while it is still open and conceding, hold our last package instead
            if not st.why.startswith("their C "):
                return None
            return self.continue_open(case, threads, sid, theirs, std, supplier, left, previous)
        if any(proposal.get(f) != previous.get(f) for f in case["negotiable"] if f != "unit_price"):
            # a changed package (new clause, other payment) must not add a second gift on top of the price step:
            # budget = our OLD package at the new price. Priced without the relationship term when trade_no_rel
            # (price_for finds no price with it: P02/P14). If no price fits, send the proposal as planned - stopping
            # here ended threads early (sim P02 0.26 -> 0.19)
            rel = None if self.p.trade_no_rel else supplier
            old_at_new_price = {**previous, "unit_price": max(previous["unit_price"], proposal["unit_price"])}
            budget = total_cost(case, old_at_new_price, std, rel)
            if total_cost(case, proposal, std, rel) > budget:
                price = levers.price_for(case, proposal, budget, std, rel)
                adjusted = {**proposal, "unit_price": price} if price and price > 0 else None
                if adjusted and total_cost(case, adjusted, std, rel) > budget:  # price_for rounds to cents
                    adjusted["unit_price"] = round(price - 0.01, 2)
                if (
                    adjusted
                    and adjusted["unit_price"] > 0
                    and total_cost(case, adjusted, std, rel) <= budget
                    and must_haves_ok(case, adjusted, std)
                ):
                    proposal = adjusted
                    st.why += "; package change repriced within concession budget"
                else:
                    st.why += "; package change could not be repriced: sent as planned"
        return proposal

    @staticmethod
    def last_proposal(events):
        return next(
            (
                m["term_sheets"][0].get("terms", m["term_sheets"][0])
                for m in reversed(events)
                if m.get("from") == "buyer" and m.get("term_sheets")
            ),
            None,
        )

    def continue_open(self, case, threads, sid, theirs, std, supplier, left, previous):
        """It is open and its package got cheaper since its last reply: resend our last package (at most
        MAX_CONTINUATIONS times, keeping reserve moves) instead of closing on a still-moving supplier."""
        events, st = threads[sid], self.threads[sid]
        if (
            latest(events).get("status") != "open"
            or st.continuations >= MAX_CONTINUATIONS
            or self.rounds_left(sid, left) <= self.p.reserve_moves + 1
        ):
            return None
        replies = [m for m in events if m.get("from") != "buyer" and m.get("term_sheets")]
        if len(replies) < 2:
            return None
        _, before = self.their_sheet(case, [replies[-2]], std, supplier)
        c_before = total_cost(case, before, std, supplier)
        c_now = total_cost(case, theirs, std, supplier)
        if not math.isfinite(c_before) or c_before - c_now <= 0.01:
            return None  # it stopped conceding: close
        proposal = complete_offer(case, previous)
        if not must_haves_ok(case, proposal, std) or total_cost(case, proposal, std, supplier) >= c_now - 0.01:
            return None  # it already met or beat our last package
        st.why = CONTINUATION_REASON
        return proposal

    def base_terms(self, case, threads, sid, theirs, std, supplier, left):
        st = self.threads[sid]
        b = case["buyer"]
        p_s = theirs.get("unit_price") or closing_terms(case, theirs, std).get("unit_price")
        if p_s is None:
            st.why = "their sheet has no price"
            return None
        fixed = self.insisted_fields(case, threads[sid])
        if self.p.sticky_terms and st.our_prices:
            # once it has priced a set of terms, flipping them lets it re-price (P11: we flipped quality terms
            # three times and accepted the dearest set it had offered): keep its cheapest-for-us sheet's terms,
            # negotiate the price, trade other terms only in alternative sheets
            sticky = tuple(f for f in case["negotiable"] if f != "unit_price")
            stick = {f: theirs[f] for f in sticky if f in case["negotiable"] and f in theirs}
            if self.p.sticky_max_cost and stick:
                # keep only the terms that are cheap for us to concede (D01: its 30 days = 0.7 % of C, stick;
                # P01: its early start date = several %, don't) - the rest we still negotiate
                ours_best = levers.best_terms(
                    case, {**theirs}, std, supplier, supplier_ppm=self.real_ppm(case, sid, std)
                )
                c0 = total_cost(case, ours_best, std, supplier)
                stick = {
                    f: v
                    for f, v in stick.items()
                    if total_cost(case, {**ours_best, f: v}, std, supplier) - c0 <= self.p.sticky_max_cost * c0
                }
            fixed.update(stick)
        revealed = self.revealed_fields(case, threads[sid], theirs)
        if "payment_days" in revealed and not self.cash_short(sid):
            # P18: its 30-day alternative looked cheapest at that moment and got locked in; the same supplier
            # gave 90 days at the same price to another agent. Faster payment only for a supplier short of cash
            revealed.pop("payment_days")
        fixed.update(revealed)
        # never adopt a supplier value that breaks one of our must-haves (P10: volume 19,890 < 22,230); meet it
        # at the bound instead (P09: it holds 49 days against our <= 42 - offer 42, not our 28 eight times)
        held = fixed
        fixed = {k: v for k, v in held.items() if must_haves_ok(case, {**complete_offer(case, theirs), k: v}, std)}
        for k in set(held) - set(fixed):
            near = levers.nearest_ok(case, k, held[k])
            if near is not None:
                fixed[k] = near
        exclude = {}
        if self.clause_insisted(threads[sid]):
            fixed.pop("index_clause", None)
            exclude = {"index_clause": [None]}  # a clause it is: the cheapest one for us (widest deadband)
        value_of = self.value_fn(case, sid, std) if self.p.value_neutral_terms else None
        real_ppm = self.real_ppm(case, sid, std)
        cap = self.p.contract_at_horizon and self.clause_rising(case)
        base = levers.best_terms(
            case,
            {**theirs, **fixed},
            std,
            supplier,
            fixed=tuple(fixed),
            exclude=exclude,
            value_of=value_of,
            cap_contract=cap,
            supplier_ppm=real_ppm,
        )
        floor = self.floor_price(st)
        rel_goal = b.get("category_goal") in RELATIONSHIP_GOALS
        if not st.our_prices and self.p.anchor_leverage and not rel_goal:
            # suppliers converge on our anchor, not their floor (deal = first ask + 2-8 %): anchor low,
            # and an estimated floor must not lift it (should-cost is not Tacto's floor)
            p = p_s * (1 - self.p.anchor_leverage)
            if b.get("current_unit_price") and case.get("type") in ("price_increase", "raw_material", "renewal"):
                p = min(p, b["current_unit_price"])
            if self.p.rfq_anchor_vs_leader and len(case["suppliers"]) > 1:
                rivals = [
                    standing(threads[s])[1].get("unit_price")
                    for s in case["suppliers"]
                    if s != sid and threads.get(s) and standing(threads[s])[1].get("unit_price")
                ]
                if rivals:
                    p = min(p, min(rivals) * (1 - self.p.rfq_anchor_vs_leader))
            p = min(p, p_s * 0.995)
        elif not st.our_prices:  # the anchor
            p = p_s * (1 - self.p.anchor_below_open)
            if b.get("current_unit_price") and case.get("type") in ("price_increase", "raw_material", "renewal"):
                p = min(p, b["current_unit_price"])
            if self.p.rel_anchor and rel_goal:
                floor = None  # should-cost is not the bot's floor: P01/P02/P17 should-cost >= the supplier's own ask
            if floor:
                p = max(p, floor)
            if self.p.rel_anchor and rel_goal and st.intel.full_cost:
                # the price below which the margin charge outweighs the saving, at the supplier's REAL cost
                # (should-cost x 0.98): P02 anchors at ~358 (the KAM's own +2 % line) instead of 369 (0.5 % below its ask)
                real = {
                    **(supplier or {}),
                    "full_cost": st.intel.full_cost * self.p.rel_full,
                    "interest_rate": 0.08,
                    "standard": closing_terms(case, st.opening, std),
                }
                p_rel = levers.relationship_optimal_price(case, base, std, real, real["full_cost"] * 0.9, p_s)
                if p_rel:
                    p = max(p, p_rel * 0.99)
            elif b.get("category_goal") in RELATIONSHIP_GOALS and supplier:
                p_rel = levers.relationship_optimal_price(case, base, std, supplier, supplier["full_cost"], p_s)
                if p_rel:
                    p = max(p, p_rel * 0.99)
            p = min(p, p_s * 0.995)
            st.why = f"anchor at {p:.2f} (their ask {p_s:.2f}, floor {floor and round(floor, 2)})"
        else:
            p_b = st.our_prices[-1]
            gap = p_s - p_b
            their_step = (st.their_prices[-2] - st.their_prices[-1]) if len(st.their_prices) >= 2 else gap
            # late: near our round limit, or from its late_after_replies-th reply - real suppliers turn final at
            # reply 3-5 (626 moves), and P02's walked at reply 4 while we followed its 1-EUR steps 2.6 % below
            replies = sum(1 for m in threads[sid] if m.get("from") != "buyer" and m.get("term_sheets"))
            late = self.rounds_left(sid, left) <= 3 or replies >= self.p.late_after_replies
            share = self.p.concede_late if late else self.p.concede_early
            step = share * gap
            if their_step <= 0:  # they did not move: we barely move
                step = min(step, 0.1 * gap)
            else:
                floor_share = self.p.late_min_share if late else 0.05
                step = min(step, max(their_step * self.p.follow_share, floor_share * gap))
            p = p_b + max(step, 0)
            st.why = (
                f"concede {max(step, 0):.2f} of gap {gap:.2f} ({'late' if late else 'early'}, their step "
                f"{their_step:.2f})"
            )
        if "unit_price" not in case["negotiable"]:
            p = p_s  # a fixed price: we negotiate the other terms only
        cap_p = levers.price_cap(case)
        if cap_p is not None and p > cap_p:
            p = cap_p  # never ask above our own price must-have (every later ask would break it)
            st.why += f"; capped at our must-have {cap_p:.2f}"
        # the best terms depend on the price (e.g. above the fallback price a short contract looks
        # "cheaper"): choose them at the price we ask, not at the supplier's (Fable review #3)
        expected = round(p + 0.5 * max(p_s - p, 0), 2)  # where the deal will likely land
        base = levers.best_terms(
            case,
            {**base, **fixed, "unit_price": expected},
            std,
            supplier,
            fixed=tuple(fixed),
            exclude=exclude,
            value_of=value_of,
            cap_contract=cap,
            supplier_ppm=real_ppm,
        )
        ours = {**base, "unit_price": round(p, 2)}
        # their sheet already as cheap as ours (on all terms): nothing to win by writing
        c_theirs = total_cost(case, theirs, std, supplier)
        c_ours = total_cost(case, ours, std, supplier)
        if not st.our_prices:
            opening_c = total_cost(case, st.opening, std, supplier) if st.opening.get("unit_price") else None
            st.anchor_c = (c_ours, opening_c)
        allow = c_ours * self.p.close_gap
        if self.p.close_room and st.anchor_c and st.anchor_c[1]:
            # P02: 0.4 % of C was 19 % of the whole room - we stopped at round 5 with 5 rounds left
            allow = min(allow, self.p.close_room * max(st.anchor_c[1] - st.anchor_c[0], 0))
        if c_theirs <= c_ours + allow:
            st.why = f"their C {c_theirs:.0f} within close_gap of ours {c_ours:.0f}: ready"
            return None
        return ours

    @staticmethod
    def revealed_fields(case, events, chosen):
        """Its alternative sheets price each term (P10: 42 vs 54 days lead time = EUR 1.90/unit). The sheet
        cheapest for us is `chosen`; keep the non-price terms where it differs from its other sheets, so
        best_terms does not flip them back to the value that costs more overall."""
        sheets = [s.get("terms") or {} for s in latest(events).get("term_sheets") or []]
        if len(sheets) < 2:
            return {}
        out = {}
        for f in case["negotiable"]:
            if f == "unit_price" or f not in chosen:
                continue
            if any(f in s and s[f] != chosen[f] for s in sheets if s is not chosen):
                out[f] = chosen[f]
        return out

    @staticmethod
    def clause_insisted(events):
        """The supplier put an index clause into its sheets twice after we asked for none."""
        hits, ask = 0, None
        for m in events:
            if m.get("from") == "buyer" and m.get("term_sheets"):
                ask = m["term_sheets"][0].get("terms", m["term_sheets"][0])
            elif m.get("from") != "buyer" and ask is not None and ask.get("index_clause") is None:
                sheets = [s.get("terms", {}) for s in m.get("term_sheets") or []]
                if (
                    sheets
                    and all(s.get("index_clause") for s in sheets if "index_clause" in s)
                    and any(s.get("index_clause") for s in sheets)
                ):
                    hits += 1
        return hits >= 1

    @staticmethod
    def insisted_fields(case, events):
        """Non-price terms the supplier answered with the same value at least twice against a
        different ask of ours: {field: its value}. Fighting those wastes rounds."""
        pairs, ask = [], None
        for m in events:
            if m.get("from") == "buyer" and m.get("term_sheets"):
                ask = m["term_sheets"][0].get("terms", m["term_sheets"][0])
            elif m.get("from") != "buyer" and ask and m.get("term_sheets"):
                pairs.append((ask, m["term_sheets"][0]["terms"]))
        out = {}
        for f in case["negotiable"]:
            if f == "unit_price":
                continue
            held = [theirs.get(f) for ours, theirs in pairs[-2:] if f in theirs and theirs.get(f) != ours.get(f)]
            if len(held) == 2 and held[0] == held[1]:
                out[f] = held[0]
        return out
