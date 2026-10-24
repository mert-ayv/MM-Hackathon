"""The unified buyer agent: one shared flow for every case type. Code decides every number; a writer
(template, or a model) words the e-mail.

Built from csee's base agent (lever engine, verified claims, parallel threads, one coordinator) plus the
lessons of 49 practice replays (24 Oct):

1. PREP     - dossier per supplier; per-type settings (TYPE_SETTINGS) on top of the v14 defaults.
2. GUARD    - checked first on every reply: never counter a final offer (the push code is gone: 2 of 5
              pushes walked, P02/P18 -> 0.0); a supplier that says it holds and did not move -> close.
3. OPEN     - anchor ~22 % below the opening; a risk-sharing index-clause sheet on the index the supplier
              blames (P02: the only good run offered the copper clause, 368 -> 357), a payment-for-price
              sheet when its own sheets reveal a high cost of money.
4. NEGOTIATE- checked facts only (news dropped; scorecards kept: the simulator says they help on P01);
              keep going while it still concedes; a changed package is repriced, never a second gift.
5. CLOSE    - the cheapest valid standing sheet that beats our alternative.

Files (one owner each): agent.py - prep, the thread loop, the guard, close; opening.py - term sheets;
concede.py - the price path and patience; claims.py - arguments; profile.py/intel.py - what we know;
writer.py - the words.

The runner's contract: `prepare` once, `thread_move` per supplier (concurrently), `close` under the
runner's lock (see csee/agents/__init__.py for the full contract; unchanged here).
"""

import dataclasses
import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field

from arena_kit.cost import closing_terms, complete_offer, must_haves_ok, supplier_value, total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import ENDED, latest, moves_left, standing
from arena_kit.play import live_threads as _kit_live_threads

from . import intel as intel_mod
from . import levers, runlog
from .claims import Claims
from .concede import CONTINUATION_REASON, Concede
from .intel import DRIVER_RE
from .opening import Opening
from .writer import SIGN, TemplateWriter, clause_notes, describe

log = logging.getLogger("unified")

READY_STATUSES = {"agreed", "final_offer"}

# the supplier says it will not move (P02 ege/v9: "we hold our Angebot" twice, we stayed low, it walked)
WALK_SIGNAL = re.compile(
    r"hold (our|the|this) (offer|angebot|price|quote)|absolute limit|"
    r"cannot (go|move|offer|reduce) (any )?(further|lower|more)|last word|withdraw",
    re.I,
)


def live_threads(threads):
    """The kit's live_threads, safe for a thread without any supplier message yet (it would raise)."""
    return _kit_live_threads({s: ev for s, ev in threads.items() if any(m.get("from") != "buyer" for m in ev)})


@dataclass
class Params:
    """The numbers that vary per case type (TYPE_SETTINGS) or are worth tuning; everything else is fixed code."""

    anchor_below_open: float = 0.12  # first price this far below the opening (used when anchor_leverage is 0)
    anchor_leverage: float = 0.22  # >0: anchor this far below the opening outside relationship goals, no floor
    rfq_anchor_vs_leader: float = 0.08  # >0: RFQ first ask at most (1 - x) x the cheapest rival's opening price
    floor_margin: float = 0.02  # never anchor below the estimated full cost + this
    concede_early: float = 0.25  # share of the remaining gap we give per round, early
    concede_late: float = 0.5  # ... in the last rounds
    follow_share: float = 1.1  # our step at most this share of the supplier's last step
    close_gap: float = 0.004  # their C within this share of ours: take it
    close_room: float = 0.1  # >0: thread is done only when the C gap <= this share of the room (opening C - anchor C)
    trade_gain: float = 0.006  # a trade sheet must save us at least this share of C
    reserve_moves: int = 1  # keep this many messages in hand
    cash_rate: float = 0.14  # a cash-short supplier's cost of money
    # the supplier's real cost for the relationship term: the arena's charge back-calculates to should-cost
    # x 0.977-0.990 in all 11 charged practice deals (P01/P02/P03, 24 Oct); 0.95 let us squeeze P02 to 0.39
    fullcost_discount: float = 0.98
    rel_anchor: bool = True  # stabilise/secure_supply: anchor at the relationship-optimal price, not should-cost
    rel_full: float = 0.98  # own-plant should-cost runs ~2 % above the real full cost (P01 130.04 vs 132.64)
    trade_no_rel: bool = True  # price trade sheets without the relationship term (price_for bisection breaks with it)
    sticky_terms: bool = True  # after our first ask, keep the non-price terms of its cheapest sheet (P11)
    sticky_max_cost: float = 0.008  # >0: stick to a term only if keeping it costs us <= this share of C
    value_neutral_terms: bool = True  # pick chargeback/ppm/payment at the price that keeps its value equal
    contract_at_horizon: bool = True  # no contract beyond the horizon when an index clause is in play and rising
    max_claims: int = 2  # data arguments per message (the arena checks at most 3)
    first_extra_claim: bool = True  # the first e-mail may carry max_claims + 1 arguments
    history_claims: bool = False  # also cite order history, quality notifications, earlier quarters, case refs
    # checked facts only; news is dropped. Scorecards stay: the replays (P18) suggested they don't move the
    # price, but the simulator says they do (P01 0.63 -> 0.71 with them) and they carry the quality cases
    claim_kinds: tuple = ("index", "should_cost", "rival", "history", "forecast", "notice", "scorecard")
    # no push after a final offer: removed on purpose (practice: 2 of 5 pushes walked, each case -> 0.0)


