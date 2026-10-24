"""Record-route mixins (sub-records). Put before the agent class: class X(PayMesoMixin, MertLeverAgent).

PayMesoMixin - payment days as a MESO choice (rival records P01: Clooless 130.15 @ 14 d / Apr, Hack It 1.0 = 14 d;
P18 record = 45 d db3; P08 record = 90 d db3):
  * every message carries the shortest and the longest payment option next to the main sheet, each priced
    at the SAME C for us as the main sheet (true C: relationship term at should-cost x 0.98). At equal C a
    sheet is worth more to the supplier exactly when its money rate differs from ours in that direction, so
    the sheet it counters on reveals its rate (bots counter on our sheet worth most to them).
  * from the 2nd message on, the main sheet adopts the payment days of the sheet it countered on, repriced
    to equal C - the negotiation then runs on the structure that is best for both.
  * never re-offer a structure below the price we offered it at before (P01 mert-lever 74fb6f: 30-day sheet
    134.07 -> 129.66 drew "your price for 30-day terms has decreased significantly" and a hold).
"""
import math

from arena_kit.cost import RELATIONSHIP_GOALS, closing_terms, complete_offer, must_haves_ok, total_cost

from csee import levers
from csee.agent import CseeAgent
from csee.agents.mert import MertAgent, MertLeverAgent, implied_rate

NON_PRICE_KEY = lambda case, t: tuple((f, str(t.get(f))) for f in case["negotiable"] if f != "unit_price")  # noqa: E731


