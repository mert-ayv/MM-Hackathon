"""Isolated continuation candidate; not selected by the final router.

Use --agent mert --variant v16 for v16 evidence plus these policy changes:
raw-material packages inherit Emre's clause/payment alternatives, preserve total
cost across package changes, and allow at most two extra counters when a close-gap
decision would stop an OPEN, still-conceding supplier. Final-offer pushes are off.
Other case types retain the selected base policy, except the evidence guard and
disabled final pushes. No claimed practice improvement until measured.
"""

import math
import re
from dataclasses import replace

from arena_kit.cost import RELATIONSHIP_GOALS, closing_terms, complete_offer, must_haves_ok, total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import latest

from .. import intel, levers
from ..agent import CseeAgent
from ..writer import SIGN
from .emre import EmreAgent

CONTINUATION_REASON = "open supplier still conceding: hold last package"


class MertAgent(EmreAgent):
    MAX_CONTINUATIONS = 2

    def prepare(self, case, threads):
        super().prepare(case, threads)
        # Emre enables a final push in prepare; explicitly disable it afterwards.
        self.p = replace(self.p, final_push=0.0, push_after_final=0)
        self.continuations = {}
        for sid, events in threads.items():
            asks = [m["term_sheets"][0]["terms"] for m in events if m.get("from") == "buyer" and m.get("term_sheets")]
            # Recover conservatively after restart: repeated identical proposals
            # consume the continuation budget even if an older policy sent them.
            self.continuations[sid] = sum(a == b for a, b in zip(asks, asks[1:], strict=False))
        for st in self.threads.values():
            # v16 asserted that an UNKNOWN should-cost is below the quote. A
            # reference existing is not evidence about the direction of its value.
            st.intel.claims = [
                c
                for c in st.intel.claims
                if not (
                    c.source == "history"
                    and c.kind == "should_cost"
                    and any(not intel._fact(case, self.pkg, ref) for ref in c.ids)
                )
            ]

    @staticmethod
    def last_proposal(events):
        return next(
            (
                m["term_sheets"][0]["terms"]
                for m in reversed(events)
                if m.get("from") == "buyer" and m.get("term_sheets")
            ),
            None,
        )

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        proposal = super().next_terms(case, threads, sid, theirs, std, supplier, left)
        if not self.raw or "unit_price" not in case["negotiable"]:
            return proposal
        st, events = self.threads[sid], threads[sid]
        previous = self.last_proposal(events)
        if previous is None or previous.get("unit_price") is None:
            return proposal
        if proposal is None:
            # next_terms is also used as a read-only stopping probe by base.
            # Count continuations only in thread_move, after a message is built.
            if not st.why.startswith("their C "):
                return None
            return self.continue_open(case, threads, sid, theirs, std, supplier, left, previous)

        changed = any(proposal.get(f) != previous.get(f) for f in case["negotiable"] if f != "unit_price")
        if changed:
            # Budget just the policy's explicit price concession on the OLD
            # package. A new clause/shorter payment must not add a second gift.
            old_at_new_price = {**previous, "unit_price": max(previous["unit_price"], proposal["unit_price"])}
            budget = total_cost(case, old_at_new_price, std, supplier)
            if total_cost(case, proposal, std, supplier) > budget:
                price = levers.price_for(case, proposal, budget, std, supplier)
                repriced = False
                if price is not None and price > 0:
                    adjusted = {**proposal, "unit_price": price}
                    # price_for rounds to cents: never round above our budget.
                    if total_cost(case, adjusted, std, supplier) > budget:
                        adjusted["unit_price"] = round(price - 0.01, 2)
                    if (
                        adjusted["unit_price"] > 0
                        and total_cost(case, adjusted, std, supplier) <= budget
                        and must_haves_ok(case, adjusted, std)
                    ):
                        proposal = adjusted
                        repriced = True
                        st.why += "; package change repriced within concession budget"
                if not repriced:
                    st.why = "cannot price changed package within concession budget"
                    return None
        return proposal

    def continue_open(self, case, threads, sid, theirs, std, supplier, left, previous):
        events = threads[sid]
        if (
            latest(events).get("status") != "open"
            or self.continuations[sid] >= self.MAX_CONTINUATIONS
            or self.rounds_left(sid, left) <= self.p.reserve_moves + 1
        ):
            return None
        replies = [m for m in events if m.get("from") != "buyer" and m.get("term_sheets")]
        if len(replies) < 2:
            return None
        _, before = self.their_sheet(case, [replies[-2]], std, supplier)
        c_before = total_cost(case, before, std, supplier)
        c_now = total_cost(case, theirs, std, supplier)
        # An actual improvement in package cost, not nominal price, is required.
        if not math.isfinite(c_before) or c_before - c_now <= 0.01:
            return None
        proposal = complete_offer(case, previous)
        if not must_haves_ok(case, proposal, std):
            return None
        if total_cost(case, proposal, std, supplier) >= c_now - 0.01:
            return None  # they already met or beat our last package
        self.threads[sid].why = CONTINUATION_REASON
        return proposal

    def thread_move(self, case, threads, sid):
        if self.case_id == case["case_id"]:
            self.threads[sid].why = ""
        msg = super().thread_move(case, threads, sid)
        if self.raw and msg and msg.get("term_sheets"):
            st = self.threads[sid]
            if st.why == CONTINUATION_REASON:
                self.continuations[sid] += 1
            # Emre can replace the proposed main sheet with its clause sheet.
            # The next round must start at the price actually sent, not a draft.
            already_sent = sum(m.get("from") == "buyer" and bool(m.get("term_sheets")) for m in threads[sid])
            price = msg["term_sheets"][0]["terms"]["unit_price"]
            if len(st.our_prices) <= already_sent:
                st.our_prices.append(price)
            else:
                st.our_prices[-1] = price
        return msg