# per case type, on top of the defaults above (evidence: practice board, 24 Oct). A type the final brings that
# is not listed plays the defaults.
TYPE_SETTINGS = {
    # P05 v7 0.81 vs base 0.35: low anchor vs the leader, no sticky/relationship machinery
    "rfq": {
        "sticky_terms": False,
        "sticky_max_cost": 0.0,
        "value_neutral_terms": False,
        "contract_at_horizon": False,
        "rel_anchor": False,
        "trade_no_rel": False,
        "close_room": 0.0,
    },
    # P07 base 0.72; the deep anchor drew a final offer at reply 2 (0.68-0.70)
    "bundling": {"anchor_leverage": 0.0, "anchor_below_open": 0.12},
    # P08/P18: order history and earlier quarters as checked arguments (mert/v16 0.71/0.55); one argument per
    # e-mail - base sent them all in the first and rounds 2+ carried none
    "raw_material": {"history_claims": True, "max_claims": 1, "first_extra_claim": False},
}


def params_for(case_type, base=None):
    return dataclasses.replace(base or Params(), **TYPE_SETTINGS.get(case_type, {}))


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
    continuations: int = 0  # times we resent our last package while it still conceded
    revealed_pay: tuple | None = None  # (its yearly cost of money, its shorter payment days) from its own sheets
    blamed: set = field(default_factory=set)  # index series its opening blames ("CU-NOTATION rose 47.7 %")
    status_quo_clause: str | None = None  # our current contract with it follows this index
    round_s: list = field(default_factory=list)  # seconds per round (our move + its reply), for the wave cap
    asked_breakdown: bool = False
    ready: bool = False  # nothing more to gain by writing: wait for the coordinator
    why: str = ""  # which branch of next_terms decided the last move (for the run log only)