class PayMesoMixin:
    REAL_FULL = 0.98
    MESO_MIN_GAIN = 0.0  # adopt its payment days only if it does not cost us more than this share of C

    # ---------- our C ----------
    def meso_sup(self, case, sid, std):
        st = self.threads[sid]
        if case["buyer"].get("category_goal") in RELATIONSHIP_GOALS and st.intel.full_cost:
            return {"full_cost": st.intel.full_cost * self.REAL_FULL, "interest_rate": implied_rate(st.events),
                    "standard": closing_terms(case, st.opening, std)}
        return None  # no relationship term: C is monotone in price

    def equal_c_price(self, case, sheet, c_target, std, sup, ref_price):
        """Highest 2-decimal price with C(sheet) <= c_target (C may be U-shaped with the relationship term)."""
        hi, lo = ref_price * 1.06, ref_price * 0.92
        n = int((hi - lo) * 100)
        for i in range(n + 1):
            p = math.floor(hi * 100 - i) / 100
            if total_cost(case, {**sheet, "unit_price": p}, std, sup) <= c_target + 1e-6:
                return p
        return None

    def pay_options(self, case):
        return sorted(levers.options(case, "payment_days") or [])

    # ---------- hooks ----------
    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        ours = super().next_terms(case, threads, sid, theirs, std, supplier, left)
        if not ours or "payment_days" not in case["negotiable"] or "unit_price" not in case["negotiable"]:
            return ours
        st = self.threads[sid]
        sent = [m for m in threads[sid] if m.get("from") == "buyer" and m.get("term_sheets")]
        d = (theirs or {}).get("payment_days")
        if not sent or d is None or d == ours.get("payment_days") or d not in self.pay_options(case):
            return ours
        offered = {s.get("terms", {}).get("payment_days") for m in sent for s in m.get("term_sheets") or []}
        if d not in offered:
            return ours  # its own standard days, not a choice among ours: keep ours
        prev_main = (sent[-1].get("term_sheets") or [{}])[0].get("terms", {})
        t = complete_offer(case, {**ours, "payment_days": d})
        if not must_haves_ok(case, t, std):
            return ours
        if prev_main.get("payment_days") == d:
            # already on its structure: super() conceded from our last price on it against its price on it
            st.why += f"; meso: stay on its {d} d"
            return {**ours, "payment_days": d}
        # first switch: our last price for that structure (the equal-C MESO sheet) plus super()'s concession step
        self.monotone(case, sid, [])  # builds the history if needed
        hist = st.meso_hist
        last_on_d = hist.get(NON_PRICE_KEY(case, {**t, "unit_price": None}))
        step = ours["unit_price"] - (st.our_prices[-1] if st.our_prices else ours["unit_price"])
        if last_on_d is None:
            sup = self.meso_sup(case, sid, std)
            last_on_d = self.equal_c_price(case, t, total_cost(case, ours, std, sup), std, sup, ours["unit_price"])
            step = 0.0
            if last_on_d is None:
                return ours
        p = round(last_on_d + max(step, 0.0), 2)
        st.why += f"; meso: adopt its {d} d (our last {last_on_d} + step {step:.2f} -> {p})"
        return {**ours, "payment_days": d, "unit_price": p}

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if not out or "payment_days" not in case["negotiable"] or "unit_price" not in case["negotiable"]:
            return self.monotone(case, sid, out)
        main = out[0]
        sup = self.meso_sup(case, sid, std)
        c_main = total_cost(case, main, std, sup)
        opts = self.pay_options(case)
        meso = []
        for d in (opts[0], opts[-1]):
            if d == main.get("payment_days"):
                continue
            t = complete_offer(case, {**main, "payment_days": d})
            if not must_haves_ok(case, t, std):
                continue
            p = self.equal_c_price(case, t, c_main, std, sup, main["unit_price"])
            if p:
                meso.append({**t, "unit_price": p})
        keys = {NON_PRICE_KEY(case, s) for s in meso}
        rest = [s for s in out[1:] if NON_PRICE_KEY(case, s) not in keys]
        # lever sheets (a lever the supplier named, e.g. P02's copper clause) and clause sheets keep priority
        named = [t for _, t, _ in getattr(self.threads[sid], "lever_notes", []) or []]
        keep = [s for s in rest if s in named or (s.get("index_clause") != main.get("index_clause"))]
        other = [s for s in rest if s not in keep]
        merged = [main] + keep + meso + other
        return self.monotone(case, sid, merged[:3])

    def monotone(self, case, sid, sheets):
        st = self.threads[sid]
        hist = getattr(st, "meso_hist", None)
        if hist is None:  # rebuilt from the thread (a resumed case, an offline replay)
            hist = st.meso_hist = {}
            for m in st.events or []:
                if m.get("from") == "buyer":
                    for x in m.get("term_sheets") or []:
                        t = x.get("terms", x)
                        if t.get("unit_price") is not None:
                            k = NON_PRICE_KEY(case, t)
                            hist[k] = max(hist.get(k, 0.0), t["unit_price"])
        out = []
        for s in sheets:
            k = NON_PRICE_KEY(case, s)
            if s.get("unit_price") is not None and k in hist and s["unit_price"] < hist[k]:
                s = {**s, "unit_price": hist[k]}
            out.append(s)
        for s in out:
            if s.get("unit_price") is not None:
                k = NON_PRICE_KEY(case, s)
                hist[k] = max(hist.get(k, 0.0), s["unit_price"])
        return out


class MesoLever(PayMesoMixin, MertLeverAgent):
    pass


class MesoBase(PayMesoMixin, CseeAgent):
    pass


class MesoMert(PayMesoMixin, MertAgent):
    pass


# ---------------------------------------------------------------------------------------------------------------
# PaymentPledgeMixin - P11 hypothesis (Hack It 45.00 vs everyone's 45.50 at 300 ppm / EUR 0): the supplier repeats
# "Without faster payment, we cannot drop the price any further" while payment is FIXED at 60 days. Our own invoice
# history shows we pay it ~10 days late (last 12 months). A binding on-time-payment commitment is the one
# truthful "faster payment" we can give. Untested: worth one P11 practice session.
import datetime as _dt
import re as _re

from csee import intel as _intel
from csee.writer import SIGN as _SIGN
from csee.writer import before_signature as _before_signature

CASH_ASK = _re.compile(r"faster payment|pay(?:ing)? (?:us )?faster|paid faster|cash flow|cash is|Zahlungsziel", _re.I)


