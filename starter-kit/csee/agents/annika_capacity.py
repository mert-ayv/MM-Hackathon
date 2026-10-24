"""annika-k: the expert buyer for `capacity` cases (a supplier that is full allocates, stretches lead times
and prices its scarce capacity). Every other case type plays exactly as base v14.

Evidence (P10 replays, 309 practice + sandbox sessions, docs/playbooks/capacity.md):
- Patience is the supplier's own: P10 answered our FIRST e-mail with its final offer although our ask sat
  above its floor (the deep-ask patience cut needs an ask ~7 %+ below the floor: D01, P07, P11, P18 cut;
  D02-C1 at 22 % below its opening but 4.5 % below its floor did not). So the first e-mail decides the case.
- Ask depth does not move a first counter (D01: asks 43.38 / 46.55 / 47.50 -> 52.2-52.4 every time); verified
  arguments the supplier "takes into account" do (D01 52.3 -> 50.7 with two; P18 -3.4 %, P11 -1 %; about
  1 % per argument, 0-3 %). P10 took should-cost into account and ignored on-time delivery. A forecast
  claim ("volume change") was taken into account by every supplier that saw one (P01, P02, P03, P07).
- It prices lead time faster than its standard (P10: 1.90 EUR/unit for 54 -> 42 days, 0.5 %/day) far above
  what the days cost us (a one-off late cost: 28,800 EUR = 0.61 EUR/unit). Its own standard lead time is a
  valid value for a sheet (P10 agreed 54 days proposed back).
- Pushing after a final offer: 20 pushes <= 1 %: 6 agreed, 12 held, 2 walked (P02, P18). Without an
  alternative a walk scores 0, so we never push.
- It agrees to its own sheets proposed back and picks the sheet worth most to it among ours.

The rules, over the case file (no supplier names):
1. Coverage: volume = the smallest option >= need that keeps the must-haves; contract = the longest option
   (months beyond the horizon cost us nothing and buy allocation priority).
2. Lead time: one sheet at the supplier's own standard lead time (its opening), one at our need; the one
   cheaper for us at its expected pricing (premium prior 0.5 %/day vs our late cost) goes first. Both
   carry the same value to it, so neither reads as a softer ask.
3. Price (H2, after practice #2): a moderate anchor, 3.75 % below its opening at its standard lead time
   (inside the owner range, below its ~2 % desk band), never below the relationship floor (should-cost x 0.98 /
   (1 - sustainable margin)); our need-lead sheet at the value-equivalent price. v13's 17 % value ask drew a
   final offer at reply 1, annika-k's 12 % an open reply.
4. Arguments (first e-mail, up to 3 checked): should-cost (when its opening is clearly above the
   sustainable price), our forecast growth with a firm commitment, our order history at today's price
   (when it asks more), a falling cost driver, a short notice. No delivery or quality attacks on a sole
   source in the first e-mail. Ask for a delivery schedule, not a cost breakdown (refused on policy).
5. Closing: price every sheet it sends, take the cheapest valid one (proposing an alternative back word for
   word); no push after a final offer; never walk without a cheaper alternative.
6. Rounds 2+ (H2 "converge"): one sheet on its own non-price terms (the sheet cheapest for us), coverage locked,
   our price a little closer every round (20 % of the gap, shrinking 0.65x, at least 0.15 % of its price),
   always strictly below its standing price, never a retreat (practice #2: our R2 at 42 d and a lower value
   plus an on-time-delivery claim drew "My call: hold" -> final). Only unused non-attacking arguments.
   `KParams(mode="v14")` restores base v14 logic for rounds 2+.

    uv run python -m csee --agent annika-k sim --cases case:P09 case:P10     free, offline
"""

import re
from dataclasses import dataclass

from arena_kit.cost import RELATIONSHIP_GOALS, complete_offer, total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import latest