class UnifiedAgent(Opening, Concede, Claims):
    """One shared agent for every case type (see the module docstring for the flow)."""

    log = runlog.NULL  # the run log: the runner sets a runlog.CaseLog before prepare()

    def __init__(self, package=None, writer=None, params=None):
        self.pkg, self.p = package, params or Params()
        self.base_params = self.p  # TYPE_SETTINGS apply on top of these, per case

        self.writer = writer or TemplateWriter()
        self.case_id, self.threads, self.used_ids = None, {}, set()
        self.close_reason = ""  # why close() chose what it returned (run log)
        self.cap_at = None  # set by the runner in the Live Final: when the safety close happens (time.time())
        # state shared across supplier threads (used_ids): thread_move runs concurrently per supplier
        self.shared_lock = threading.RLock()

    # ---------- preparation ----------
    def prepare(self, case, threads):
        self.case_id, self.threads, self.used_ids = case["case_id"], {}, set()
        self.p = params_for(case.get("type"), self.base_params)
        for sid in case["suppliers"]:
            _, terms = standing(threads[sid]) if threads.get(sid) else (None, {})
            first = next((m for m in threads.get(sid, []) if m.get("from") != "buyer" and m.get("term_sheets")), None)
            opening = dict(first["term_sheets"][0]["terms"]) if first else dict(terms)
            body = (first or {}).get("body") or ""
            info = intel_mod.build(case, self.pkg, sid, opening.get("unit_price"), body, opening=first)
            st = self.threads[sid] = ThreadState(info, opening=opening)
            st.blamed = set(DRIVER_RE.findall(body))
            st.status_quo_clause = self.current_clause(sid)
            info.claims = [c for c in info.claims if self.keep_claim(case, c)]
            for m in threads.get(sid, []):  # a resumed case: continue from our earlier asks, never re-anchor
                if m.get("from") == "buyer" and m.get("term_sheets"):
                    st.our_prices.append(m["term_sheets"][0].get("terms", m["term_sheets"][0]).get("unit_price"))
                elif m.get("term_sheets"):
                    st.their_prices.append(m["term_sheets"][0]["terms"].get("unit_price"))
                if m.get("from") == "buyer" and "breakdown" in (m.get("body") or "").lower():
                    st.asked_breakdown = True
            asks = [
                m["term_sheets"][0].get("terms", {})
                for m in threads.get(sid, [])
                if m.get("from") == "buyer" and m.get("term_sheets")
            ]
            st.continuations = sum(a == b for a, b in zip(asks, asks[1:], strict=False))  # a resumed case
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
        rate = self.p.cash_rate if "cash" in pressures else 0.08
        # its standard terms, complete: the quote PDF's standard section often omits what it offered,
        # so fill every field from its opening offer and the case (supplier_value needs them all)
        standard = closing_terms(case, st.opening, std)
        return {"full_cost": full, "interest_rate": rate, "standard": standard}

    def real_ppm(self, case, sid, std=None):
        """The defect rate the supplier really has: max(its opening / standard commitment, its latest scorecard
        ppm, its profile's quality.ppm). A chargeback costs it real ppm x chargeback x units (P11: 2,376)."""
        st = self.threads[sid]
        ppm = max(st.opening.get("ppm_commitment") or 0, (std or {}).get("ppm_commitment") or 0)
        cards = intel_mod.supplier_facts(case, self.pkg, sid, "sc:")
        if cards:
            ppm = max(ppm, max(cards.items(), key=lambda x: x[1].get("quarter") or "")[1].get("ppm") or 0)
        quality = st.intel.profile.get("quality") or {}
        return max(ppm, quality.get("ppm") or 0)

    def value_fn(self, case, sid, std):
        """What a sheet is worth to the supplier per unit (cash), incl. chargebacks at its REAL defect rate."""
        st = self.threads[sid]
        ppm = self.real_ppm(case, sid, std)
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

    def their_sheet(self, case, events, std, supplier=None):
        """(term_sheet_id, terms) the supplier offers that is cheapest for us (must-haves kept). Suppliers
        often answer with alternatives; the second can be the deal."""
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
        # GUARD: a final offer is never countered (READY_STATUSES below). A supplier that says it holds and did
        # not move this round walks next if we keep writing low (P02 ege/v9): let the coordinator close now.
        if status == "open" and self.holding(ev):
            st.ready = True
            self.note_decision(ev, sid, "wait", "walk risk: it holds and did not move", t0)
            return None
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
        st.revealed_pay = self.revealed_payment(case, ev)
        ours = self.next_terms(case, threads, sid, theirs, std, supplier, left)
        if ours is None:
            st.ready = True
            self.note_decision(ev, sid, "wait", st.why or "next_terms: nothing to win by writing", t0)
            return None
        sheets = self.sheets(case, sid, ours, std, supplier)
        # the price actually sent (a status-quo clause sheet can lead instead of `ours`)
        st.our_prices.append(sheets[0].get("unit_price", ours["unit_price"]))
        if st.why == CONTINUATION_REASON:
            st.continuations += 1
        claims = self.pick_claims(case, threads, sid)
        ask_breakdown = not st.asked_breakdown and not st.breakdown
        st.asked_breakdown = st.asked_breakdown or ask_breakdown
        if self.log.enabled:
            self.note_plan(case, threads, sid, sheets, claims, std, supplier)
        self.note_decision(ev, sid, "send", st.why or "next_terms", t0, candidate_id=f"{sid}:main")
        draft = clause_notes(TemplateWriter().write(case, self, sid, ev, sheets, claims, ask_breakdown), sheets)
        msg = {
            "subject": f"Re: {case['title']}"[:300],
            "body": draft,
            "term_sheets": [{"terms": {k: v for k, v in s.items() if k in case["negotiable"]}} for s in sheets],
            "refs": [i for c in claims for i in c.ids][:20],
        }
        if not isinstance(self.writer, TemplateWriter):
            # the model writes outside the case lock (runner), so one slow thread never blocks the others
            events = list(ev)
            msg["_write"] = lambda: clause_notes(
                self.writer.write(case, self, sid, events, sheets, claims, ask_breakdown), sheets
            )
        return msg

    @staticmethod
    def holding(events):
        """Its latest reply says it will not move (WALK_SIGNAL) and its price did not move since its last one."""
        replies = [m for m in events if m.get("from") != "buyer" and m.get("term_sheets")]
        if len(replies) < 2 or not WALK_SIGNAL.search(replies[-1].get("body") or ""):
            return False

        def price(m):
            return (m["term_sheets"][0].get("terms") or {}).get("unit_price")

        now, before = price(replies[-1]), price(replies[-2])
        return now is not None and before is not None and now >= before

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
            # only the first sheet is standing: alternatives are won by proposing them back (thread_move)
            sheet_id, terms = standing(threads[sid])
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