def late_days(pkg, sid, since_days=365, today=None):
    """Mean days our payments to `sid` arrived after their due date (invoices.csv), last `since_days`."""
    rows = _intel._q(pkg, "SELECT invoice_date, due_date, paid_date FROM invoices WHERE supplier_id = ?", (sid,))
    if not rows:
        return None, 0
    dates = [r["invoice_date"] for r in rows if r.get("invoice_date")]
    end = _dt.date.fromisoformat(max(dates)) if dates else _dt.date.today()
    start = end - _dt.timedelta(days=since_days)
    late = []
    for r in rows:
        try:
            if _dt.date.fromisoformat(r["invoice_date"]) < start or not r.get("paid_date"):
                continue
            late.append((_dt.date.fromisoformat(r["paid_date"]) - _dt.date.fromisoformat(r["due_date"])).days)
        except (TypeError, ValueError):
            continue
    return (sum(late) / len(late), len(late)) if late else (None, 0)


class PaymentPledgeMixin:
    PLEDGE_MIN_LATE = 3.0  # only when we really have been paying late (days)

    def pledge(self, case, sid):
        fixed = (case.get("fixed_terms") or {}).get("payment_days")
        if not fixed or "payment_days" in case["negotiable"]:
            return None
        replies = [m for m in self.threads[sid].events if m.get("from") != "buyer"]
        if not replies or not CASH_ASK.search(replies[-1].get("body") or ""):
            return None
        st = self.threads[sid]
        if getattr(st, "pledged", 0) >= 2:
            return None
        days, n = late_days(self.pkg, sid)
        if days is None or days < self.PLEDGE_MIN_LATE:
            return None
        st.pledged = getattr(st, "pledged", 0) + 1
        return (f"On payment: the term stays {fixed} days net, but we commit to paying every invoice under this "
                f"agreement on its due date. Over the last twelve months our payments to you arrived on average "
                f"{days:.0f} days after the due date; from this agreement on you are paid on time, which is cash in "
                f"your hands about {days:.0f} days earlier on every delivery.")

    def thread_move(self, case, threads, sid):
        msg = super().thread_move(case, threads, sid)
        if not msg or not msg.get("term_sheets"):
            return msg
        line = self.pledge(case, sid)
        if not line:
            return msg

        def add(body):
            return _before_signature(body, line)

        msg["body"] = add(msg["body"])
        w = msg.get("_write")
        if w:
            msg["_write"] = lambda: add(w())
        return msg


class PledgeBase(PaymentPledgeMixin, CseeAgent):
    pass


from csee.agents.mert import PlanMixin  # noqa: E402


class PlanMesoLever(PlanMixin, PayMesoMixin, MertLeverAgent):
    """The planner's value-unit pacing on top of the payment MESO: PayMeso picks the payment days the supplier
    chose (P01: 14 d), then the planner prices that sheet at its planned value. P01 MESO run 0.938: the
    supplier took 14 d at once but our last steps were +0.05, so it stopped at 133.9."""


from csee.agents.mert import MertSkipHedgeAgent  # noqa: E402


class PlanMesoRaw(PlanMixin, PayMesoMixin, MertSkipHedgeAgent):
    """Raw material: mert-skiphedge's packages (Emre's clause sheets, hedged index last) + payment choice + the
    planner's value-unit pacing. P18 record = 3 % db / 45 d / 5.20 or 5 % / 14 d / 5.21 (supplier rate 10.5 %)."""


# ---------- soft-anchor study (Sat 24 Oct, 21:00): the bots that go final on a deep gap ----------
# Evidence (runs/20261024-204254-router*-practice): Werdenfels (P18, "KAM <= 2 % per step") moved 6.10 -> 5.60 -> 5.40
# -> 5.30 final at reply 3 in EVERY 22 %-anchor run (5 agents, all exactly 0.552; the record is 0.688 = ~5.10): its gap
# after our reply-2/3 asks was still 8-10 %, above what keeps it open. Ravensteiner (P10, "desk authority 2 %, the
# committee above") answers a 12 %-below ask with a final offer at reply 1 (both routers; 0.57 / 0.671 via its own
# alternative). These agents keep every package of their parents and only move the planner's first ask and gap budget.
from csee.agents.mert import PlanParams, PlannerAgent  # noqa: E402