from .. import intel as intel_mod
from .. import levers, variants
from ..agent import CseeAgent, Params, must_haves_ok
from ..writer import SIGN, describe


@dataclass(frozen=True)
class KParams:
    # H2 (practice #2, 223df3b28256069f): a 12 % value ask got an OPEN first reply (v13's 17 % got a final
    # offer), and our R2 retreat (42 d at a lower value + an on-time-delivery attack) drew "My call: hold" ->
    # final. So: a moderate anchor inside the owner range, then small steady steps on its own terms.
    anchor_below_open: float = 0.0375  # first ask at its standard lead time, below its opening
    mode: str = "converge"  # rounds 2+: "converge" (H2) or "v14" (base logic, coverage locked)
    converge_share: float = 0.2  # first step: this share of the gap to its standing price ...
    converge_decay: float = 0.65  # ... shrinking by this factor every round (31.00 -> 31.14 -> 31.24 -> 31.30)
    min_step: float = 0.0015  # but at least this share of its price (keeps visibly converging)
    stay_below: float = 0.01  # never ask within this many EUR of its standing price
    # k9j (after practice #3, 0.679: patience exactly 2, its R2 mirrored our 0.48 step with 0.10, landing on the
    # 2 % desk band 31.56 -> 31.60): one large R2 step to just below the record-equivalent, "ready to sign today"
    jump: bool = False  # R2: jump to min(its price - jump_abs, its price x (1 - jump_pct)) on its price grid
    jump_abs: float = 0.40
    jump_pct: float = 0.013
    appreciation: bool = False  # R1: cite its green scorecard ppm as appreciation (only if green throughout)
    pay_on_terms: bool = False  # R1, words only: "we pay on terms" if our invoices are <= 2 days late on average
    lead_premium: float = 0.005  # prior: what a full supplier charges per day faster than its standard (P10 fit)
    std_lead_sheet: bool = True  # also offer its own standard lead time
    first_claims: tuple = ("should_cost", "forecast", "history", "index", "notice")
    min_forecast_pct: float = 3.0  # cite forecast growth from this change on
    should_cost_room: float = 1.05  # cite should-cost only if its opening > sustainable price x this
    ask_schedule: bool = True  # ask for a delivery schedule (the document capacity cases render)


FORECAST_OK = ("should_cost", "forecast", "history", "index", "notice")


