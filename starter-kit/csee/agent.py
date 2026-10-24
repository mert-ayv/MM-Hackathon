"""The csee buyer agent. Code decides every number; a writer (template, or a model) words the e-mail.

Per supplier thread it plans a concession path from an anchor near the supplier's estimated floor
toward its standing offer, offers 1-3 term sheets (our best terms, plus trades the supplier may value
more than they cost us), and cites data the arena checks as verified. One coordinator decides for the
whole case when to accept which standing sheet, or to walk away.
"""

import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field

from arena_kit.cost import RELATIONSHIP_GOALS, closing_terms, complete_offer, must_haves_ok, supplier_value, total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import ENDED, latest, moves_left, standing
from arena_kit.play import live_threads as _kit_live_threads

from . import intel as intel_mod
from . import levers, runlog
from .writer import SIGN, TemplateWriter, describe

log = logging.getLogger("csee")

READY_STATUSES = {"agreed", "final_offer"}


def live_threads(threads):
    """The kit's live_threads, safe for a thread without any supplier message yet (it would raise)."""
    return _kit_live_threads({s: ev for s, ev in threads.items() if any(m.get("from") != "buyer" for m in ev)})


AVOID_WORDS = {
    "should_cost": ("should-cost", "should cost", "cost:"),
    "rival": ("quote", "second source", "competitor", "rival"),
    "forecast": ("forecast", "fc:"),
    "notice": ("notice",),
    "news": ("news:",),
}


def avoided(claim, avoid_text):
    """The profile says this argument backfires with this supplier (kind-specific keywords; for indices
    the series itself or its theme, never the word "index" alone - it is in 13 of 46 profiles)."""
    if not avoid_text:
        return False
    if claim.kind == "index":
        tag = claim.tag.lower()
        theme = {"ppi-d": "electric", "cu": "copper", "wb-cu": "copper", "as-": "alloy", "ppi-c24": "steel"}
        words = [tag] + [w for k, w in theme.items() if tag.startswith(k)]
        return any(w and w in avoid_text for w in words)
    if claim.kind == "scorecard":
        words = ("ppm", "complaint", "quality") if claim.tag == "ppm" else ("otd", "on-time", "delivery record")
        return any(w in avoid_text for w in words)
    return any(w in avoid_text for w in AVOID_WORDS.get(claim.kind, ()))


# the person at the desk is asking for approval: 16 of 19 such replies were followed by a further step
INTERNAL = re.compile(
    r"clarify (this )?internally|come back to you on price|check (this )?internally|"
    r"needs? (the )?approval|discuss (it|this) with (our )?management",
    re.I,
)