class MertAnchorAgent(MertAgent):
    """Raw-only 30% opening-anchor ablation; every other decision unchanged."""

    def prepare(self, case, threads):
        super().prepare(case, threads)
        if self.raw:
            self.p = replace(self.p, anchor_leverage=0.30)


class MertConsistentAgent(MertAgent):
    """Keep the indexed structure once both parties offer it.

    Base only recognises an insisted clause after a buyer fixed-price MAIN sheet.
    Emre can instead replace that main sheet before it is sent. Rebuilding a fixed
    main next round then converting it back to indexed subtracts another trade_gain
    and can erase the intended concession. This challenger keeps the shared clause.
    """

    def clause_insisted(self, events):
        if super().clause_insisted(events):
            return True
        ours = self.last_proposal(events)
        offered = latest(events).get("term_sheets") or []
        return bool(
            self.raw
            and ours
            and ours.get("index_clause")
            and offered
            and offered[0].get("terms", {}).get("index_clause")
        )


class MertDialogueAgent(MertAgent):
    """Separate challenger: answer binding-volume questions and request real approval.

    No invented volume, contract extension, authority threshold or guaranteed approval.
    Numbers come from the actual main package including the enquiry's fixed terms.
    Approval requests are made only when the dossier documents an approval process.
    """

    def thread_move(self, case, threads, sid):
        msg = super().thread_move(case, threads, sid)
        if not msg or not msg.get("term_sheets") or latest(threads[sid]).get("status") != "open":
            return msg
        events, st = threads[sid], self.threads[sid]
        first = not any(m.get("from") == "buyer" for m in events)
        last_body = (latest(events).get("body") or "").lower()
        notes = []
        main = closing_terms(case, msg["term_sheets"][0]["terms"], standard_terms(events))
        if first or re.search(r"volume|quantity|commitment|forecast", last_body):
            volume, months = main.get("volume_per_year"), main.get("contract_months")
            if volume and months:
                notes.append(
                    f"Our main package is a binding annual quantity of {volume:g} for {months:g} months, "
                    "as specified in the enquiry and term sheet. Please price that committed quantity; "
                    "the wider forecast is not an additional commitment."
                )
        pressures = st.intel.profile.get("pressures") or []
        authority = next(
            (p for p in pressures if re.search(r"committee|approval|authori", p.get("evidence", ""), re.I)),
            None,
        )
        prior_bodies = " ".join(m.get("body") or "" for m in events if m.get("from") == "buyer")
        if authority and "responsible approver" not in prior_bodies:
            refs = [r for r in authority.get("ids", []) if r.startswith("doc:") and intel._fact(case, self.pkg, r)]
            source = f" ({', '.join(refs[:2])})" if refs else ""
            approver = "pricing committee" if "committee" in authority.get("evidence", "").lower() else "management"
            notes.append(
                f"Our supplier notes describe your approval process{source}. "
                f"Please refer these packages to your {approver}, the responsible approver, "
                "for a further price concession, "
                "and obtain their decision before issuing a final offer. Which package can they approve?"
            )
            msg["refs"] = list(dict.fromkeys([*msg.get("refs", []), *refs[:2]]))[:20]
        if not notes:
            return msg
        addition = "\n\n".join(notes)

        def explain(body):
            if SIGN in body:
                return body.replace(SIGN, addition + "\n\n" + SIGN)
            return body.rstrip() + "\n\n" + addition

        msg["body"] = explain(msg["body"])
        write = msg.get("_write")
        if write:
            msg["_write"] = lambda: explain(write())
        return msg