class AnnikaCapacityAgent(CseeAgent):
    K = KParams()

    def __init__(self, package=None, writer=None, params=None):
        # base v14 unless a variant is passed explicitly (v14 is what the router plays for capacity today)
        if params is None or params == Params():
            params = variants.params("v14")
        super().__init__(package, writer, params)
        self.plans = {}

    # ---------- preparation ----------
    @staticmethod
    def is_capacity(case):
        return case.get("type") == "capacity"

    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.plans = {}
        if not self.is_capacity(case):
            return
        for sid in case["suppliers"]:
            try:
                self.plans[sid] = self.plan(case, threads, sid)
            except Exception as e:  # a plan that fails falls back to base v14, never costs the case
                self.plans[sid] = None
                if self.log.enabled:
                    self.log.event(
                        "decision", round=1, supplier_id=sid, kind="note", reason=f"capacity plan failed: {e!r}"
                    )
            # a group refuses cost breakdowns on policy (P10); we ask for the delivery schedule instead
            self.threads[sid].asked_breakdown = True

    def plan(self, case, threads, sid):
        """The first e-mail's terms, computed from the case file, its opening and our data."""
        b, neg = case["buyer"], case["negotiable"]
        st = self.threads[sid]
        std = standard_terms(threads.get(sid) or [])
        opening = dict(st.opening)
        need, horizon = b["need_per_year"], b["horizon_years"]
        fixed = {}
        probe = complete_offer(case, {**opening, "unit_price": opening.get("unit_price")})
        if "volume_per_year" in neg:
            opts = sorted(levers.options(case, "volume_per_year"))
            ok = [v for v in opts if v >= need and must_haves_ok(case, {**probe, "volume_per_year": v}, std)]
            fixed["volume_per_year"] = ok[0] if ok else (max(opts) if opts else need)
        if "contract_months" in neg:
            opts = levers.options(case, "contract_months")
            fixed["contract_months"] = max(opts) if opts else max(round(12 * horizon), 12)
        years = min(fixed.get("contract_months", (std or {}).get("contract_months") or 12) / 12 or 1.0, horizon)
        committed = (fixed.get("volume_per_year") or opening.get("volume_per_year") or need) * years
        leads = None
        if "lead_time_days" in neg:
            opts = sorted(levers.options(case, "lead_time_days"))
            need_lt = b["need_lead_time_days"]
            ours = max((o for o in opts if o <= need_lt), default=None) if opts else need_lt
            if ours is None:
                ours = min(opts)
            its = opening.get("lead_time_days") or (std or {}).get("lead_time_days")
            if its is None:
                its = ((st.intel.profile.get("standard_terms_hint") or {}).get("lead_time_days")) or ours
            if not must_haves_ok(case, {**probe, **fixed, "lead_time_days": its}, std):
                its = levers.nearest_ok(case, "lead_time_days", its) or ours
            leads = (ours, its)
        p_open = opening.get("unit_price")
        floor_rel = None
        if b.get("category_goal") in RELATIONSHIP_GOALS and st.intel.full_cost and b.get("sustainable_margin_pct"):
            floor_rel = st.intel.full_cost * self.p.rel_full / (1 - b["sustainable_margin_pct"] / 100)
        return {
            "fixed": fixed,
            "leads": leads,
            "committed": committed,
            "p_open": p_open,
            "floor_rel": floor_rel,
            "std": std,
        }

    # ---------- the first e-mail ----------
    def first_move(self, case, sid):
        """Our first e-mail to this supplier is still to be decided (a fixed price: base plays it)."""
        return bool(
            self.is_capacity(case)
            and self.plans.get(sid)
            and "unit_price" in case["negotiable"]
            and not self.threads[sid].our_prices
        )

    def first_sheets(self, case, sid, base_ours, std, supplier):
        """[first, second(, third)] sheets of the first e-mail and the reason in words."""
        plan, b = self.plans[sid], case["buyer"]
        k = self.K
        p_open = plan["p_open"] or base_ours.get("unit_price")
        # its opening is quoted at its own standard lead time: the anchor is k below it there, so the ask's
        # value to it stays within ~12 % of its opening (deeper asks cut patience on D01/P07/P11/P18)
        p_std = p_open * (1 - k.anchor_below_open)
        why = [f"anchor {k.anchor_below_open:.0%} below its opening {p_open:.2f}"]
        if plan["floor_rel"]:
            if p_std < plan["floor_rel"]:
                why.append(f"lifted to the relationship floor {plan['floor_rel']:.2f}")
            p_std = max(p_std, plan["floor_rel"])
        cap = levers.price_cap(case)
        if cap is not None:
            p_std = min(p_std, cap)
        p_std = min(p_std, p_open * 0.995)
        main = complete_offer(case, {**base_ours, **plan["fixed"]})
        sheets = []
        if plan["leads"]:
            ours_lt, its_lt = plan["leads"]
            gap = max(its_lt - ours_lt, 0)
            # our need at the same value to it: its prior premium per day faster than its standard on top
            premium = k.lead_premium * gap * p_open
            p_need = p_std + premium
            # value parity with the standard-lead sheet; with a deep anchor also never above today's price
            # for our own lead time (P09: 16.90 > 16.02), with a moderate (H2) anchor value parity wins
            if k.anchor_below_open >= 0.08:
                p_need = min(p_need, max(p_std, b.get("current_unit_price") or p_need), p_open * 0.995)
            if cap is not None:
                p_need = min(p_need, cap)
            need_sheet = complete_offer(case, {**main, "lead_time_days": ours_lt, "unit_price": round(p_need, 2)})
            need_sheet["lead_time_days"] = ours_lt
            if k.std_lead_sheet and gap > 0:
                std_sheet = {**need_sheet, "lead_time_days": its_lt, "unit_price": round(p_std, 2)}
                # which one is cheaper for us once it has priced both: its premium x units vs our late cost
                late = b.get("late_cost_per_day", 0) * (
                    max(0, its_lt - b["need_lead_time_days"]) - max(0, ours_lt - b["need_lead_time_days"])
                )
                charge = premium * plan["committed"]
                if charge > late:
                    sheets = [std_sheet, need_sheet]
                    why.append(
                        f"its standard {its_lt} d first: its premium ~{premium:.2f}/u x {plan['committed']:,.0f} "
                        f"= {charge:,.0f} > our late cost {late:,.0f}"
                    )
                else:
                    sheets = [need_sheet, std_sheet]
                    why.append(f"our need {ours_lt} d first: our late cost {late:,.0f} >= its premium {charge:,.0f}")
            elif gap > 0:
                sheets = [need_sheet]
            else:  # its standard is already as fast as we need: ask our need (longer suits it) at the anchor
                sheets = [{**need_sheet, "unit_price": round(p_std, 2)}]
        else:
            sheets = [complete_offer(case, {**main, "unit_price": round(p_std, 2)})]
        sheets = [s for s in sheets if must_haves_ok(case, s, std)] or [
            complete_offer(case, {**main, "unit_price": round(p_std, 2)})
        ]
        # a faster-payment trade (cash-short supplier, payment negotiable): base's trade sheets
        if len(sheets) < 3:
            for t in super().sheets(case, sid, sheets[0], std, supplier)[1:]:
                if len(sheets) >= 3:
                    break
                if t.get("payment_days") != sheets[0].get("payment_days") and t not in sheets:
                    sheets.append(t)
        cov = ", ".join(f"{f} {v}" for f, v in plan["fixed"].items())
        why.insert(0, f"capacity first e-mail: coverage locked ({cov})")
        return sheets, "; ".join(why)

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        if (
            self.is_capacity(case)
            and self.plans.get(sid)
            and self.K.mode == "converge"
            and "unit_price" in case["negotiable"]
            and self.threads[sid].our_prices
        ):
            return self.converge(case, threads, sid, theirs, std, left)
        ours = super().next_terms(case, threads, sid, theirs, std, supplier, left)
        if not self.is_capacity(case) or not self.plans.get(sid) or ours is None:
            return ours
        st = self.threads[sid]
        if self.first_move(case, sid):
            sheets, why = self.first_sheets(case, sid, ours, std, supplier)
            st.k_first = sheets
            st.why = why
            first = dict(sheets[0])
            opening_c = total_cost(case, st.opening, std, supplier) if st.opening.get("unit_price") else None
            st.anchor_c = (total_cost(case, first, std, supplier), opening_c)
            return first
        # later rounds: base v14, coverage locked (a lower volume or a short contract costs fallback x 1.25)
        for f, v in self.plans[sid]["fixed"].items():
            if ours.get(f) != v and must_haves_ok(case, {**ours, f: v}, std):
                ours[f] = v
        return ours

    def converge(self, case, threads, sid, theirs, std, left):
        """H2, rounds 2+: its own non-price terms (the sheet cheapest for us), coverage locked, our price a little
        closer each round and always below its standing price; nothing more to gain -> ready (accept)."""
        st, k = self.threads[sid], self.K
        p_s = theirs.get("unit_price")
        if p_s is None:
            st.why = "converge: its sheet has no price"
            return None
        terms = {f: theirs[f] for f in case["negotiable"] if f in theirs and f != "unit_price"}
        terms.update(self.plans[sid]["fixed"])  # coverage: chosen to keep the must-haves
        last = self.last_ask_at(case, sid, terms)
        n = len(st.our_prices)  # our e-mails so far (>= 1)
        gap = p_s - last
        if gap <= k.stay_below or self.rounds_left(sid, left) <= 1:
            st.why = f"converge: its {p_s:.2f} is within reach of our {last:.2f} (or no rounds left): ready"
            return None
        step = max(k.converge_share * gap * k.converge_decay ** (n - 1), k.min_step * p_s)
        p = min(last + step, p_s - k.stay_below)
        st.k_jump = False
        if k.jump and n == 1 and latest(threads[sid]).get("status") == "open" and self.short_patience(case, sid):
            grid = self.price_grid(threads[sid])
            target = round(round(min(p_s - k.jump_abs, p_s * (1 - k.jump_pct)) / grid) * grid, 2)
            floor = self.plans[sid]["floor_rel"] or 0
            if last < target < p_s - k.stay_below and target >= floor:
                p, st.k_jump = target, True
                st.why = (
                    f"jump: {last:.2f} -> {p:.2f} in one step (its {p_s:.2f} on a {grid:.2f} grid; short patience: "
                    "desk authority / capacity squeeze), ready to sign today"
                )
                st.k_terms = dict(terms)
                return complete_offer(case, {**terms, "unit_price": p}) | {
                    f: v for f, v in terms.items() if f == "lead_time_days"
                }
        if p <= last:
            st.why = "converge: no room left below its price: ready"
            return None
        st.why = f"converge: {last:.2f} -> {p:.2f} (gap {gap:.2f} to its {p_s:.2f}, round {n + 1}), its terms kept"
        st.k_terms = dict(terms)
        return complete_offer(case, {**terms, "unit_price": round(p, 2)}) | {
            f: v for f, v in terms.items() if f == "lead_time_days"
        }

    SHORT_PATIENCE = re.compile(r"desk|authority|committee|approval ladder|allocat|capacity|fully booked", re.I)

    def short_patience(self, case, sid):
        """Its patience is likely short: a desk with limited authority or a capacity squeeze, by its profile or
        its own e-mails (P10: 'desk up to 2 %, pricing committee above'; final offer at reply 2)."""
        st = self.threads[sid]
        prof = st.intel.profile or {}
        text = " ".join(
            [str(prof.get("persona", "")), " ".join(p.get("type", "") for p in prof.get("pressures", []))]
            + list(prof.get("what_it_values", []))
        )
        return bool(self.SHORT_PATIENCE.search(text)) or "capacity" in self.signals(sid, st.events)

    @staticmethod
    def price_grid(events):
        """The step its prices move on (P10 quotes 32.20, 31.70, 31.60: EUR 0.10)."""
        prices = [
            (t.get("terms") or {}).get("unit_price")
            for m in events
            if m.get("from") != "buyer"
            for t in m.get("term_sheets") or []
        ]
        prices = [p for p in prices if p]
        for g in (0.5, 0.1, 0.05):
            if prices and all(abs(p / g - round(p / g)) < 1e-6 for p in prices):
                return g
        return 0.01

    def last_ask_at(self, case, sid, terms):
        """Our last ask for these terms; a sheet at another lead time converted at the premium prior."""
        st = self.threads[sid]
        sent = getattr(st, "k_sent", None) or []
        lt = terms.get("lead_time_days")
        for s in sent:
            if s.get("lead_time_days") == lt:
                return s["unit_price"]
        if sent and lt is not None and sent[0].get("lead_time_days") is not None:
            p_open = self.plans[sid]["p_open"] or sent[0]["unit_price"]
            return sent[0]["unit_price"] + self.K.lead_premium * (sent[0]["lead_time_days"] - lt) * p_open
        return st.our_prices[-1]

    def sheets(self, case, sid, ours, std, supplier):
        st = self.threads[sid]
        first = getattr(st, "k_first", None)
        if self.is_capacity(case) and first and not st.our_prices:
            st.k_first = None
            out = [{k: s[k] for k in case["negotiable"] if k in s} for s in first]
            st.k_sent = out
            return out
        if self.is_capacity(case) and self.plans.get(sid) and self.K.mode == "converge":
            out = [{k: ours[k] for k in case["negotiable"] if k in ours}]
            st.k_sent = out  # one sheet on its own terms: nothing to flip, nothing to re-price
            return out
        out = super().sheets(case, sid, ours, std, supplier)
        if self.is_capacity(case) and self.plans.get(sid):
            fixed = self.plans[sid]["fixed"]
            out = [s for s in out if all(s.get(f) == v for f, v in fixed.items()) or s is out[0]]
        return out

    # ---------- arguments ----------
    def forecast_claim(self, case):
        known = {**(self.pkg.facts if self.pkg else {}), **(case.get("facts") or {})}
        for part in case.get("parts", []):
            key = f"fc:{part.split(':')[-1]}@"
            fcs = sorted((r, f) for r, f in known.items() if r.startswith(key) and isinstance(f, dict))
            if fcs and (fcs[-1][1].get("change_pct") or 0) >= self.K.min_forecast_pct:
                ref, fc = fcs[-1]
                return intel_mod.Claim(
                    f"Our demand forecast for this part grows {fc['change_pct']:+.1f}% ({ref}).",
                    [ref],
                    "forecast",
                    strength=1.5,
                )
        return None

    def appreciation_claim(self, case, sid):
        """Its latest scorecard ppm as appreciation, only if every scorecard of it is green (never with qn:
        the arena merges sc and qn into one mean-ppm check, which came back contradicted on P11)."""
        cards = intel_mod.supplier_facts(case, self.pkg, sid, "sc:")
        if not cards or any(f.get("colour") != "green" for f in cards.values()):
            return None
        ref, last = max(cards.items(), key=lambda x: x[1].get("quarter") or "")
        if last.get("ppm") is None:
            return None
        return intel_mod.Claim(
            f"Your quality has been green throughout, with {last['ppm']:.0f} ppm in the rolling twelve months "
            f"({ref}), and we value you as a reliable partner.",
            [ref],
            "appreciation",
            strength=1.0,
        )

    def pays_on_terms(self, sid):
        """Our invoices to it are paid on average <= 2 days after the due date (words only, no ID)."""
        try:
            rows = self.pkg.query(
                "SELECT AVG(julianday(paid_date) - julianday(due_date)) AS late, COUNT(*) AS n FROM invoices "
                "WHERE supplier_id = ? AND paid_date IS NOT NULL",
                (sid,),
            )
        except Exception:
            return False
        r = rows[0] if rows else {}
        return bool(r.get("n")) and r.get("late") is not None and r["late"] <= 2.0

    def first_claims(self, case, sid):
        """Up to 3 checked arguments for the first e-mail, in the rule's order of kinds."""
        st, plan = self.threads[sid], self.plans[sid]
        pool = list(st.intel.claims)
        if self.K.appreciation and (ap := self.appreciation_claim(case, sid)):
            pool.append(ap)
        fc = self.forecast_claim(case)
        if fc:
            pool.append(fc)
        p_open = plan["p_open"] or 0
        sustainable = plan["floor_rel"]
        out = []
        for kind in self.K.first_claims:
            cands = [c for c in pool if c.kind == kind]
            if kind == "should_cost" and sustainable and p_open <= sustainable * self.K.should_cost_room:
                continue  # thin margin: should-cost would argue below its sustainable price (P09)
            if kind == "history":
                cands = [
                    c
                    for c in cands
                    if c.tag == "po"
                    and _max_price(c.sentence)
                    and _max_price(c.sentence) < 0.98 * p_open
                    # our own ask above the prices we cite would contradict the argument (H2 anchor 30.99 > 29.89)
                    and p_open * (1 - self.K.anchor_below_open) <= _max_price(c.sentence)
                ]
            if cands:
                out.append(max(cands, key=lambda c: c.strength))
        return out

    def pick_claims(self, case, threads, sid):
        # called after base recorded our first price, so "first" = no e-mail of ours in the thread yet
        first = (
            self.is_capacity(case)
            and self.plans.get(sid)
            and "unit_price" in case["negotiable"]
            and not any(m.get("from") == "buyer" for m in threads[sid])
        )
        later = not first and self.is_capacity(case) and self.plans.get(sid) and self.K.mode == "converge"
        if not first and not later:
            return super().pick_claims(case, threads, sid)
        limit = 3 if first else 1  # rounds 2+: an unused non-attacking argument at most, never delivery/quality
        st = self.threads[sid]
        avoid = " ".join(
            f"{a.get('argument', '')} {a.get('why', '')}" for a in st.intel.profile.get("arguments_to_avoid", [])
        ).lower()
        from ..agent import avoided

        out = []
        with self.shared_lock:
            for c in self.first_claims(case, sid):
                if any(i in self.used_ids for i in c.ids) or avoided(c, avoid):
                    continue
                out.append(c)
                self.used_ids.update(c.ids)
                if len(out) >= limit:
                    break
        return out

    # ---------- the e-mail ----------
    def thread_move(self, case, threads, sid):
        first = self.first_move(case, sid) and not any(m.get("from") == "buyer" for m in threads.get(sid, []))
        msg = super().thread_move(case, threads, sid)
        converging = (
            not first
            and self.is_capacity(case)
            and self.plans.get(sid)
            and self.K.mode == "converge"
            and "unit_price" in case["negotiable"]
            and getattr(self.threads[sid], "k_terms", None) is not None
        )
        if not (msg and self.is_capacity(case) and (first or converging)):
            return msg
        if converging and "accept your alternative" in msg["body"]:
            return msg  # base's propose-back of its own sheet: keep its proven wording
        self.threads[sid].k_terms = None
        sheets = [ts["terms"] for ts in msg["term_sheets"]]
        pool = self.threads[sid].intel.claims + [self.forecast_claim(case)]
        if self.K.appreciation:
            pool.append(self.appreciation_claim(case, sid))
        claims = [c for c in pool if c and set(c.ids) <= set(msg["refs"]) and c.kind != "scorecard"]
        claims = [c for i, c in enumerate(claims) if all(c.ids != d.ids for d in claims[:i])]
        claims = sorted(claims, key=lambda c: msg["refs"].index(c.ids[0]))
        if first:
            msg["body"], focus = self.first_body(case, sid, sheets, claims), self.first_focus(case, sid)
        else:
            msg["body"], focus = self.converge_body(case, sid, sheets, claims), self.converge_focus(case, sid)
        if "_write" in msg:
            events = list(threads[sid])
            writer = self.writer
            schedule = first and self.K.ask_schedule

            def write():
                try:
                    text = writer.write(case, self, sid, events, sheets, claims, False, focus=focus)
                except TypeError:  # a writer without `focus`
                    text = writer.write(case, self, sid, events, sheets, claims, False)
                text = re.sub(r"^\s*Subject:[^\n]*\n+", "", text or "")  # the model sometimes adds one
                if schedule and "delivery schedule" not in (text or "").lower():
                    text = (text or "").replace(SIGN, "").rstrip() + "\n" + SCHEDULE + "\n\n" + SIGN
                return text

            msg["_write"] = write
        return msg

    def converge_body(self, case, sid, sheets, claims):
        lines = ["Good day,", "", "Thank you for your revised offer.", self.commitment(case, sid)]
        lines += [c.sentence for c in claims]
        if getattr(self.threads[sid], "k_jump", False):
            lines.append(f"To close this now, we move in one step to {describe(sheets[0])}.")
            lines.append("We are ready to sign today on these terms.")
        else:
            lines.append(f"We move to {describe(sheets[0])}, on your lead time.")
        lines += ["", SIGN]
        return "\n".join(lines)

    def converge_focus(self, case, sid):
        if getattr(self.threads[sid], "k_jump", False):
            return (
                "We make one large step to close now. Thank them for the revised offer, restate our firm commitment "
                f"({self.commitment(case, sid)}), say we accept their lead time and terms, that we move in one step to "
                "the stated price and that we are ready to sign today on these terms. Short, warm, decisive. No "
                "threats, no criticism of their delivery or quality, no mention of other suppliers."
            )
        return (
            "We are converging step by step. Thank them for the revised offer, restate our firm commitment "
            f"({self.commitment(case, sid)}), say we accept their lead time and terms and move our price to the "
            "stated figure as a step towards them. Short, warm and constructive. No threats, no criticism of their "
            "delivery or quality, no urgency, no mention of other suppliers."
        )

    def commitment(self, case, sid):
        fixed = self.plans[sid]["fixed"]
        vol, months = fixed.get("volume_per_year"), fixed.get("contract_months")
        if vol and months:
            return f"We commit firmly to our full need of {vol:,} pieces a year for {months} months."
        if vol:
            return f"We commit firmly to our full need of {vol:,} pieces a year."
        return "We are ready to commit firmly to our full need."

    def first_body(self, case, sid, sheets, claims):
        lines = [
            "Good day,",
            "",
            "Thank you for your offer and for being open about your capacity situation. "
            "We want a reliable, long-term arrangement with you.",
            self.commitment(case, sid),
        ]
        if self.K.pay_on_terms and self.pays_on_terms(sid):
            lines.append(PAY_ON_TERMS)
        lines += [c.sentence for c in claims]
        lines.append(f"We propose {describe(sheets[0])}.")
        for s in sheets[1:]:
            lines.append(f"Alternatively: {describe(s, sheets[0])}.")
        if self.K.ask_schedule:
            lines.append(SCHEDULE)
        lines += ["", SIGN]
        return "\n".join(lines)

    def first_focus(self, case, sid):
        pay = f" Say: {PAY_ON_TERMS}" if self.K.pay_on_terms and self.pays_on_terms(sid) else ""
        return (
            "A capacity-constrained supplier allocates to customers with firm, long-term commitments. Stress our firm "
            f"commitment ({self.commitment(case, sid)}), a reliable partnership and simple, plannable call-offs.{pay} "
            "Offer the packages as stated; no threats, no complaints about the allocation, no urgency. "
            f"End with this request: {SCHEDULE}"
        )


SCHEDULE = "Please send us a delivery schedule for the committed volume (monthly quantities)."
PAY_ON_TERMS = "We pay your invoices on terms, on average within two days of the due date."


def _max_price(sentence):
    prices = [float(x) for x in re.findall(r"EUR (\d+(?:\.\d+)?)", sentence)]
    return max(prices) if prices else None


class AnnikaCapacity9Agent(AnnikaCapacityAgent):
    """annika-k with a 9 % anchor (still under the 12 % that drew an open reply on P10): on the replay bot the
    converging rounds mirror our steps, so a deeper (not deep) start leaves more room (mean 0.689 vs 0.680)."""

    K = KParams(anchor_below_open=0.09)


class AnnikaCapacity9JAgent(AnnikaCapacityAgent):
    """annika-k9 + green-scorecard appreciation and 'we pay on terms' in R1, and one large R2 step to just below
    the record-equivalent ('ready to sign today') for a short-patience supplier (practice #3: patience 2)."""

    K = KParams(
        anchor_below_open=0.09,
        first_claims=("should_cost", "forecast", "appreciation"),
        appreciation=True,
        pay_on_terms=True,
        jump=True,
    )