@dataclass
class Params:
    anchor_below_open: float = 0.12  # first price this far below the cheapest opening, at most
    floor_margin: float = 0.02  # never anchor below the estimated full cost + this
    concede_early: float = 0.25  # share of the remaining gap we give per round, early
    concede_late: float = 0.5  # ... in the last rounds
    close_gap: float = 0.004  # their C within this share of ours: take it
    trade_gain: float = 0.006  # a trade sheet must save us at least this share of C
    max_claims: int = 2  # data arguments per message (the arena checks at most 3)
    cash_rate: float = 0.14  # a cash-short supplier's cost of money
    reserve_moves: int = 1  # keep this many messages in hand
    # v2 switches (off = the v1 baseline behaviour)
    adopt_insisted: bool = False  # a term the supplier held twice against our ask: take its value
    rival_only_lower: bool = False  # cite a rival offer only if it beats this supplier's price
    cash_trade_always: bool = False  # always offer a faster-payment sheet, not only for cash-short profiles
    follow_share: float = 1.1  # our step at most this share of the supplier's last step
    hold_above_floor: float = 0.0  # with a known cost floor: concede only this share while above floor*1.08
    # v3 switches (replay lessons P01/P05/P08/P10)
    all_sheets: bool = True  # weigh every term sheet the supplier sends, not only its first
    clause_when_insisted: bool = True  # supplier insists on an index clause: ask for its cheapest form
    fullcost_discount: float = 0.95  # should-cost runs high (error ~5%): scale it for the relationship term
    # v4 switches (D01 patience lesson, P05 floor bug, RFQ)
    floor_guard: bool = False  # ignore a floor estimate at or above ~97% of its own price (outside relationship goals)
    rfq_beat_leader: bool = False  # RFQ: non-leaders must beat the leader by rfq_margin; never pay above the leader
    rfq_margin: float = 0.02
    # v5 switches (Fable review strategy bets)
    anchor_leverage: float = 0.0  # >0: anchor this far below the opening outside relationship goals, no floor
    rfq_anchor_vs_leader: float = 0.0  # >0: RFQ first ask at most (1 - x) x the cheapest rival's opening price
    adopt_revealed: bool = False  # keep a term at the supplier's value when its own sheets show that is cheaper
    hold_on_internal: bool = False  # "we will come back to you on price": hold our price one round
    # v8 switches (trade every lever; read the supplier's own words)
    generic_trades: bool = False  # trade sheets over every negotiable term, cheapest concession for us first
    push_after_final: int = 0  # rounds we still push after its final_offer (0 = accept the final offer)
    final_push: float = 0.0  # >0: after a final offer, ask only this small step below it (D01 agreed to 0.5 %;
    #                          a far-off push made DEMO-C1 walk away) - and only with the bidder holding the best deal
    # v14 switches (price-increase review: relationship-goal anchors)
    rel_anchor: bool = (
        False  # stabilise/secure_supply: anchor at the relationship-optimal price, not the should-cost floor
    )
    rel_full: float = 0.98  # own-plant should-cost runs ~2 % above the real full cost (P01 130.04 vs 132.64)
    close_room: float = 0.0  # >0: thread is done only when the C gap <= this share of the room (opening C - anchor C)
    trade_no_rel: bool = False  # price trade sheets without the relationship term (price_for bisection breaks with it)
    time_aware: bool = True  # Live Final: pace concessions to the rounds that fit before the wave's cap
    sticky_terms: bool = False  # after our first ask, keep the non-price terms of its cheapest sheet (P11)
    text_signals: bool = False
    # v12 switches (coverage review)
    sticky_max_cost: float = 0.0  # >0: stick to a term only if keeping it costs us <= this share of C
    sticky_fields: tuple = ()  # with sticky_terms: only these fields stick (empty = all non-price fields)
    value_neutral_terms: bool = False  # pick chargeback/ppm/payment at the price that keeps its value equal
    contract_at_horizon: bool = False  # no contract beyond the horizon when an index clause is in play and rising  # infer cash/capacity/volume pressure from the supplier's e-mails, not only profiles


@dataclass
class ThreadState:
    intel: intel_mod.Intel
    our_prices: list = field(default_factory=list)
    their_prices: list = field(default_factory=list)
    breakdown: dict | None = None
    opening: dict = field(default_factory=dict)  # its first offered terms
    cited_rival: float | None = None  # the rival price we last cited to this supplier
    completion_requested: str | None = None  # a sheet of theirs with missing terms we asked to complete
    alt_requested: str | None = None  # an alternative sheet of theirs we proposed back
    events: list = field(default_factory=list)  # the thread so far (for the supplier's own signals)
    anchor_c: tuple | None = None  # (our anchor's C, its opening C): the room of this thread
    pushed: int = 0  # rounds pushed after a final offer
    round_s: list = field(default_factory=list)  # seconds per round (our move + its reply), for the wave cap
    asked_breakdown: bool = False
    ready: bool = False  # nothing more to gain by writing: wait for the coordinator
    why: str = ""  # which branch of next_terms decided the last move (for the run log only)