class MertClauseAgent(MertAgent):
    """P02 challenger: when the supplier blames an index we may write a clause on, offer that clause as an
    alternative sheet for a lower base price (P02: copper +47.7 %, 20 % of its cost; no run ever offered one).

    The clause sheet costs us exactly the main sheet's C less trade_gain (code prices it), so taking it is
    never worse for us; the supplier-favoured form (smallest deadband) gives it the most risk relief."""

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if "index_clause" not in case["negotiable"] or "unit_price" not in case["negotiable"]:
            return out
        main = out[0]
        if main.get("index_clause"):
            return out
        events = self.threads[sid].events
        opening = next((m.get("body") or "" for m in events if m.get("from") != "buyer"), "")
        blamed = set(intel.DRIVER_RE.findall(opening))
        clauses = [c for c in levers.options(case, "index_clause") if c and c.get("series") in blamed]
        if not clauses:
            return out
        clause = min(clauses, key=lambda c: c.get("deadband_pct") or 0)  # most relief for the supplier
        t = complete_offer(case, {**main, "index_clause": clause})
        if not must_haves_ok(case, t, std):
            return out
        target = total_cost(case, main, std, None) * (1 - self.p.trade_gain)
        t["unit_price"] = levers.price_for(case, t, target, std, None)
        if t["unit_price"] <= 0 or t in out:
            return out
        return [main, t] + out[1:2]


# P02 hedge challenger (sub-p02 analysis): copper clause in the form cheapest for us, relationship-aware price
SERIES_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,}(?:-[A-Z0-9@]+)+)\b")


def implied_rate(events, default=0.08):
    """The supplier's own money rate, read from two of its sheets that differ only in payment days
    (P02: 373.88@90 vs 369.76@30 -> 6.6 %). Its alternatives are value-equivalent for it."""
    rates = []
    for m in events:
        if m.get("from") == "buyer":
            continue
        sheets = [s.get("terms") or {} for s in (m.get("term_sheets") or [])]
        for a in sheets:
            for b in sheets:
                da, db = a.get("payment_days"), b.get("payment_days")
                pa, pb = a.get("unit_price"), b.get("unit_price")
                if not (da and db and pa and pb) or da <= db:
                    continue
                same = all(a.get(k) == b.get(k) for k in a if k not in ("payment_days", "unit_price"))
                if same and pa > pb:
                    rates.append((pa - pb) / pa * 360 / (da - db))
    rates = [r for r in rates if 0.0 < r < 0.3]
    return sum(rates) / len(rates) if rates else default


