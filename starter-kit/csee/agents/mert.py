"""Isolated continuation candidate; not selected by the final router.

Use --agent mert --variant v16 for v16 evidence plus these policy changes:
raw-material packages inherit Emre's clause/payment alternatives, preserve total
cost across package changes, and allow at most two extra counters when a close-gap
decision would stop an OPEN, still-conceding supplier. Final-offer pushes are off.
Other case types retain the selected base policy, except the evidence guard and
disabled final pushes. No claimed practice improvement until measured.
"""

import math
import json
import re
from datetime import date
from dataclasses import dataclass, replace

from arena_kit.cost import RELATIONSHIP_GOALS, closing_terms, complete_offer, must_haves_ok, supplier_value, total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import latest

from .. import intel, levers
from ..agent import CseeAgent
from ..agent import must_haves_ok as csee_must_haves_ok
from ..writer import SIGN, LLMWriter, before_signature
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
            price = closing_terms(case, msg["term_sheets"][0]["terms"], standard_terms(threads[sid]))["unit_price"]
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
            return before_signature(body, addition)

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


# ---------- raw-material candidate (P08/P18 review, 24 Oct): see docs in the class ----------
RAW_RECIP = 0.6  # our move >= this share of the supplier's last move, in C
RAW_MIN_GAP = 0.03  # ... but our main package stays at least this share of C below its current package
HEDGE_RE = re.compile(
    # "bought their copper forward until March 2027": the call-note wording (70190, 70520-M4, 70560, 70730)
    r"(?:covered at fixed prices|hedged|bought (?:\w+ ){0,4}?forward|fixed[- ]price cover)[^.]*?until\s+([A-Z][a-z]+)\s+(\d{4})",
    re.I,
)
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}
KIND_ORDER = {"index": 0, "should_cost": 0, "rival": 0, "scorecard": 1, "forecast": 2, "news": 2, "notice": 2,
              "history": 3}


def hedge_of(pkg, sid):
    """(series-agnostic) hedge end as date, from the supplier's own letters in the package, or None."""
    if not pkg:
        return None
    best = None
    for ref, fact in (pkg.facts or {}).items():
        if not ref.startswith("doc:") or not isinstance(fact, dict) or fact.get("supplier") != sid:
            continue
        try:
            text = pkg.document(ref) or ""
        except Exception:
            continue
        m = HEDGE_RE.search(text)
        if m and m.group(1).lower() in MONTHS:
            end = date(int(m.group(2)), MONTHS[m.group(1).lower()], 1)
            best = max(best, end) if best else end
    return best


def material_series(case):
    """The series of the case's own index-clause options: the material the supplier would hedge."""
    return {c["series"] for c in (case.get("term_options") or {}).get("index_clause") or [] if c}