class CseeAgent:
    """The runner's contract (who calls what, which lock is held) is in `csee/agents/__init__.py`."""

    log = runlog.NULL  # the run log: the runner sets a runlog.CaseLog before prepare()

    def __init__(self, package=None, writer=None, params=None):
        self.pkg, self.p = package, params or Params()

        self.writer = writer or TemplateWriter()
        self.case_id, self.threads, self.used_ids = None, {}, set()
        self.close_reason = ""  # why close() chose what it returned (run log)
        self.cap_at = None  # set by the runner in the Live Final: when the safety close happens (time.time())
        # state shared across supplier threads (used_ids): thread_move runs concurrently per supplier
        self.shared_lock = threading.RLock()

    # ---------- preparation ----------
    def prepare(self, case, threads):
        self.case_id, self.threads, self.used_ids = case["case_id"], {}, set()
        for sid in case["suppliers"]:
            _, terms = standing(threads[sid]) if threads.get(sid) else (None, {})
            first = next((m for m in threads.get(sid, []) if m.get("from") != "buyer" and m.get("term_sheets")), None)
            opening = dict(first["term_sheets"][0]["terms"]) if first else dict(terms)
            body = (first or {}).get("body") or ""
            info = intel_mod.build(case, self.pkg, sid, opening.get("unit_price"), body, opening=first)
            st = self.threads[sid] = ThreadState(info, opening=opening)
            for m in threads.get(sid, []):  # a resumed case: continue from our earlier asks, never re-anchor
                if m.get("from") == "buyer" and m.get("term_sheets"):
                    st.our_prices.append(m["term_sheets"][0].get("terms", m["term_sheets"][0]).get("unit_price"))
                elif m.get("term_sheets"):
                    st.their_prices.append(m["term_sheets"][0]["terms"].get("unit_price"))
                if m.get("from") == "buyer" and "breakdown" in (m.get("body") or "").lower():
                    st.asked_breakdown = True
            log.info(
                "%s %s: full cost %s (%s), %d claims",
                case["case_id"],
                sid,
                info.full_cost,
                info.full_cost_source,
                len(info.claims),
            )

    def signals(self, sid, events=None):
        """Pressures the supplier states itself: its e-mails are formulaic ("we need cash", "fully booked")."""
        text = " ".join((m.get("body") or "") for m in (events or []) if m.get("from") != "buyer").lower()
        out = set()
        if re.search(
            r"cash|liquid|pay (our|the) (guys|staff|wages)|faster payment|payment within|too long .{0,20}payment|"
            r"payment .{0,30}too long",
            text,
        ):
            out.add("cash")
        if re.search(r"fully booked|capacity|utili[sz]ation|allocation|lead time .{0,30}not feasible", text):
            out.add("capacity")
        if re.search(r"new customers|more (parts|business|volume)|fill (our|the) (line|capacity)|second shift", text):
            out.add("volume")
        if re.search(r"index clause|alloy|surcharge|copper|preisgleit", text):
            out.add("index")
        return out

    def cash_short(self, sid):
        st = self.threads[sid]
        pressures = " ".join(p.get("type", "") for p in st.intel.profile.get("pressures", []))
        return "cash" in pressures or "cash" in self.signals(sid, st.events)

    def supplier_estimate(self, case, sid, std):
        st = self.threads[sid]
        full = (st.breakdown or {}).get("full_cost") or (
            st.intel.full_cost * self.p.fullcost_discount if st.intel.full_cost else None
        )
        if not full:
            return None
        pressures = " ".join(p.get("type", "") for p in st.intel.profile.get("pressures", []))
        if self.p.text_signals and "cash" in self.signals(sid, st.events):
            pressures += " cash"
        rate = self.p.cash_rate if "cash" in pressures else 0.08
        # its standard terms, complete: the quote PDF's standard section often omits what it offered,
        # so fill every field from its opening offer and the case (supplier_value needs them all)
        standard = closing_terms(case, st.opening, std)
        return {"full_cost": full, "interest_rate": rate, "standard": standard}

    def value_fn(self, case, sid, std):
        """What a sheet is worth to the supplier per unit (cash), incl. chargebacks at its REAL defect rate:
        max(its opening commitment, its latest scorecard ppm)."""
        st = self.threads[sid]
        ppm = st.opening.get("ppm_commitment") or 0
        cards = intel_mod.supplier_facts(case, self.pkg, sid, "sc:")
        if cards:
            ppm = max(ppm, max(cards.items(), key=lambda x: x[1].get("quarter") or "")[1].get("ppm") or 0)
        est = self.supplier_estimate(case, sid, std) or {
            "full_cost": 1.0,
            "interest_rate": 0.08,
            "standard": closing_terms(case, st.opening, std),
        }
        sup = {**est, "ppm": ppm}

        def value(terms):
            try:
                return supplier_value(case, terms, sup)
            except Exception:
                return 0.0

        return value

    def clause_rising(self, case):
        b = case["buyer"]
        clauses = [c for c in case.get("term_options", {}).get("index_clause") or [] if c]
        return "index_clause" in case["negotiable"] and any(
            (b.get("index_paths") or {}).get(c["series"], 0) > 0 for c in clauses
        )

    def leader_cost(self, case, threads, exclude=None):
        """The lowest C any other live supplier offers right now (inf if none)."""
        best = math.inf
        for s in live_threads(threads):
            if s == exclude:
                continue
            std = standard_terms(threads[s])
            sheet_id, terms = self.their_sheet(case, threads[s], std, self.supplier_estimate(case, s, std))
            if sheet_id and terms.get("unit_price") is not None:
                best = min(best, total_cost(case, terms, std))
        return best

    def their_sheet(self, case, events, std, supplier=None):
        """(term_sheet_id, terms) the supplier offers that is cheapest for us (must-haves kept), or with
        all_sheets off its first sheet. Suppliers often answer with alternatives; the second can be the deal."""
        if not self.p.all_sheets:
            return standing(events)
        sheets = latest(events).get("term_sheets") or []
        best = None
        for sh in sheets:
            terms = sh.get("terms") or {}
            if terms.get("unit_price") is None or not must_haves_ok(case, terms, std):
                continue
            c = total_cost(case, terms, std, supplier)
            if best is None or c < best[0]:
                best = (c, sh["term_sheet_id"], terms)
        return (best[1], best[2]) if best else standing(events)

    # ---------- the cheapest opening, the alternative, the reservation ----------
    def c_of(self, case, threads, sid, supplier=None):
        sheet_id, terms = standing(threads[sid])
        if not sheet_id:
            return math.inf
        return total_cost(case, terms, standard_terms(threads[sid]), supplier)

    def reservation(self, case, threads):
        """The most a deal may cost: never more than the alternative, never more than the cheapest opening."""
        openings = []
        for _sid, ev in threads.items():
            first = next((m for m in ev if m.get("from") != "buyer"), None)
            if first and first.get("term_sheets"):
                openings.append(total_cost(case, first["term_sheets"][0]["terms"], standard_terms(ev)))
        return min([levers.alternative_cost(case)] + openings) if openings else levers.alternative_cost(case)

    # ---------- one thread ----------
    def thread_move(self, case, threads, sid):
        """The next e-mail to this supplier, or None when this thread is ready for the coordinator."""
        t0 = time.monotonic()
        if self.case_id != case["case_id"]:
            self.prepare(case, threads)
        st, ev = self.threads[sid], threads[sid]
        st.events = ev
        last = latest(ev)
        status = last.get("status")
        std = standard_terms(ev)
        sheet_id, theirs = self.their_sheet(case, ev, std, self.supplier_estimate(case, sid, std))
        for att in last.get("attachments") or []:
            if "breakdown" in (att.get("name") or "").lower() and att.get("text"):
                parsed = intel_mod.parse_cost_breakdown(att["text"])
                price = (standing(ev)[1] or {}).get("unit_price")
                if parsed and parsed.get("full_cost") and (not price or parsed["full_cost"] <= 0.98 * price):
                    st.breakdown = parsed  # a "full cost" at or above its own price is a parsing error
                log.info("%s %s: cost breakdown %s", case["case_id"], sid, parsed)
        if theirs.get("unit_price") is not None and (
            not st.their_prices or st.their_prices[-1] != theirs["unit_price"]
        ):
            st.their_prices.append(theirs["unit_price"])
        if status in ENDED:
            st.ready = True
            self.note_decision(ev, sid, "wait", f"thread ended ({status})", t0)
            return None
        left = moves_left(case, ev)
        # Only the FIRST sheet of a reply is standing and acceptable (422 "not a standing offer" otherwise).
        # Its alternative is better for us: propose it back word for word; the supplier then agrees to it.
        first_id = (latest(ev).get("term_sheets") or [{}])[0].get("term_sheet_id")
        closing = status in READY_STATUSES or left <= self.p.reserve_moves + 1
        if (
            sheet_id
            and first_id
            and sheet_id != first_id
            and left >= 1
            and st.alt_requested != sheet_id
            and (closing or self.nothing_to_win(case, threads, sid, theirs, std, left))
        ):
            st.alt_requested = sheet_id
            snapped = complete_offer(case, theirs)
            terms = {f: theirs.get(f, snapped.get(f)) for f in case["negotiable"]}  # its exact values, unsnapped
            self.note_decision(ev, sid, "send", f"propose its alternative {sheet_id} back word for word", t0)
            return {
                "subject": f"Re: {case['title']}"[:300],
                "body": "Good day,\n\nthank you. We accept your alternative offer as stated: "
                f"{describe(terms)}. Please confirm it as your offer.\n\n{SIGN}",
                "term_sheets": [{"terms": terms}],
                "refs": [],
            }
        # Its sheet leaves terms out: at a deal they close on ITS standard terms (sim S03: price-only final offer,
        # standard contract/payment cost us 0.87 -> 0.29). Before taking it, ask once for its price with our terms.
        missing = [f for f in case["negotiable"] if f != "unit_price" and f not in theirs]
        if (
            missing
            and sheet_id
            and theirs.get("unit_price") is not None
            and left >= 1
            and st.completion_requested != sheet_id
            and (closing or self.nothing_to_win(case, threads, sid, theirs, std, left))
        ):
            present = tuple(f for f in case["negotiable"] if f in theirs)
            completed = levers.best_terms(case, {**theirs}, std, None, fixed=present)
            completed["unit_price"] = theirs["unit_price"]
            c_as_is, c_completed = total_cost(case, theirs, std), total_cost(case, completed, std)
            if c_as_is - c_completed > 0.002 * c_as_is and must_haves_ok(case, completed, std):
                st.completion_requested = sheet_id
                self.note_decision(
                    ev, sid, "send", f"its {sheet_id} omits {missing}: ask for its price with our terms", t0
                )
                return {
                    "subject": f"Re: {case['title']}"[:300],
                    "body": "Good day,\n\nthank you. We can accept your price; please confirm it with these terms: "
                    f"{describe(completed)}.\n\n{SIGN}",
                    "term_sheets": [{"terms": completed}],
                    "refs": [],
                }
        if (
            status == "final_offer"
            and self.p.final_push
            and st.pushed < 1
            and left > self.p.reserve_moves
            and sheet_id
            and theirs.get("unit_price")
            and self.is_leader(case, threads, sid)
        ):
            st.pushed += 1
            ask = complete_offer(
                case, {**theirs, "unit_price": round(theirs["unit_price"] * (1 - self.p.final_push), 2)}
            )
            st.our_prices.append(ask["unit_price"])
            self.note_decision(
                ev, sid, "send", f"final offer: one small push ({self.p.final_push:.1%}), leader only", t0
            )
            return {
                "subject": f"Re: {case['title']}"[:300],
                "body": "Good day,\n\nthank you for your offer. We are very close. If you can meet us at "
                f"{describe(ask)}, we can confirm the order today.\n\n{SIGN}",
                "term_sheets": [{"terms": ask}],
                "refs": [],
            }
        if status == "final_offer" and st.pushed < self.p.push_after_final and left > self.p.reserve_moves and sheet_id:
            st.pushed += 1  # replays: 0 walk-aways in ~630 supplier moves; test whether a final offer still moves
            status = "open"
        if status in READY_STATUSES or left <= self.p.reserve_moves or not sheet_id:
            st.ready = True
            why = (
                f"supplier status {status}"
                if status in READY_STATUSES
                else f"{left} moves left (reserve {self.p.reserve_moves})"
                if left <= self.p.reserve_moves
                else "no term sheet offered"
            )
            self.note_decision(ev, sid, "wait", why, t0)
            return None
        supplier = self.supplier_estimate(case, sid, std)
        st.why = ""
        ours = self.next_terms(case, threads, sid, theirs, std, supplier, left)
        if ours is None:
            st.ready = True
            self.note_decision(ev, sid, "wait", st.why or "next_terms: nothing to win by writing", t0)
            return None
        sheets = self.sheets(case, sid, ours, std, supplier)
        st.our_prices.append(ours["unit_price"])  # sheets carry no price when the price is fixed
        claims = self.pick_claims(case, threads, sid)
        ask_breakdown = not st.asked_breakdown and not st.breakdown
        st.asked_breakdown = st.asked_breakdown or ask_breakdown
        if self.log.enabled:
            self.note_plan(case, threads, sid, sheets, claims, std, supplier)
        self.note_decision(ev, sid, "send", st.why or "next_terms", t0, candidate_id=f"{sid}:main")
        draft = TemplateWriter().write(case, self, sid, ev, sheets, claims, ask_breakdown)
        msg = {
            "subject": f"Re: {case['title']}"[:300],
            "body": draft,
            "term_sheets": [{"terms": {k: v for k, v in s.items() if k in case["negotiable"]}} for s in sheets],
            "refs": [i for c in claims for i in c.ids][:20],
        }
        if not isinstance(self.writer, TemplateWriter):
            # the model writes outside the case lock (runner), so one slow thread never blocks the others
            events = list(ev)
            msg["_write"] = lambda: self.writer.write(case, self, sid, events, sheets, claims, ask_breakdown)
        return msg

    def is_leader(self, case, threads, sid):
        """This thread holds our cheapest standing deal (always true with one supplier)."""
        if len(case["suppliers"]) == 1:
            return True
        std = standard_terms(threads[sid])
        sheet_id, terms = standing(threads[sid])
        if not sheet_id or terms.get("unit_price") is None:
            return False
        return total_cost(case, terms, std) <= self.leader_cost(case, threads, exclude=sid)

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
        cap = self.cap_at() if self.p.time_aware and self.cap_at else None
        if not cap:
            return left
        times = self.threads[sid].round_s
        per_round = max(sum(times[-3:]) / len(times[-3:]) if times else 45.0, 15.0)
        fit = int(max(cap - time.time(), 0) // per_round)
        return min(left, fit)

    # ---------- run log (docs/run-log.md): observes, never decides ----------
    def note_decision(self, events, sid, kind, reason, t0=None, candidate_id=None, **extra):
        if not self.log.enabled:
            return
        try:
            self.log.event(
                "decision",
                round=sum(m.get("from") == "buyer" for m in events) + 1,
                supplier_id=sid,
                kind=kind,
                candidate_id=candidate_id,
                reason=reason,
                decided_in_s=round(time.monotonic() - t0, 3) if t0 is not None else None,
                **extra,
            )
        except Exception as e:
            log.warning("run log decision: %s", e)

    def note_plan(self, case, threads, sid, sheets, claims, std, supplier):
        try:
            priced = [runlog.priced(case, s, std, supplier) for s in sheets]
            labels = ["main"] + [
                "trade: " + ", ".join(k for k in s if s.get(k) != sheets[0].get(k) and k != "unit_price")
                for s in sheets[1:]
            ]
            cites = [{"id": i, "text": c.sentence} for c in claims for i in c.ids]
            self.log.event(
                "plan",
                round=sum(m.get("from") == "buyer" for m in threads[sid]) + 1,
                supplier_id=sid,
                target=priced[0],
                walk_away_c=runlog.finite(self.reservation(case, threads)),
                candidates=[
                    {
                        "id": f"{sid}:main",
                        "label": " | ".join(labels),
                        "sheets": priced,
                        "claims": cites,
                        "rationale": self.threads[sid].why,
                    }
                ],
            )
        except Exception as e:
            log.warning("run log plan: %s", e)

    def floor_price(self, st):
        full = (st.breakdown or {}).get("full_cost") or st.intel.full_cost
        return full * (1 + self.p.floor_margin) if full else None

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        st = self.threads[sid]
        b = case["buyer"]
        p_s = theirs.get("unit_price") or closing_terms(case, theirs, std).get("unit_price")
        if p_s is None:
            st.why = "their sheet has no price"
            return None
        fixed = self.insisted_fields(case, threads[sid]) if self.p.adopt_insisted else {}
        if self.p.sticky_terms and st.our_prices:
            # once it has priced a set of terms, flipping them lets it re-price (P11: we flipped quality terms
            # three times and accepted the dearest set it had offered): keep its cheapest-for-us sheet's terms,
            # negotiate the price, trade other terms only in alternative sheets
            sticky = self.p.sticky_fields or tuple(f for f in case["negotiable"] if f != "unit_price")
            stick = {f: theirs[f] for f in sticky if f in case["negotiable"] and f in theirs}
            if self.p.sticky_max_cost and stick:
                # keep only the terms that are cheap for us to concede (D01: its 30 days = 0.7 % of C, stick;
                # P01: its early start date = several %, don't) - the rest we still negotiate
                ours_best = levers.best_terms(case, {**theirs}, std, supplier)
                c0 = total_cost(case, ours_best, std, supplier)
                stick = {
                    f: v
                    for f, v in stick.items()
                    if total_cost(case, {**ours_best, f: v}, std, supplier) - c0 <= self.p.sticky_max_cost * c0
                }
            fixed.update(stick)
        if self.p.adopt_revealed:
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
        if self.p.clause_when_insisted and self.clause_insisted(threads[sid]):
            fixed.pop("index_clause", None)
            exclude = {"index_clause": [None]}  # a clause it is: the cheapest one for us (widest deadband)
        value_of = self.value_fn(case, sid, std) if self.p.value_neutral_terms else None
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
            if floor and not (
                self.p.floor_guard
                and b.get("category_goal") not in RELATIONSHIP_GOALS
                and floor >= p_s * 0.97  # an estimate above its own ask is wrong, not a floor
            ):
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
            late = self.rounds_left(sid, left) <= 3
            share = self.p.concede_late if late else self.p.concede_early
            step = share * gap
            if their_step <= 0:  # they did not move: we barely move
                step = min(step, 0.1 * gap)
            else:
                step = min(step, max(their_step * self.p.follow_share, 0.05 * gap))
            if self.p.hold_above_floor and floor and p_b > floor * 1.08:
                step *= self.p.hold_above_floor  # we know there is room above its cost: hold
            if self.p.hold_on_internal and INTERNAL.search(latest(threads[sid]).get("body") or ""):
                step = 0.0  # it is asking its boss for a further step: give it nothing to answer
            p = p_b + max(step, 0)
            st.why = (
                f"concede {max(step, 0):.2f} of gap {gap:.2f} ({'late' if late else 'early'}, their step "
                f"{their_step:.2f})"
                + (", holding above floor" if self.p.hold_above_floor and floor and p_b > floor * 1.08 else "")
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
        )
        ours = {**base, "unit_price": round(p, 2)}
        if self.p.rfq_beat_leader and len(case["suppliers"]) > 1:
            leader = self.leader_cost(case, threads, exclude=sid)
            if leader < math.inf:
                # ask for a package that beats the best rival; conceding past the rival is pointless
                cap = levers.price_for(case, ours, leader * (1 - self.p.rfq_margin), std, supplier)
                if cap <= 0:
                    st.why = "rfq: cannot beat the leader"
                    return None
                if cap < ours["unit_price"]:
                    st.why += f"; capped at {cap:.2f} to beat the leader"
                ours["unit_price"] = round(min(ours["unit_price"], cap), 2)
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

    def sheets(self, case, sid, ours, std, supplier):
        """Our main sheet, plus up to two trades: a term the supplier values for a lower price."""
        full = supplier
        if self.p.trade_no_rel:
            supplier = None  # with the relationship term C is not monotone in price: price_for returned 0 (P01)
        out = [complete_offer(case, ours)]
        if "unit_price" not in case["negotiable"]:
            return out  # a trade is a term for a lower price: nothing to trade with a fixed price
        c_main = total_cost(case, out[0], std, supplier)
        target = c_main * (1 - self.p.trade_gain)
        profile = self.threads[sid].intel.profile
        values = " ".join(profile.get("what_it_values", [])).lower()
        tradeables = [t.get("lever") for t in profile.get("likely_tradeables", [])]
        trades = []
        if "payment_days" in case["negotiable"] and (
            self.p.cash_trade_always or "cash" in values or "payment" in values or "payment_days" in tradeables
        ):
            faster = [d for d in levers.options(case, "payment_days") if d < out[0]["payment_days"]]
            if faster:
                trades.append(
                    {"payment_days": max(d for d in faster if d <= 30) if any(d <= 30 for d in faster) else min(faster)}
                )
        if "contract_months" in case["negotiable"]:
            longer = [m for m in levers.options(case, "contract_months") if m > out[0]["contract_months"]]
            if longer:
                trades.append({"contract_months": max(longer)})
        if "effective_date" in case["negotiable"]:
            earlier = [
                d for d in levers.options(case, "effective_date") if d and d < (out[0].get("effective_date") or "9")
            ]
            if earlier:
                trades.append({"effective_date": max(earlier)})
        if "volume_per_year" in case["negotiable"] and levers.options(case, "volume_per_year"):
            more = [v for v in levers.options(case, "volume_per_year") if v > out[0]["volume_per_year"]]
            if more:
                trades.append({"volume_per_year": min(more)})
        if self.p.generic_trades:
            trades = self.generic_trade_moves(case, sid, out[0], std, supplier, values, tradeables) + trades
        for change in trades:
            if len(out) >= 3:
                break
            t = complete_offer(case, {**out[0], **change})
            if not must_haves_ok(case, t, std):
                continue
            t["unit_price"] = levers.price_for(case, t, target, std, supplier)
            if self.p.trade_no_rel and full and total_cost(case, t, std, full) > total_cost(case, out[0], std, full):
                continue  # below its cost: dearer for us with the relationship charge (P17: 29.38 vs cost 35.38)
            if t["unit_price"] > 0 and t not in out and t["unit_price"] < out[0]["unit_price"] * 1.2:
                out.append(t)
        return out

    def generic_trade_moves(self, case, sid, main, std, supplier, values, tradeables):
        """Every negotiable term one step toward what the supplier prefers (P10: lead time was worth EUR 1.90
        a unit to it and far less to us; P11: chargeback). Ordered: terms its own words or profile say it
        values, then the cheapest concession for us."""
        sig = self.signals(sid, self.threads[sid].events) if self.p.text_signals else set()
        wants = {
            "payment_days": "cash" in sig or "cash" in values or "payment" in values,
            "lead_time_days": "capacity" in sig or "capacity" in values or "lead" in values,
            "volume_per_year": "volume" in sig or "volume" in values,
            "contract_months": "volume" in sig or "contract" in values or "long" in values,
            "index_clause": "index" in sig or "index" in values,
        }
        base_c = total_cost(case, main, std, supplier)
        moves = []
        for f in case["negotiable"]:
            opts = levers.options(case, f)
            if f == "unit_price" or not opts or f not in main:
                continue
            here = levers._supplier_rank(f, main[f], case)
            better = [v for v in opts if levers._supplier_rank(f, v, case) > here]
            if not better:
                continue
            v = min(better, key=lambda x: levers._supplier_rank(f, x, case))  # one step toward the supplier
            t = complete_offer(case, {**main, f: v})
            if not must_haves_ok(case, t, std):
                continue
            cost_to_us = total_cost(case, t, std, supplier) - base_c
            liked = wants.get(f, False) or f in tradeables
            moves.append((not liked, cost_to_us, {f: v}))
        return [m for _, _, m in sorted(moves, key=lambda x: (x[0], x[1]))]

    def pick_claims(self, case, threads, sid):
        st = self.threads[sid]
        claims = list(st.intel.claims)
        if len(case["suppliers"]) > 1:
            stand = {s: standing(threads[s]) for s in threads}
            rivals = intel_mod.rival_claims(case, stand, sid)
            if self.p.rival_only_lower:
                mine = stand.get(sid, (None, {}))[1].get("unit_price") or 0
                cited = st.cited_rival
                rivals = [
                    c for c in rivals if c.price is not None and c.price < mine and (cited is None or c.price < cited)
                ]
                if rivals:
                    st.cited_rival = rivals[0].price
            claims = rivals + claims
        avoid = " ".join(
            f"{a.get('argument', '')} {a.get('why', '')}" for a in st.intel.profile.get("arguments_to_avoid", [])
        ).lower()
        out = []
        with self.shared_lock:  # check-and-claim: two threads must not cite the same ID
            for c in claims:
                key = tuple(c.ids) if c.kind != "rival" else (sid, *c.ids)
                if key in self.used_ids or any(i in self.used_ids for i in c.ids if c.kind != "rival"):
                    continue
                if avoided(c, avoid):
                    continue
                out.append(c)
                self.used_ids.add(key)
                self.used_ids.update(i for i in c.ids if c.kind != "rival")
                first = not any(m.get("from") == "buyer" for m in threads[sid])
                if len(out) >= (self.p.max_claims + 1 if first else self.p.max_claims):
                    break
        return out

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

    # ---------- the whole case ----------
    def close(self, case, threads, force=False):
        """Accept the cheapest valid standing sheet, walk away, or None to keep negotiating. Read-only (the
        runner also calls it as a probe); `close_reason` says why, for the runner's `decision` event."""
        live = live_threads(threads)
        if not live:
            self.close_reason = "no live thread"
            return {"supplier_id": case["suppliers"][0], "message": {"action": {"type": "walk_away"}}}
        if not force and not all(self.threads.get(s) and self.threads[s].ready for s in live):
            return None
        c_alt = levers.alternative_cost(case)
        best = None
        for sid in live:
            std = standard_terms(threads[sid])
            supplier = self.supplier_estimate(case, sid, std)
            if False:  # only the first sheet is standing: alternatives are won by proposing them back
                offered = []
            else:
                offered = [standing(threads[sid])]
            for sheet_id, terms in offered:
                if not sheet_id or closing_terms(case, terms, std).get("unit_price") is None:
                    continue
                if not must_haves_ok(case, terms, std):
                    continue
                c = total_cost(case, terms, std, supplier)
                if c < c_alt and (best is None or c < best[0]):
                    best = (c, sid, sheet_id)
        if best is None:
            self.close_reason = f"no valid sheet beats the alternative (C_alt {c_alt:.0f})"
            return {"supplier_id": live[0], "message": {"action": {"type": "walk_away"}}}
        log.info("%s: accept %s %s at C=%.0f (alt %.0f)", case["case_id"], best[1], best[2], best[0], c_alt)
        self.close_reason = f"cheapest valid standing sheet C={best[0]:.0f} < C_alt {c_alt:.0f}"
        return {"supplier_id": best[1], "message": {"action": {"type": "accept", "term_sheet_id": best[2]}}}

    # ---------- the kit's sequential interface (arena_kit.play.play) ----------
    def decide(self, case, threads):
        if self.case_id != case["case_id"]:
            self.prepare(case, threads)
        for sid in live_threads(threads):
            if latest(threads[sid]).get("from") != "buyer" and not self.threads[sid].ready:
                msg = self.thread_move(case, threads, sid)
                if msg:
                    write = msg.pop("_write", None)
                    if write:
                        try:
                            msg["body"] = write() or msg["body"]
                        except Exception as e:
                            log.warning("writer failed (%s): template kept", e)
                    return {"supplier_id": sid, "message": msg}
        return self.close(case, threads, force=True)