class MertHedgeAgent(CseeAgent):
    REAL_FULL = 0.98  # own-plant should-cost x 0.98 = the full cost the relationship charge uses (P01, P02)

    def calibrated(self, case, sid, std):
        """Our best estimate of the supplier for the relationship term: real full cost, its own money rate."""
        st = self.threads[sid]
        if not st.intel.full_cost:
            return self.supplier_estimate(case, sid, std)
        return {
            "full_cost": st.intel.full_cost * self.REAL_FULL,
            "interest_rate": implied_rate(st.events),
            "standard": closing_terms(case, st.opening, std),
        }

    def blamed_series(self, sid):
        text = " ".join(m.get("body") or "" for m in self.threads[sid].events if m.get("from") != "buyer")
        return set(intel.DRIVER_RE.findall(text)) | {
            s for s in SERIES_RE.findall(text) if re.search(rf"{re.escape(s)}[^.]{{0,40}}(rose|clause|Preisgleit)", text)
        }

    def hedge_sheet(self, case, sid, main, std):
        """The clause package with the lowest C for us under the calibrated supplier model, or None."""
        if "index_clause" not in case["negotiable"] or "unit_price" not in case["negotiable"]:
            return None
        blamed = self.blamed_series(sid)
        clauses = [c for c in levers.options(case, "index_clause") if c and c.get("series") in blamed]
        paths = case["buyer"].get("index_paths") or {}
        clauses = [c for c in clauses if paths.get(c["series"], 0) > 0]  # a hedge for a RISING index only
        if not clauses:
            return None
        sup = self.calibrated(case, sid, std)
        # payment: keep main's term until the supplier's own sheets reveal its money rate (P02 r1 default 8 %
        # picked 14 days, true score 0.61 at its real 6.6 %)
        known = any(len(m.get("term_sheets") or []) > 1 for m in self.threads[sid].events if m.get("from") != "buyer")
        pays = levers.options(case, "payment_days") if "payment_days" in case["negotiable"] and known else [None]
        best = None
        for clause in clauses:
            for pay in pays:
                t = complete_offer(case, {**main, "index_clause": clause, **({"payment_days": pay} if pay else {})})
                if not must_haves_ok(case, t, std):
                    continue
                ask = (self.threads[sid].opening or {}).get("unit_price") or main["unit_price"]
                hi = max(main["unit_price"], ask) * 1.02
                lo = hi * 0.85
                if case["buyer"].get("category_goal") in RELATIONSHIP_GOALS and sup:
                    p = levers.relationship_optimal_price(case, t, std, sup, lo, hi, steps=400)
                else:
                    # no relationship charge: C falls with the price; ask the same C as main minus trade_gain
                    p = levers.price_for(case, t, total_cost(case, main, std) * (1 - self.p.trade_gain), std, None)
                if not p or p <= 0:
                    continue
                t["unit_price"] = round(p, 2)
                c = total_cost(case, t, std, sup)
                if best is None or c < best[0]:
                    best = (c, t)
        return best

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if not out or out[0].get("index_clause"):
            return out
        found = self.hedge_sheet(case, sid, out[0], std)
        if not found:
            return out
        c_hedge, hedge = found
        sup = self.calibrated(case, sid, std)
        # only if it beats what the supplier has on the table now (else it is a gift, not a trade)
        _, theirs = self.their_sheet(case, self.threads[sid].events, std, sup)
        c_table = total_cost(case, theirs, std, sup) if theirs.get("unit_price") else math.inf
        if c_hedge >= c_table * (1 - self.p.trade_gain) or hedge in out:
            return out
        self.threads[sid].why += f"; hedge sheet {hedge['unit_price']}@{hedge.get('payment_days')} on {hedge['index_clause']['series']} db{hedge['index_clause']['deadband_pct']}"
        return [out[0], hedge] + out[1:2]


class MertHedgeLateAgent(MertHedgeAgent):
    """Same hedge, but only from our 3rd message (62b1 offered it at r4 while open and got 'agreed'): two
    rounds to test whether the no-clause track moves below the hedge's C first. Riskier (final offers came
    at reply 4 after deep anchors) - offer it no later than message 3."""

    FROM_MESSAGE = 3

    def sheets(self, case, sid, ours, std, supplier):
        sent = sum(1 for m in self.threads[sid].events if m.get("from") == "buyer")
        if sent + 1 < self.FROM_MESSAGE:
            return CseeAgent.sheets(self, case, sid, ours, std, supplier)
        return super().sheets(case, sid, ours, std, supplier)