class MertRawAgent(MertConsistentAgent):
    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.hedges = {}
        if not self.raw:
            return
        for sid, st in self.threads.items():
            end = hedge_of(self.pkg, sid)
            self.hedges[sid] = end
            # Keep v16's proven index sequence (strongest fall first; the hedged series now carries the
            # hedge-expiry sentence, see thread_move). Then ONE quality/delivery argument per topic, then
            # order history (4/4 "does not change our calculation" on P08/P18) and repeats last.
            seen_tags = set()

            def rank(c):
                k = KIND_ORDER.get(c.kind, 2)
                if c.kind == "scorecard":
                    if c.tag in seen_tags:
                        return (4, -c.strength)
                    seen_tags.add(c.tag)
                elif c.source == "history":
                    k = 3
                return (k, -c.strength)

            ordered = sorted(st.intel.claims, key=lambda c: (KIND_ORDER.get(c.kind, 2), -c.strength))
            st.intel.claims = sorted(ordered, key=rank)

    # ---------- 1. reciprocity floor ----------
    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        proposal = super().next_terms(case, threads, sid, theirs, std, supplier, left)
        if not self.raw or proposal is None or "unit_price" not in case["negotiable"]:
            return proposal
        events = threads[sid]
        previous = self.last_proposal(events)
        replies = [m for m in events if m.get("from") != "buyer" and m.get("term_sheets")]
        if previous is None or previous.get("unit_price") is None or len(replies) < 3:
            return proposal  # replies[0] is the opening quote: their first real move is replies[1]
        _, before = self.their_sheet(case, [replies[-2]], std, supplier)
        c_before, c_now = total_cost(case, before, std, supplier), total_cost(case, theirs, std, supplier)
        their_move = c_before - c_now
        if not their_move > 0:
            return proposal  # it did not move: base's small step stands
        c_prev = total_cost(case, complete_offer(case, previous), std, supplier)
        c_prop = total_cost(case, proposal, std, supplier)
        target = min(c_prev + RAW_RECIP * their_move, c_now * (1 - RAW_MIN_GAP))
        if c_prop >= target - 0.01:
            return proposal
        price = levers.price_for(case, proposal, target, std, supplier)
        if price is None or price <= proposal["unit_price"]:
            return proposal
        adjusted = {**proposal, "unit_price": price}
        if total_cost(case, adjusted, std, supplier) > target:
            adjusted["unit_price"] = round(price - 0.01, 2)
        if adjusted["unit_price"] > proposal["unit_price"] and must_haves_ok(case, adjusted, std):
            self.threads[sid].why += f"; reciprocity floor {RAW_RECIP:.0%} of their move"
            return adjusted
        return proposal

    # ---------- 3. hedge-expiry sentence when the hedged series is cited ----------
    def hedge_sentence(self, case, sid, main):
        end = self.hedges.get(sid)
        start = (main or {}).get("effective_date") or (case.get("fixed_terms") or {}).get("effective_date")
        months = (main or {}).get("contract_months")
        if not end or not start or not months:
            return None
        s = date.fromisoformat(start)
        first_open = (end.year * 12 + end.month) + 1  # the month after the cover ends
        total = int(months)
        before = max(0, min(total, first_open - (s.year * 12 + s.month)))
        exposed = total - before
        if exposed <= 0:
            return None
        nxt = date((first_open - 1) // 12, (first_open - 1) % 12 + 1, 1)
        return (
            f"You wrote that your material is covered at fixed prices until {end:%B %Y}. Our agreement runs "
            f"{total} months from {s:%B %Y}, so {exposed} of those {total} months, from {nxt:%B %Y} on, are "
            f"follow the market, and the fall cited above reaches your cost."
        )

    def thread_move(self, case, threads, sid):
        msg = super().thread_move(case, threads, sid)
        if not self.raw or not msg or not msg.get("term_sheets") or not self.hedges.get(sid):
            return msg
        hedged = material_series(case)
        if not any(r.startswith("idx:") and r[4:].split("@")[0] in hedged for r in msg.get("refs") or []):
            return msg
        main = {**(case.get("fixed_terms") or {}), **msg["term_sheets"][0]["terms"]}
        line = self.hedge_sentence(case, sid, main)
        if not line:
            return msg

        def add(body):
            return before_signature(body, line)

        msg["body"] = add(msg["body"])
        write = msg.get("_write")
        if write:
            msg["_write"] = lambda: add(write())
        return msg


# ------------------------------------------------------------------ pacing study (scratchpad sub-misc, Sat 24 Oct):
# 1,132 supplier replies, 26 pushes after a final offer; see docs/ARCHITECTURE.md
# max anchor depth below the opening, by case type (outside relationship goals): floor depth + ~6 pp
ANCHOR_CAP = {
    "price_increase": 0.12,
    "renewal": 0.12,
    "quality": 0.22,  # P11 0.71 (record) was played at 22 % and hit the bot's reservation (45.5): keep
    "bundling": 0.15,
    "capacity": 0.15,
    "raw_material": 0.22,
    "rfq": 0.22,
}

# ------------------------------------------------------------------ GatedPushAgent (recommended)
PUSH_MAX = 0.01  # never more than 1 % below its final price
PUSH_SHARE = 0.6  # at most this share of its own concession since its first counter-offer
MIN_CONCESSION = 0.01  # a supplier that moved less than 1 % is at its limit: accept (P02 walked)


class GatedPushAgent(MertAgent):
    """One push after a final offer, sized by how far the supplier has already moved."""

    def push_size(self, case, events):
        sup = [m for m in events if m.get("from") != "buyer" and m.get("term_sheets")]
        if len(sup) < 3 or latest(events).get("status") != "final_offer":
            return 0.0  # need the opening, a first counter and the final offer
        std = standard_terms(events)
        first = sup[1]["term_sheets"][0]["terms"]  # its first counter-offer (after seeing our terms)
        final = sup[-1]["term_sheets"][0]["terms"]
        c1, cf = total_cost(case, first, std), total_cost(case, final, std)
        if not (c1 and cf) or c1 == float("inf") or cf == float("inf"):
            return 0.0
        conc = (c1 - cf) / c1
        if conc < MIN_CONCESSION:
            return 0.0
        return round(min(PUSH_MAX, PUSH_SHARE * conc), 4)

    def final_push_size(self, case, events):
        return self.push_size(case, events)


# ------------------------------------------------------------------ AnchorCapAgent
class AnchorCapAgent(MertAgent):
    """anchor_leverage capped by case type (base applies it outside relationship goals only)."""

    def prepare(self, case, threads):
        super().prepare(case, threads)
        cap = ANCHOR_CAP.get(case.get("type"))
        if cap is not None and self.p.anchor_leverage > cap:
            self.p = replace(self.p, anchor_leverage=cap)


class FinalCandidateAgent(GatedPushAgent, AnchorCapAgent):
    """Anchor cap by case type + gated push after a final offer."""


# ---------- mert-lever: give the supplier what it names ----------
# Give the supplier what it names (mert-lever).
# 
# Suppliers say what would move them: "faster payment would help us", "we can offer a Preisgleitklausel on
# CU-NOTATION", "in return for the 24-month commitment", "a lead time of 42 days is not feasible; we must
# maintain 54", "we are willing to adjust the effective date to 1 January 2027", "which volume can you
# commit to?". The base agent reads a few keywords and otherwise answers with its own trade list.
# 
# This mixin turns every lever the supplier NAMES into an answer:
#   * negotiable field -> an alternative term sheet with that field at the supplier's value, priced by code:
#       - the supplier's side: its cash value (arena_kit.supplier_value at its OWN money rate, read off its
#         sheets), plus what its own alternative sheets reveal per unit of a field (lead time, chargeback,
#         ppm), plus a security value for an index clause (share x the rise it claims, less the deadband) and
#         for a longer contract. p_ind = the price at which the sheet is worth exactly its current ask to it.
#       - our side: the TRUE C (relationship charge at the calibrated supplier: should-cost x 0.98, its money
#         rate). The sheet is offered at max(p_ind, our relationship-optimal price) if that beats the deal we
#         expect without the lever (its current ask less its projected remaining steps) by trade_gain; else at
#         the highest price that does (a real trade, not acceptable at once); never if even that is below our
#         own main ask (the lever costs us more than it is worth to it).
#   * fixed field it asks about -> one honest sentence (the fixed volume in every package is binding; the
#     payment term is fixed by the contract) - never a commitment the case does not allow.
# Regex extraction (no model call): the bots' e-mails are formulaic (scratchpad/sub-lever/sentences.txt).

KAPPA_CLAUSE = 0.5  # share of the claimed index exposure a clause is worth to the supplier (P18 fit 0.8, P02 >= 0.35)
CONTRACT_SECURITY = 0.005  # per extra year of contract, share of price (P07/P03/P04: welcomed, never priced alone)
MARGIN = 0.05  # a lever sheet must beat the expected close by 5 % of the room (opening C - expected C)
N_FINAL = 5  # bots go final around their 4th-5th reply (practice traces)
LEVER_PRIOR_STEP = 0.01  # its expected step per remaining reply before it has made one (share of its price)
MONTHS = {m: i for i, m in enumerate(
    "january february march april may june july august september october november december".split(), 1)}
NUM = re.compile(r"(\d+(?:[.,]\d+)?)")
RISE = re.compile(r"([A-Z][A-Z0-9-]{2,}) rose ([\d.]+) ?% in twelve months and is (\d+) ?% of our cost")


@dataclass
class Named:
    field: str
    kind: str  # wants | requires | offers | question
    sentence: str
    value: object = None


PATTERNS = [
    ("payment_days", "wants", re.compile(
        r"faster payment|pay(ing)? (us |your invoices )?(faster|on time)|cash (is|flow)|better payment terms|"
        r"\d+[- ]day payment terms?,? which (are|is) necessary|(maintain|keep)(ing)? (our )?(standard )?\d+[- ]day payment|"
        r"standard payment terms of \d+ days", re.I)),
    ("index_clause", "offers", re.compile(
        r"(Preisgleitklausel|index clause|price adjustment clause) on [A-Z]|(must|need to) include (the |an )?"
        r"([A-Z][A-Z0-9-]+ )?index clause|cannot offer a fixed price|insist on the [A-Z][A-Z0-9-]+ index clause", re.I)),
    ("contract_months", "wants", re.compile(
        r"(in return for|welcome|appreciate|agreeable to|support|pleased to).{0,60}\b(24|36|48)[- ]month|"
        r"longer (contract|term|agreement)", re.I)),
    ("volume_per_year", "question", re.compile(r"which volume|binding (higher )?volume|volume commitment", re.I)),
    ("lead_time_days", "requires", re.compile(
        r"lead ?time of \d+ days is not feasible|(maintain|keep) (the )?(lead ?time|Lieferzeit) at \d+|"
        r"must maintain \d+ days|fully booked|capacity utili[sz]ation", re.I)),
    ("effective_date", "wants", re.compile(r"(adjust|move|shift) the effective date to \d{1,2} \w+ \d{4}", re.I)),
    ("ppm_commitment", "offers", re.compile(r"(drop|lower|relax) the ppm commitment to \d+", re.I)),
]


def sentences(body):
    body = re.sub(r"\s+", " ", body or "")
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+(?=[A-Z])", body) if s.strip()]


def extract(body):
    """Every lever a supplier e-mail names: [Named]. Pure regex (the bots' phrasing is formulaic)."""
    out = []
    for s in sentences(body):
        for field, kind, rx in PATTERNS:
            if rx.search(s):
                out.append(Named(field, kind, s))
    return out


def _date(s):
    m = re.search(r"(\d{1,2}) (\w+) (\d{4})", s)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return None


class LeverMixin:
    """Put before the agent class: class X(LeverMixin, SomeAgent). Adds sheets and sentences, never removes the
    main sheet or changes its price."""

    REAL_FULL = 0.98

    # ---------- reading ----------
    def named_levers(self, case, sid, latest_only=False):
        """Levers the supplier named (latest reply first, one per field), with target values. An index it
        blames ("CU-NOTATION rose 47.7 % ... 20 % of our cost") names a clause when we may write one on it."""
        st = self.threads[sid]
        replies = [m for m in st.events if m.get("from") != "buyer"]
        if latest_only:
            replies = replies[-1:]
        out, seen = [], set()
        for m in reversed(replies):
            found = extract(m.get("body"))
            if not latest_only and "index_clause" in case["negotiable"]:
                for series, rise, share in RISE.findall(m.get("body") or ""):
                    if any(c and c.get("series") == series for c in levers.options(case, "index_clause")):
                        found.append(Named("index_clause", "blames", f"{series} rose {rise} %", {series}))
            for n in found:
                if n.field in seen:
                    continue
                seen.add(n.field)
                if n.value is None:
                    n.value = self.target_value(case, sid, n)
                out.append(n)
        return out

    def target_value(self, case, sid, n):
        st, f = self.threads[sid], n.field
        opts = levers.options(case, f)
        theirs = [t.get("terms") or {} for m in st.events if m.get("from") != "buyer" for t in m.get("term_sheets") or []]
        seen = {t.get(f) for t in theirs if isinstance(t.get(f), int | float | str)}
        nums = [float(x.replace(",", ".")) for x in NUM.findall(n.sentence)]
        if f == "payment_days":
            named = [int(x) for x in nums if 7 <= x <= 120 and (int(x) in opts or int(x) in seen)]
            if named:
                return named[0]
            ours = [m["term_sheets"][0].get("terms", {}).get("payment_days") for m in st.events
                    if m.get("from") == "buyer" and m.get("term_sheets")]
            now = next((d for d in reversed(ours) if d), None) or st.opening.get("payment_days") or 60
            faster = [d for d in opts if d < now]
            return (30 if 30 in faster else max(faster)) if faster else None
        if f == "contract_months":
            named = [int(x) for x in nums if int(x) in (opts or [12, 24, 36])]
            return max(named) if named else (max(opts) if opts else None)
        if f == "lead_time_days":
            named = [int(x) for x in nums if int(x) in seen or int(x) in opts]
            return max(named) if named else st.opening.get("lead_time_days")
        if f == "effective_date":
            return _date(n.sentence)
        if f == "ppm_commitment":
            named = [int(x) for x in nums if int(x) in opts or int(x) in seen]
            return named[0] if named else None
        if f == "index_clause":
            series = set(re.findall(r"\b([A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+)+)\b", n.sentence))
            if not series:  # "we must include an index clause": the series its sheets carry
                series = {(t.get("index_clause") or {}).get("series") for t in theirs} - {None}
            return series or None
        if f == "volume_per_year":
            more = [v for v in opts if v > (st.opening.get("volume_per_year") or 0)]
            return min(more) if more else None
        return None

    # ---------- the supplier's side ----------
    def bot_model(self, case, sid, std):
        st = self.threads[sid]
        default = self.p.cash_rate if self.cash_short(sid) else 0.08
        return {
            "standard": closing_terms(case, st.opening, std),
            "interest_rate": implied_rate(st.events, default),
            "ppm": self.real_ppm(case, sid, std),
        }

    def claimed_rise(self, sid, series):
        text = " ".join(m.get("body") or "" for m in self.threads[sid].events if m.get("from") != "buyer")
        rises = [float(r) for s, r, _ in RISE.findall(text) if s == series]
        return max(rises) if rises else None

    def security(self, case, sid, t):
        """Share of price the non-cash terms are worth to the supplier (arena: clause and contract are security)."""
        s = 0.0
        ic = t.get("index_clause")
        if ic:
            rise = self.claimed_rise(sid, ic["series"])
            if rise is None:
                rise = abs((case["buyer"].get("index_paths") or {}).get(ic["series"], 0.0)) * 100
            s += KAPPA_CLAUSE * ic.get("material_share", 0) * max(rise - (ic.get("deadband_pct") or 0), 0) / 100
        std_m = self.threads[sid].opening.get("contract_months") or 12
        if t.get("contract_months"):
            s += CONTRACT_SECURITY * max(0, t["contract_months"] - std_m) / 12
        return s

    def revealed_slopes(self, case, sid):
        """EUR per unit of a numeric field, from its own sheets that differ only in that field and the price
        (P10: 33.60 at 42 days vs 31.70 at 54 -> -0.158 EUR per day of lead time)."""
        out = {}
        for m in self.threads[sid].events:
            if m.get("from") == "buyer":
                continue
            sh = [x.get("terms") or {} for x in m.get("term_sheets") or []]
            for a in sh:
                for b in sh:
                    if a is b or a.get("unit_price") is None or b.get("unit_price") is None:
                        continue
                    diff = [k for k in set(a) | set(b) if k != "unit_price" and a.get(k) != b.get(k)]
                    if len(diff) != 1 or diff[0] in ("payment_days", "index_clause", "contract_months"):
                        continue
                    f = diff[0]
                    if isinstance(a.get(f), int | float) and isinstance(b.get(f), int | float) and a[f] != b[f]:
                        out[f] = (a["unit_price"] - b["unit_price"]) / (a[f] - b[f])
        return out

    def bot_value(self, case, sid, std, t, ref=None):
        """What sheet t is worth to the supplier per unit (cash + security + revealed field premiums vs ref)."""
        sup = self.bot_model(case, sid, std)
        t = closing_terms(case, t, std)
        try:
            v = supplier_value(case, t, sup)
        except Exception:
            return -math.inf
        v += self.security(case, sid, t) * t["unit_price"]
        if ref:
            ref = closing_terms(case, ref, std)
            for f, slope in self.revealed_slopes(case, sid).items():
                if isinstance(t.get(f), int | float) and isinstance(ref.get(f), int | float):
                    v += slope * (t[f] - ref[f])
        return v

    def indifferent_price(self, case, sid, std, sheet, theirs):
        """The price at which `sheet` is worth to the supplier what its current ask is worth (bisection)."""
        target = self.bot_value(case, sid, std, theirs, theirs)
        lo, hi = 0.0, (theirs.get("unit_price") or sheet["unit_price"]) * 2
        for _ in range(50):
            mid = (lo + hi) / 2
            if self.bot_value(case, sid, std, {**sheet, "unit_price": mid}, theirs) < target:
                lo = mid
            else:
                hi = mid
        return hi

    # ---------- our side ----------
    def true_model(self, case, sid, std):
        st = self.threads[sid]
        if case["buyer"].get("category_goal") not in RELATIONSHIP_GOALS or not st.intel.full_cost:
            return self.supplier_estimate(case, sid, std)
        return {
            "full_cost": st.intel.full_cost * self.REAL_FULL,
            "interest_rate": implied_rate(st.events),
            "standard": closing_terms(case, st.opening, std),
        }

    def expected_close(self, case, sid, std, theirs, sup):
        """C of the deal we expect WITHOUT the lever: its ask less its projected remaining steps (its standing
        sheet's own price steps, same terms, last two; bots go final around reply N_FINAL)."""
        st = self.threads[sid]
        c_now = total_cost(case, theirs, std, sup)
        if latest(st.events).get("status") == "final_offer":
            return c_now
        firsts = [(m.get("term_sheets") or [{}])[0].get("terms") or {} for m in st.events
                  if m.get("from") != "buyer" and m.get("term_sheets")]
        steps = []
        for a, b in zip(firsts, firsts[1:]):
            same = all(a.get(k) == b.get(k) for k in set(a) | set(b) if k != "unit_price")
            if same and a.get("unit_price") and b.get("unit_price"):
                steps.append(max(a["unit_price"] - b["unit_price"], 0.0))
        k = max(0, N_FINAL - len(firsts))
        price = theirs.get("unit_price") or 0
        if steps:
            give = sum(steps[-2:]) / len(steps[-2:]) * k
        else:
            # no step of its own seen yet (our first message). The old 0.2 % a round let a lever sheet priced at its
            # indifference to the OPENING ask pass, and the engine agrees to any sheet worth its ask: sweep 13 of 138
            # hidden-like price-increase cases closed at reply 1 (~0.1 instead of ~0.6). Expect its own-plant
            # should-cost room (floors track it: P01 0.99, P02 0.97, P03 1.06 x should-cost), else 1 % a round.
            give = LEVER_PRIOR_STEP * price * k
            if st.intel.full_cost and "its own plant" in (st.intel.full_cost_source or ""):
                give = max(0.002 * price * k, min(give, price - st.intel.full_cost * self.REAL_FULL))
        return total_cost(case, {**theirs, "unit_price": price - give}, std, sup)

    def price_lever(self, case, sid, std, sheet, theirs, main):
        """(price, note) for a lever sheet, or None. See the module docstring."""
        sup = self.true_model(case, sid, std)
        c = lambda p: total_cost(case, {**sheet, "unit_price": p}, std, sup)  # noqa: E731
        e = self.expected_close(case, sid, std, theirs, sup)
        room = abs(total_cost(case, self.threads[sid].opening and closing_terms(case, self.threads[sid].opening, std) or theirs, std, sup) - e)
        target = e - MARGIN * room  # must beat the expected close by a share of this thread's room
        if len(case["suppliers"]) > 1:  # RFQ: a lever sheet must also beat the best rival on the table
            try:
                target = min(target, self.leader_cost(case, {s: ev for s, ev in self._threads_seen.items()}, exclude=sid))
            except Exception:
                pass
        p_ind = self.indifferent_price(case, sid, std, sheet, theirs)
        p = p_ind
        rel = levers.relationship_optimal_price(case, sheet, std, sup, p_ind * 0.9, p_ind * 1.05, steps=300)
        if rel and rel > p:
            p = rel  # higher price, lower C for us (relationship charge): better on both sides
        p = math.ceil(p * 100 - 1e-6) / 100  # the cent goes to the supplier: at p_ind it must not fall short
        if c(p) <= target:
            return p, f"acceptable (p_ind {p_ind:.2f})"
        # the highest price that still beats the expected close: scan down from p_ind
        lo = main["unit_price"]
        best = None
        for i in range(201):
            q = p - (p - lo) * i / 200
            if c(q) <= target:
                best = math.floor(q * 100) / 100
                break
        if best is None or best <= main["unit_price"]:
            return None
        return best, f"trade (p_ind {p_ind:.2f} too dear for us)"

    def lever_sheets(self, case, sid, main, std):
        """[(C_true, sheet, Named, note)] for every named negotiable lever, cheapest for us first."""
        if "unit_price" not in case["negotiable"]:
            return []
        st = self.threads[sid]
        _, theirs = self.their_sheet(case, st.events, std, self.supplier_estimate(case, sid, std))
        if theirs.get("unit_price") is None:
            return []
        theirs = closing_terms(case, theirs, std)
        sup = self.true_model(case, sid, std)
        out = []
        for n in self.named_levers(case, sid):
            if n.field not in case["negotiable"] or n.value is None:
                continue
            variants = []
            if n.field == "index_clause":
                paths = case["buyer"].get("index_paths") or {}
                for c in levers.options(case, "index_clause"):
                    if c and c.get("series") in n.value:
                        variants.append({"index_clause": c})
                if not variants or main.get("index_clause"):
                    continue
                _ = paths
            else:
                if main.get(n.field) == n.value:
                    continue
                rank = levers._supplier_rank
                if main.get(n.field) is not None and rank(n.field, n.value, case) <= rank(n.field, main[n.field], case):
                    continue  # not a step toward the supplier (it accepted our 24 months: no 24-month 'lever' vs 36)
                variants.append({n.field: n.value})
            for change in variants:
                t = complete_offer(case, {**main, **change})
                if not must_haves_ok(case, t, std):
                    continue
                priced = self.price_lever(case, sid, std, t, theirs, main)
                if not priced:
                    continue
                t["unit_price"], note = priced
                out.append((total_cost(case, t, std, sup), t, n, note))
        out.sort(key=lambda x: x[0])
        seen, uniq = set(), []
        for x in out:  # one sheet per field (the clause: its cheapest deadband for us)
            if x[2].field in seen:
                continue
            seen.add(x[2].field)
            uniq.append(x)
        return uniq

    # ---------- the agent hooks ----------
    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if not out:
            return out
        main = out[0]
        found = self.lever_sheets(case, sid, main, std)
        self.threads[sid].lever_notes = []
        if not found:
            return out
        extra = [t for _, t, _, _ in found if t not in out]
        rest = [s for s in out[1:] if s not in extra]
        # a clause sheet from a hedge parent already answers a clause lever
        if any(s.get("index_clause") for s in rest):
            extra = [t for t in extra if not t.get("index_clause")]
        merged = [main] + extra[:2] + rest
        self.threads[sid].lever_notes = [(n, t, note) for _, t, n, note in found if t in merged[:3]]
        self.threads[sid].why += "; levers: " + ", ".join(f"{n.field}->{t['unit_price']} ({note})" for n, t, note in self.threads[sid].lever_notes)
        return merged[:3]

    def answers(self, case, sid, sheets):
        """Sentences for the e-mail: which package answers a lever named in its LATEST reply (a clause package
        always: the template's package line omits the clause); fixed fields it asks about answered honestly."""
        st = self.threads[sid]
        latest_named = {n.field for n in self.named_levers(case, sid, latest_only=True)}
        lines = []
        for n, t, _ in getattr(st, "lever_notes", []):
            idx = next((i for i, s in enumerate(sheets)
                        if all(s.get(k) == t.get(k) for k in case["negotiable"])), None)
            if idx is None or (n.field not in latest_named and n.field != "index_clause"):
                continue
            ic = t.get("index_clause") or {}
            what = {
                "payment_days": f"payment at {t.get('payment_days')} days net",
                "contract_months": f"a binding {t.get('contract_months')}-month agreement",
                "lead_time_days": f"your lead time of {t.get('lead_time_days')} days",
                "effective_date": f"the new price valid from {t.get('effective_date')}",
                "volume_per_year": f"a binding {(t.get('volume_per_year') or 0):,} units a year",
                "ppm_commitment": f"a {t.get('ppm_commitment')} ppm commitment",
                "index_clause": f"a Preisgleitklausel on {ic.get('series')} ({ic.get('material_share', 0):.0%} material share, "
                                f"{ic.get('deadband_pct', 0):g} % deadband, base month {ic.get('base_month')}), which shares the "
                                "index risk with you",
            }.get(n.field)
            if what:
                lead = "As you asked, our" if n.field in latest_named else "Our"
                lines.append(f"{lead} package {idx + 1} gives you {what}, at EUR {t['unit_price']:.2f} per unit.")
        fixed = case.get("fixed_terms") or {}
        main = closing_terms(case, sheets[0], {}) if sheets else {}
        if "volume_per_year" in latest_named and "volume_per_year" not in case["negotiable"]:
            vol, months = fixed.get("volume_per_year") or main.get("volume_per_year"), main.get("contract_months")
            if vol and months:
                lines.append(f"On volume: every package is a binding commitment of {vol:,.0f} units a year for "
                             f"{months:g} months, the full need of this enquiry.")
        if "payment_days" in latest_named and "payment_days" not in case["negotiable"] and fixed.get("payment_days"):
            lines.append(f"On payment: the payment term is fixed at {fixed['payment_days']} days net for this "
                         "contract and is not part of this negotiation.")
        return lines

    def thread_move(self, case, threads, sid):
        self._threads_seen = threads  # read-only snapshot (runner contract): rivals for the RFQ cap
        msg = super().thread_move(case, threads, sid)
        if not msg or not msg.get("term_sheets"):
            return msg
        sheets = [s["terms"] for s in msg["term_sheets"]]
        lines = self.answers(case, sid, sheets)
        if not lines:
            return msg
        addition = "\n".join(lines)

        def explain(body):
            return before_signature(body, addition)

        msg["body"] = explain(msg["body"])
        write = msg.get("_write")
        if write:
            msg["_write"] = lambda: explain(write())
        return msg


class MertLeverAgent(LeverMixin, CseeAgent):
    """Base + an answer to every lever the supplier names (price_increase, renewal, capacity, quality, bundling)."""


class MertLeverRawAgent(LeverMixin, MertAgent):
    """mert/v16 raw material + the same answers (its clause packages stay; lever sheets never touch the main sheet)."""


class MertSkipHedgeAgent(MertAgent):
    """mert/v16 with one change: an index argument on a series the supplier has hedged (its own letter: "covered
    at fixed prices until March 2027") goes last. P08: round 1 cited AS-14404 in every run and got "not our
    reality"; the unhedged PPI-C2431 fall got "took it into account" and the big step, one round later."""

    def prepare(self, case, threads):
        super().prepare(case, threads)
        if not self.raw:
            return
        series = material_series(case)
        for sid, st in self.threads.items():
            if hedge_of(self.pkg, sid) is None:
                continue
            # Emre's claims carry no tag: read the series from the cited ID (idx:AS-14404@2026-06)
            hedged = [
                c for c in st.intel.claims
                if c.kind == "index" and any(i.startswith("idx:") and i[4:].split("@")[0] in series for i in c.ids)
            ]
            st.intel.claims = [c for c in st.intel.claims if c not in hedged] + hedged

# ---------------------------------------------------------------------------------------------------------
# The planner (mert-plan*): Online move planner: exploit the supplier engine's concession rule (scratchpad/sub-engine/engine.py).
#
# Engine rule (fitted on 260 sessions): reply 1 gives s1; reply k>1 gives min(m * our value step, cap_k), cap_k =
# cap * dec^(k-2); a hold (no value step) gets a hold; final at reply N, or from reply K0 if our gap > G; some walk on
# a deep gap; any sheet of ours worth >= its ask is agreed.
#
# So a supplier's total give is s1 + sum of the caps we actually extract, and our asks matter only through
#   (1) the step we make each round (>= cap/m extracts the full cap; less wastes it; a value DROP makes it hold),
#   (2) the gap after its reply (too big from K0 -> early final; deep -> walk risk),
#   (3) crossing (our ask >= its next ask ends the thread at our price, before the remaining caps).
# The planner works in the supplier's value units (our estimate: supplier_value at its implied money rate):
#   - anchor `anchor` below its opening value;
#   - estimate the next cap online: its last step when that was clearly smaller than m_lo x our step (capped), else a
#     probe (`probe` x V0 before any evidence, `grow` x its last step after an uncapped mirror);
#   - our next ask = max(extract the full predicted cap: B + c/m_lo,  hit the gap budget: A - c - target_gap),
#     target_gap = min(gap we need to keep extracting full caps until reply n_plan, gmax[k] x A),
#     never above A - max(tick, cross_buf x c) (no crossing), never below our last ask (no holds);
#   - stop writing (accept) when it stops moving twice while we move, or at the relationship-optimal price.
# Terms stay the parent agent's (best_terms, sticky, lever/clause sheets); only the main price changes, and extra
# sheets are re-priced so none is worth more to the supplier than the main (the engine counters on the sheet worth
# most to it and measures our step on that sheet: base's churn of trade sheets made P01 hold twice).
# Engine evaluation: scratchpad sub-planner (evalp.py: 9 single-supplier cases x 60 perturbed personas).

@dataclass
class PlanParams:
    anchor: float = 0.12  # first ask below its opening (value)
    anchor_rel: float = 0.12  # relationship goals (stabilise / secure_supply)
    anchor_raw: float = 0.22  # raw material (index-driven, big first steps: P08/P18 s1 ~8 %)
    probe: float = 0.03  # our step after reply 1 (share of V0), before any cap evidence
    m_lo: float = 0.75  # lowest mirror ratio we plan for (fits: 0.5 .. 1.3)
    grow: float = 1.3  # it mirrored us in full: assume the cap is at least this x its step
    dec: float = 0.8  # cap decay per reply (fits 0.6 / 0.8 / 1.0)
    n_plan: int = 5  # the reply we expect its final at (fits: 4 / 5 / 6, tiny-cap ones 8)
    gmax: tuple = (0.12, 0.08, 0.04, 0.03, 0.025, 0.02)  # max gap after reply 1, 2, 3, ... (share of its ask)
    cross_buf: float = 0.6  # keep at least this x its predicted step between our ask and its ask
    safety: float = 0.5  # extra gap (x predicted cap) on top of the need
    frozen_after: int = 99  # was 2 (stop and accept after it held twice while we moved): P11 held 46.00 twice, we accepted; waiting got 45.50 as its final (0.626 vs 0.71)
    default_rate: float = 0.08  # its money rate until its own sheets reveal it
    smooth_ticks: bool = False  # coarse price ticks: average its last two capped steps
    rfq: bool = False  # plan RFQ threads too (default: parent's RFQ logic)
    tick_rule: bool = False  # steps >= 1 tick and a gap that leaves room for tick steps until its final (P11 lesson)


class PlanMixin:
    """Put first: class X(PlanMixin, Parent). Parent decides terms; the planner decides the main price."""

    plan = PlanParams()
    dossier_plan = False  # True: supplier-specific PlanParams from csee/dossier (fitted personas only, else defaults)

    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.plan_by = {}
        if self.dossier_plan:
            from .. import dossier

            for sid in case["suppliers"]:
                ov = dossier.plan_overrides(dossier.get(sid, self.pkg), case, self.plan)
                try:
                    if ov:
                        self.plan_by[sid] = replace(self.plan, **ov)
                except (TypeError, ValueError):
                    continue
        self.case_negotiable = list(case["negotiable"])
        # the planner decides when a thread is done: the parent's close-gap stop must never fire
        self.p = replace(self.p, close_gap=-1.0, close_room=0.0, final_push=0.0, push_after_final=0)
        self.planned = not (len(case["suppliers"]) > 1 and not self.plan.rfq)

    # ---------- the supplier's value, our estimate ----------
    def sup_model(self, case, sid, std):
        st = self.threads[sid]
        base = {"standard": closing_terms(case, st.opening, std), "ppm": self.real_ppm(case, sid, std)}
        rate = self.revealed_rate(case, sid, base)
        return {**base, "interest_rate": rate if rate is not None else self.plan_for(sid).default_rate}

    def plan_for(self, sid):
        """This supplier's PlanParams: the dossier's priors when dossier_plan is on and it has them, else `plan`."""
        return (getattr(self, "plan_by", None) or {}).get(sid, self.plan)

    def revealed_rate(self, case, sid, base):
        """Its money rate from two of its sheets that differ only in payment days: the rate at which both are
        worth the same to it (supplier_value, so a late effective date's old units count; mert.implied_rate's
        price ratio read P01 as 15 % instead of the engine's 9.5 %)."""
        rates = []
        for m in self.threads[sid].events:
            if m.get("from") == "buyer":
                continue
            sh = [x.get("terms") or {} for x in m.get("term_sheets") or []]
            for a in sh:
                for b in sh:
                    if not (a.get("unit_price") and b.get("unit_price") and a.get("payment_days") and b.get("payment_days")):
                        continue
                    if a["payment_days"] <= b["payment_days"] or a["unit_price"] <= b["unit_price"]:
                        continue
                    if not all(a.get(f) == b.get(f) for f in set(a) | set(b) if f not in ("payment_days", "unit_price")):
                        continue
                    lo, hi = 0.0, 0.5
                    f = lambda r: self.sval(case, {**base, "interest_rate": r}, a) - self.sval(case, {**base, "interest_rate": r}, b)
                    try:
                        if f(lo) * f(hi) > 0:
                            continue
                        for _ in range(40):
                            mid = (lo + hi) / 2
                            if f(lo) * f(mid) <= 0:
                                hi = mid
                            else:
                                lo = mid
                        rates.append((lo + hi) / 2)
                    except Exception:
                        continue
        rates = [r for r in rates if 0.0 < r < 0.4]
        return sum(rates[-2:]) / len(rates[-2:]) if rates else None

    def sval(self, case, sup, t):
        try:
            return supplier_value(case, closing_terms(case, t, sup["standard"]), sup)
        except Exception:
            return None

    def price_at_value(self, case, sup, t, v):
        """Price at which sheet t is worth v to the supplier (value is linear in price)."""
        p0 = t.get("unit_price") or 1.0
        v0, v1 = self.sval(case, sup, {**t, "unit_price": p0}), self.sval(case, sup, {**t, "unit_price": p0 + 1.0})
        if v0 is None or v1 is None or v1 - v0 <= 1e-9:
            return None
        return p0 + (v - v0) / (v1 - v0)

    @staticmethod
    def tick_of(prices):
        prices = [p for p in prices if p]
        for t in (0.5, 0.1, 0.05):
            if len(prices) >= 2 and all(abs(p / t - round(p / t)) < 1e-6 for p in prices):
                return t
        return 0.01

    def same_terms(self, a, b):
        return all(a.get(f) == b.get(f) for f in self.case_negotiable if f != "unit_price")

    def history(self, case, sid, sup):
        """(B, A, S, prices). B[j-1]: value of our message j's sheet that its reply j countered on (same non-price
        terms; else our sheet worth most to it); A[j]: value of its reply j's first sheet (A[0] = opening);
        S[j-1] = A[j-1] - A[j] on the SAME terms (None when its terms changed: our value model is not exact
        across terms, P01 r2 looked like a rise)."""
        B, A, S, theirs, prev, pending, v_prev = [], [], [], [], None, None, None
        for m in self.threads[sid].events:
            sh = [x.get("terms", x) for x in m.get("term_sheets") or []]
            sh = [t for t in sh if t.get("unit_price") is not None]
            if not sh:
                continue
            if m.get("from") == "buyer":
                pending = sh
                continue
            t = sh[0]
            v = self.sval(case, sup, t)
            if v is None:
                continue
            if pending:
                match = [x for x in pending if self.same_terms(x, t)]
                vals = [self.sval(case, sup, x) for x in (match or pending)]
                vals = [x for x in vals if x is not None]
                if vals:
                    B.append(max(vals))
                pending = None
            if prev is not None and v_prev is not None:
                S.append(v_prev - v if self.same_terms(prev, t) else None)
            A.append(v)
            theirs.append(t["unit_price"])
            prev, v_prev = t, v
        return B, A, S, theirs

    # ---------- the plan ----------
    def plan_value(self, case, threads, sid, sup, left):
        """Target value of our next main sheet, or (None, why) to stop writing."""
        P = self.plan_for(sid)
        B, A, S, theirs = self.history(case, sid, sup)
        if not A:
            return None, "no supplier value"
        V0 = A[0]
        k = len(A) - 1  # replies after its opening
        if k == 0 or not B:
            a = P.anchor_raw if case.get("type") == "raw_material" else P.anchor
            if case["buyer"].get("category_goal") in RELATIONSHIP_GOALS:
                a = P.anchor_rel
            return V0 * (1 - a), f"anchor {a:.0%} below its opening value"
        if len(B) < k:  # a message without a sheet: align on the latest
            k = len(B)
        A_k, B_k = A[-1], B[-1]
        tickv = self.tick_of(theirs) * (A_k / theirs[-1] if theirs[-1] else 1.0)
        # observations (our step D, its step S) for replies j >= 2; S None when its terms changed
        obs = []
        for j in range(2, k + 1):
            if j - 1 < len(B) and j - 1 < len(S):
                obs.append((B[j - 1] - B[j - 2], S[j - 1]))
        # frozen: it did not move although we did
        frozen = 0
        for d, s in reversed(obs):
            if s is None or d <= 0.5 * tickv or s > 0.5 * tickv:
                break
            frozen += 1
        if frozen >= P.frozen_after:
            return None, f"it held {frozen}x while we moved: accept"
        if A_k <= B_k + 0.5 * tickv:
            return None, "its ask meets ours"
        # cap estimate for the next reply
        dec, caps, last = P.dec, [], None
        for d, s in obs:
            if s is None or d <= 0.5 * tickv:
                continue
            capped = s < 0.8 * P.m_lo * d - tickv  # clearly less than a mirror
            last = (capped, max(s, 0.0))
            if capped:
                caps.append(max(s, 0.0))
        if last is None:
            c_hat = P.probe * V0 * P.m_lo
        elif last[0]:
            if len(caps) >= 2 and caps[-2] > 0 and caps[-1] > 0:
                dec = min(1.0, max(0.5, caps[-1] / caps[-2]))
            c_hat = last[1] * dec
            if P.smooth_ticks and len(caps) >= 2 and tickv > 0.3 * max(caps[-1], 1e-9):
                c_hat = (caps[-1] + caps[-2]) / 2 * dec
        else:
            c_hat = last[1] * P.grow
        c_hat = max(c_hat, 0.5 * tickv)
        # the gap we want after its next reply
        n_plan = P.n_plan
        rl = self.rounds_left(sid, left)
        n_plan = min(n_plan, k + max(rl - self.p.reserve_moves, 1))
        n_rem = max(n_plan - (k + 1), 1)
        need = sum(c_hat * dec**i for i in range(1, n_rem + 1)) * (1 + 1 / P.m_lo) + P.safety * c_hat
        if P.tick_rule:
            # a coarse-tick supplier only drops a tick when our step is at least one (P11: +0.55 steps got 45.00,
            # the planner's +0.02 last steps rounded to nothing): keep room for a tick step each side per reply
            need = max(need, 2.1 * tickv * n_rem)
        gi = min(k, len(P.gmax) - 1)  # gmax[0] = after reply 1; the next reply is k + 1
        g_target = min(need, P.gmax[gi] * A_k)
        B_gap = (A_k - c_hat) - g_target
        B_ext = B_k + c_hat / P.m_lo
        B_new = max(B_gap, B_ext)
        if P.tick_rule:
            B_new = max(B_new, B_k + 1.05 * tickv)
        B_cross = A_k - max(tickv, min(P.cross_buf * c_hat, 0.5 * (A_k - B_k)))
        why = f"r{k + 1}: c^ {c_hat / V0:.2%} gap {((A_k - B_k) / A_k):.2%} -> target {g_target / A_k:.2%}"
        if B_new > B_cross:
            B_new = B_cross
            why += " (no-cross cap)"
        B_new = max(B_new, B_k)
        return B_new, why

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        ours = super().next_terms(case, threads, sid, theirs, std, supplier, left)
        if ours is None or not getattr(self, "planned", False) or "unit_price" not in case["negotiable"]:
            return ours
        st = self.threads[sid]
        st.events = threads[sid]
        sup = self.sup_model(case, sid, std)
        # relationship goals: no gain below the relationship-optimal price - accept there
        b = case["buyer"]
        if b.get("category_goal") in RELATIONSHIP_GOALS and st.intel.full_cost and theirs.get("unit_price"):
            real = {**sup, "full_cost": st.intel.full_cost * getattr(self.p, "rel_full", 0.98)}
            p_rel = levers.relationship_optimal_price(case, ours, std, real, real["full_cost"] * 0.9, theirs["unit_price"])
            if p_rel and theirs["unit_price"] <= p_rel * 1.002 and any(m.get("from") == "buyer" for m in threads[sid]):
                st.why = f"its ask {theirs['unit_price']} at the relationship optimum {p_rel}: ready"
                return None
        v, why = self.plan_value(case, threads, sid, sup, left)
        st.plan_v = None
        if v is None:
            st.why = "plan: " + why
            return None
        st.plan_v = v
        p = self.priced(case, sid, sup, ours, v)
        if p is None:
            return ours
        st.why = "plan " + why + f" -> {p:.2f}"
        return {**ours, "unit_price": p}

    def last_sent(self, sid):
        for m in reversed(self.threads[sid].events):
            if m.get("from") == "buyer" and m.get("term_sheets"):
                return [x.get("terms", x) for x in m["term_sheets"]]
        return []

    def last_counter(self, sid):
        for m in reversed(self.threads[sid].events):
            if m.get("from") != "buyer" and m.get("term_sheets"):
                return m["term_sheets"][0].get("terms") or {}
        return None

    def priced(self, case, sid, sup, t, v):
        """Price of sheet t at value v; never below what we asked last time for the same terms (no hold)."""
        p = self.price_at_value(case, sup, t, v)
        if p is None:
            return None
        p = math.floor(p * 100 + 1e-6) / 100
        before = [x["unit_price"] for x in self.last_sent(sid) if self.same_terms(x, t)]
        if before and p < max(before) + 0.01:
            p = round(max(before) + 0.01, 2)
        return round(p, 2)

    def xc_sync_plan(self, case, sid, events, ours):
        """Cross-check xc_pace changed the main price after plan_value: re-plan at that price, or sheets() below
        would price the main sheet back at the old plan_v (restore_main_plan) and the pacing would never be sent."""
        st = self.threads[sid]
        if getattr(st, "plan_v", None) is None or not getattr(self, "planned", False):
            return
        try:
            v = self.sval(case, self.sup_model(case, sid, standard_terms(events)), ours)
        except Exception:
            v = None
        if v is not None:
            st.plan_v = v

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        st = self.threads[sid]
        v_plan = getattr(st, "plan_v", None)
        if not getattr(self, "planned", False) or "unit_price" not in case["negotiable"] or v_plan is None:
            return out
        sup = self.sup_model(case, sid, std)
        levers_sent = [t for _, t, _ in getattr(st, "lever_notes", [])]
        # the sheet it countered on last time carries the plan (the engine counters on our sheet worth most to it
        # and measures our step on it); every other sheet is worth at most that much to it
        counter = self.last_counter(sid) if any(m.get("from") == "buyer" for m in st.events) else None
        bi = next((i for i, x in enumerate(out) if counter and self.same_terms(x, counter) and x not in levers_sent), 0)
        # Parent builders can reprice sheet zero. The raw challenger opts into restoring its plan;
        # keep the independently validated team planners' existing sheet-zero behaviour.
        if bi or getattr(self, "restore_main_plan", False):
            p = self.priced(case, sid, sup, out[bi], v_plan)
            if p is not None and csee_must_haves_ok(case, {**out[bi], "unit_price": p}, std):
                out[bi] = {**out[bi], "unit_price": p}
            else:
                bi = 0
        v_b = self.sval(case, sup, out[bi])
        if v_b is None:
            return out
        fixed = []
        for i, s in enumerate(out):
            if i != bi and s not in levers_sent:
                v = self.sval(case, sup, s)
                if v is not None and v > v_b:
                    p = self.price_at_value(case, sup, s, v_b)
                    if p is None:
                        continue
                    s = {**s, "unit_price": math.floor(p * 100) / 100}
                    if not csee_must_haves_ok(case, s, std):
                        continue
            if s not in fixed:
                fixed.append(s)
        return fixed[:3]


class PlannerAgent(PlanMixin, CseeAgent):
    """Base terms + the planner (renewal, capacity, quality, bundling, unknown)."""


class PlannerLeverAgent(PlanMixin, MertLeverAgent):
    """mert-lever (clause / named-lever sheets) + the planner (price_increase)."""


class PlannerRawAgent(PlanMixin, MertSkipHedgeAgent, MertConsistentAgent):
    """Unrouted raw challenger: hedge-aware evidence, consistent clauses and planned concessions.

    The two raw parents share MertAgent: keep the existing evidence ordering and the already-tested
    clause-continuity rule without changing the selected raw-material champion.
    """

    restore_main_plan = True

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if not self.raw or not getattr(self, "planned", False) or not out or "unit_price" not in case["negotiable"]:
            return out
        # Two payment trades can have the same non-price terms. Keep the first (the revealed-rate
        # trade precedes the generic one), leaving space for a different, useful package.
        distinct = []
        for sheet in out:
            if not any(self.same_terms(sheet, previous) for previous in distinct):
                distinct.append(sheet)
        main = distinct[0]
        if not main.get("index_clause") or "contract_months" not in case["negotiable"]:
            return distinct
        longer = [m for m in levers.options(case, "contract_months") if m > main["contract_months"]]
        if not longer:
            return distinct
        # A longer INDEXED contract remains feasible after the supplier rejects long fixed prices.
        # Price the commitment as a real trade, bounded by both buyer cost and the planned supplier value.
        trade = {**main, "contract_months": max(longer)}
        sup = self.sup_model(case, sid, std)
        values = [self.sval(case, sup, sheet) for sheet in distinct]
        if any(value is None or not math.isfinite(value) for value in values):
            return distinct
        ceiling = max(values)
        target = total_cost(case, main, std, supplier) * (1 - self.p.trade_gain)
        buyer_price = levers.price_for(case, trade, target, std, supplier)
        supplier_price = self.price_at_value(case, sup, trade, ceiling)
        if buyer_price is None or supplier_price is None:
            return distinct
        trade["unit_price"] = math.floor(min(buyer_price, supplier_price) * 100 + 1e-6) / 100
        if total_cost(case, trade, std, supplier) > target:
            trade["unit_price"] = round(trade["unit_price"] - .01, 2)
        previous = [sheet["unit_price"] for sheet in self.last_sent(sid) if self.same_terms(sheet, trade)]
        if (
            trade["unit_price"] <= 0
            or (previous and trade["unit_price"] <= max(previous))
            or not csee_must_haves_ok(case, trade, std)
            or total_cost(case, trade, std, supplier) > target
            or self.sval(case, sup, trade) > ceiling + 1e-9
        ):
            return distinct
        return [main, trade, *[sheet for sheet in distinct[1:] if not self.same_terms(sheet, trade)]][:3]


class MertScopedWriter(LLMWriter):
    """Candidate-only writer: do not promise concessions on immutable case terms."""

    SYSTEM = LLMWriter.SYSTEM + (
        '\nThe FIXED TERMS are binding facts, not options. State them accurately when relevant. '
        'Never promise to change or separately negotiate them. Answer volume questions from '
        'those facts; do not invent an internal review or extra commitments. '
        'Only the NEGOTIABLE fields may change.'
    )

    def write(self, case, agent, sid, events, sheets, claims, ask_breakdown, focus=''):
        scope = 'FIXED TERMS: ' + json.dumps(case.get('fixed_terms', {}), separators=(',', ':'))
        scope += '; NEGOTIABLE: ' + ','.join(case['negotiable'])
        return super().write(case, agent, sid, events, sheets, claims, ask_breakdown,
                             focus=scope + ('; ' + focus if focus else ''))


def scoped_writer(writer):
    if type(writer) is LLMWriter:
        return MertScopedWriter(writer.complete, writer.budget_s)
    return writer


class MertQualityMenuAgent(CseeAgent):
    """Isolated quality/price menu. Each relaxed commitment costs no more than main.

    Uses only allowed negotiable terms; fixed payment and volume stay fixed. No
    supplier-specific scores or prices, and no post-final negotiation override.
    """

    scope_writer = False  # separate ablation; leave the successful first live policy unchanged

    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.p = replace(self.p, final_push=0.0, push_after_final=0)
        if self.scope_writer:
            self.writer = scoped_writer(self.writer)

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if (case.get('type') != 'quality' or not out
                or not {'unit_price', 'ppm_commitment'} <= set(case['negotiable'])):
            return out
        main = out[0]
        target = total_cost(case, main, std, supplier)
        menu = [main]
        for ppm in sorted(levers.options(case, 'ppm_commitment')):
            if ppm <= main.get('ppm_commitment', 0):
                continue
            t = complete_offer(case, {**main, 'ppm_commitment': ppm})
            if not must_haves_ok(case, t, std):
                continue
            price = levers.price_for(case, t, target, std, supplier)
            if price is None or price <= 0:
                continue
            t['unit_price'] = price
            # price_for rounds to nearest cent; round toward the buyer if necessary.
            if total_cost(case, t, std, supplier) > target + 1e-7:
                t['unit_price'] = round(price - .01, 2)
            # Never retract an actual earlier offer for this same structure.
            prior = [x.get('terms', {}) for m in self.threads[sid].events
                     if m.get('from') == 'buyer' for x in m.get('term_sheets') or []]
            prices = [p['unit_price'] for p in prior if p.get('unit_price') is not None
                      and all(p.get(k) == t.get(k) for k in case['negotiable'] if k != 'unit_price')]
            if prices:
                t['unit_price'] = max(t['unit_price'], max(prices))
            if (t['unit_price'] > 0 and must_haves_ok(case, t, std)
                    and total_cost(case, t, std, supplier) <= target + 1e-7):
                menu.append(t)
            if len(menu) == 3:
                break
        return menu


class MertFixedProbeAgent(MertLeverAgent):
    """P02-only research probe: one fixed 368/90 offer before normal lever fallback.

    Practice-specific candidate, deliberately NOT a final route. The price is an
    offline-scored hypothesis, not evidence of acceptance. Other cases unchanged.
    """

    fixed_prices = (368.0,)

    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.p = replace(self.p, final_push=0.0, push_after_final=0)
        self.writer = scoped_writer(self.writer)
        for sid, events in threads.items():
            self.threads[sid].events = list(events)

    def fixed_probe(self, case, sid):
        return (case.get('case_id') == 'case:P02'
                and sum(m.get('from') == 'buyer' for m in self.threads[sid].events) < len(self.fixed_prices)
                and {'unit_price', 'payment_days', 'index_clause'} <= set(case['negotiable'])
                and 90 in levers.options(case, 'payment_days')
                and None in levers.options(case, 'index_clause'))

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        if self.fixed_probe(case, sid):
            n = sum(m.get('from') == 'buyer' for m in self.threads[sid].events)
            t = complete_offer(case, {**theirs, 'unit_price': self.fixed_prices[n],
                                      'payment_days': 90, 'index_clause': None})
            if must_haves_ok(case, t, std):
                self.threads[sid].why = f'isolated P02 fixed-price probe {n + 1}/{len(self.fixed_prices)}; bounded clause fallback'
                return t
        return super().next_terms(case, threads, sid, theirs, std, supplier, left)

    def sheets(self, case, sid, ours, std, supplier):
        if self.fixed_probe(case, sid):
            return [complete_offer(case, ours)]
        return super().sheets(case, sid, ours, std, supplier)


class MertFixedLadderAgent(MertFixedProbeAgent):
    """P02-only bounded fixed-price negotiation before opening the clause fallback.

    Tests whether the first probe ended too early by offering an immediately
    acceptable clause. All four fixed targets score above the clause ceiling if
    accepted under the calibrated practice economics. Does not override closing.
    """

    fixed_prices = (364.0, 366.0, 368.0, 369.0)


class MertRawJointMenuAgent(MertSkipHedgeAgent):
    """Raw-material probe: intermediate payment and narrower deadband together.

    Keep the parent main offer. Price two alternative structures at equal buyer
    cost; this measures whether extra index security unlocks a better counter.
    Never change coverage or promise a lower price on a previously sent structure.
    """

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if (case.get('type') != 'raw_material' or not out
                or not {'unit_price', 'payment_days', 'index_clause'} <= set(case['negotiable'])):
            return out
        main = out[0]
        clause = main.get('index_clause')
        if not clause:
            return out
        days = sorted(levers.options(case, 'payment_days'))
        inner = days[1:-1]
        clauses = sorted([c for c in levers.options(case, 'index_clause')
                          if c and c['series'] == clause['series']
                          and c['deadband_pct'] < clause['deadband_pct']],
                         key=lambda c: c['deadband_pct'], reverse=True)
        if not inner or not clauses:
            return out
        # Prefer the middle payment options, not the already-tested endpoints.
        chosen_days = sorted(inner, key=lambda d: abs(d-days[len(days)//2]))
        target = total_cost(case, main, std, supplier)
        menu = [main]
        for d, index in zip(chosen_days, clauses):
            t = complete_offer(case, {**main, 'payment_days': d, 'index_clause': index})
            price = levers.price_for(case, t, target, std, supplier)
            if price is None or price <= 0:
                continue
            t['unit_price'] = price
            if total_cost(case, t, std, supplier) > target + 1e-7:
                t['unit_price'] = round(price - .01, 2)
            prior = [x.get('terms', {}) for m in self.threads[sid].events
                     if m.get('from') == 'buyer' for x in m.get('term_sheets') or []]
            prices = [p['unit_price'] for p in prior if p.get('unit_price') is not None
                      and all(p.get(k) == t.get(k) for k in case['negotiable'] if k != 'unit_price')]
            if prices:
                t['unit_price'] = max(t['unit_price'], max(prices))
            if (t['unit_price'] > 0 and must_haves_ok(case, t, std)
                    and total_cost(case, t, std, supplier) <= target + 1e-7):
                menu.append(t)
            if len(menu) == 3:
                break
        return menu