TIGHT_GAPS = (0.08, 0.05, 0.03, 0.025, 0.02, 0.02)  # max gap after reply 1, 2, 3 ... (share of its ask)


class PlanMesoRawSoft(PlanMesoRaw):
    """P18 arm A: 15 % raw anchor + the tight gap budget (never more than 8 % below its ask after reply 1)."""

    plan = PlanParams(anchor_raw=0.15, gmax=TIGHT_GAPS)


class PlanMesoRawSoft12(PlanMesoRaw):
    """P18 arm B: 12 % raw anchor, the default gap budget (risk: we converge above its final 5.30)."""

    plan = PlanParams(anchor_raw=0.12)


class PlanMesoRawSoft18(PlanMesoRaw):
    """P18 arm C: 18 % raw anchor + the tight gap budget."""

    plan = PlanParams(anchor_raw=0.18, gmax=TIGHT_GAPS)


class PlannerSoftRel(PlannerAgent):
    """P10 arm: relationship-goal anchor 4 % below its opening value (inside the desk's 2-4 % authority), so a
    capacity-full group supplier answers 'open' instead of 'final offer' at reply 1. Terms stay base's."""

    plan = PlanParams(anchor_rel=0.04)


# ---------- real-cost study (P02): the relationship-optimal price under a lower real cost ----------
# P02 (Nordmark, stabilise, sustainable margin 0.5 %): every run ends at the clause sheet we price "relationship-
# optimal" at should-cost x 0.98 (362 @ 90 d, CU clause), and the bot ACCEPTS IT AT REPLY 1 ("My call: accept") in
# all three runs - we never see its counter. The arena's C_best sits 12.6 k EUR (27 % of the room) below that deal,
# and the practice record is 0.854 vs our 0.733, so its real cost is below our estimate. The relationship charge is
# quadratic in the margin gap (g^2/10 up to 5 points), so pricing 1.5 % lower costs little even if we overshoot, while
# the price saving is linear. This agent prices every relationship-goal sheet at should-cost x 0.965 instead.
class PlanMesoLeverReal(PlanMesoLever):
    """mert-plan-meso-lever with the real full cost at should-cost x 0.965 (run with --variant v14r)."""

    REAL_FULL = 0.965


class PinDb0Mixin:
    """Raw-material record route (Hack It P18 0.688 = 5.00 with a 0 % deadband clause, 45 days, 24 months, rebuilt
    from its published EUR saved): the main sheet carries the clause WITHOUT deadband (worth ~2 % of price to these
    suppliers, which add it themselves) and a middle payment term (Werdenfels values cash at 10.5 %). Our agents
    always chose the 5 % deadband at 30 days and stalled at 5.30. Put after PlanMixin, so the planner prices it."""

    PIN_DAYS = 45

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        ours = super().next_terms(case, threads, sid, theirs, std, supplier, left)
        if not ours or case.get("type") != "raw_material":
            return ours
        opts = levers.options(case, "index_clause") or []
        db0 = [c for c in opts if c and not c.get("deadband_pct")]
        pin = {}
        if "index_clause" in case["negotiable"] and db0:
            pin["index_clause"] = db0[0]
        if "payment_days" in case["negotiable"] and self.PIN_DAYS in (levers.options(case, "payment_days") or []):
            pin["payment_days"] = self.PIN_DAYS
        t = complete_offer(case, {**ours, **pin})
        if not pin or not must_haves_ok(case, t, std):
            return ours
        self.threads[sid].why += f"; pinned {sorted(pin)} (record route)"
        return {**ours, **pin}


class PlanDb0Raw(PlanMixin, PinDb0Mixin, PayMesoMixin, MertSkipHedgeAgent):
    pass


# value menu for the remaining types (renewal, capacity, quality-free bases): the payment MESO that took P01 from
# 0.926 to 0.988 - the shortest and longest payment term at equal C next to the main sheet; the supplier's pick
# reveals its money rate and the main sheet adopts it
from csee.agents.mert import PlannerAgent  # noqa: E402


class PlanMesoBase(PlanMixin, PayMesoMixin, CseeAgent):
    pass
