"""The csee buyer agent. Code decides every number; a writer (template, or a model) words the e-mail.

Per supplier thread it plans a concession path from an anchor near the supplier's estimated floor
toward its standing offer, offers 1-3 term sheets (our best terms, plus trades the supplier may value
more than they cost us), and cites data the arena checks as verified. One coordinator decides for the
whole case when to accept which standing sheet, or to walk away.
"""

import logging
import re
import math
from dataclasses import dataclass, field

from arena_kit.cost import RELATIONSHIP_GOALS, closing_terms, complete_offer, must_haves_ok, total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import ENDED, latest, live_threads, moves_left, standing

from . import intel as intel_mod
from . import levers
from .writer import SIGN, TemplateWriter, describe

log = logging.getLogger("csee")

READY_STATUSES = {"agreed", "final_offer"}
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


@dataclass
class ThreadState:
    intel: intel_mod.Intel
    our_prices: list = field(default_factory=list)
    their_prices: list = field(default_factory=list)
    breakdown: dict | None = None
    opening: dict = field(default_factory=dict)  # its first offered terms
    cited_rival: float | None = None
    alt_requested: str | None = (
        None  # an alternative sheet of theirs we proposed back  # the rival price we last cited to this supplier
    )
    asked_breakdown: bool = False
    ready: bool = False  # nothing more to gain by writing: wait for the coordinator


class CseeAgent:
    def __init__(self, package=None, writer=None, params=None):
        self.pkg, self.p = package, params or Params()

        self.writer = writer or TemplateWriter()
        self.case_id, self.threads, self.used_ids = None, {}, set()

    # ---------- preparation ----------
    def prepare(self, case, threads):
        self.case_id, self.threads, self.used_ids = case["case_id"], {}, set()
        for sid in case["suppliers"]:
            _, terms = standing(threads[sid]) if threads.get(sid) else (None, {})
            first = next((m for m in threads.get(sid, []) if m.get("from") != "buyer" and m.get("term_sheets")), None)
            opening = dict(first["term_sheets"][0]["terms"]) if first else dict(terms)
            info = intel_mod.build(case, self.pkg, sid, opening.get("unit_price"))
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
        if self.case_id != case["case_id"]:
            self.prepare(case, threads)
        st, ev = self.threads[sid], threads[sid]
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
            return None
        left = moves_left(case, ev)
        # Only the FIRST sheet of a reply is standing and acceptable (422 "not a standing offer" otherwise).
        # Its alternative is better for us: propose it back word for word; the supplier then agrees to it.
        first_id = (latest(ev).get("term_sheets") or [{}])[0].get("term_sheet_id")
        if sheet_id and first_id and sheet_id != first_id and left >= 1 and st.alt_requested != sheet_id:
            st.alt_requested = sheet_id
            terms = complete_offer(case, theirs)
            return {
                "subject": f"Re: {case['title']}"[:300],
                "body": "Good day,\n\nthank you. We accept your alternative offer as stated: "
                f"{describe(terms)}. Please confirm it as your offer.\n\n{SIGN}",
                "term_sheets": [{"terms": terms}],
                "refs": [],
            }
        if status in READY_STATUSES or left <= self.p.reserve_moves or not sheet_id:
            st.ready = True
            return None
        supplier = self.supplier_estimate(case, sid, std)
        ours = self.next_terms(case, threads, sid, theirs, std, supplier, left)
        if ours is None:
            st.ready = True
            return None
        sheets = self.sheets(case, sid, ours, std, supplier)
        st.our_prices.append(sheets[0]["unit_price"])
        claims = self.pick_claims(case, threads, sid)
        ask_breakdown = not st.asked_breakdown and not st.breakdown
        st.asked_breakdown = st.asked_breakdown or ask_breakdown
        draft = TemplateWriter().write(case, self, sid, ev, sheets, claims, ask_breakdown)
        msg = {
            "subject": f"Re: {case['title']}"[:300],
            "body": draft,
            "term_sheets": [{"terms": s} for s in sheets],
            "refs": [i for c in claims for i in c.ids][:20],
        }
        if not isinstance(self.writer, TemplateWriter):
            # the model writes outside the case lock (runner), so one slow thread never blocks the others
            events = list(ev)
            msg["_write"] = lambda: self.writer.write(case, self, sid, events, sheets, claims, ask_breakdown)
        return msg

    def floor_price(self, st):
        full = (st.breakdown or {}).get("full_cost") or st.intel.full_cost
        return full * (1 + self.p.floor_margin) if full else None

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        st = self.threads[sid]
        b = case["buyer"]
        p_s = theirs.get("unit_price")
        if p_s is None:
            return None
        fixed = self.insisted_fields(case, threads[sid]) if self.p.adopt_insisted else {}
        if self.p.adopt_revealed:
            fixed.update(self.revealed_fields(case, threads[sid], theirs))
        exclude = {}
        if self.p.clause_when_insisted and self.clause_insisted(threads[sid]):
            fixed.pop("index_clause", None)
            exclude = {"index_clause": [None]}  # a clause it is: the cheapest one for us (widest deadband)
        base = levers.best_terms(case, {**theirs, **fixed}, std, supplier, fixed=tuple(fixed), exclude=exclude)
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
            if floor and not (
                self.p.floor_guard
                and b.get("category_goal") not in RELATIONSHIP_GOALS
                and floor >= p_s * 0.97  # an estimate above its own ask is wrong, not a floor
            ):
                p = max(p, floor)
            if b.get("category_goal") in RELATIONSHIP_GOALS and supplier:
                p_rel = levers.relationship_optimal_price(case, base, std, supplier, supplier["full_cost"], p_s)
                if p_rel:
                    p = max(p, p_rel * 0.99)
            p = min(p, p_s * 0.995)
        else:
            p_b = st.our_prices[-1]
            gap = p_s - p_b
            their_step = (st.their_prices[-2] - st.their_prices[-1]) if len(st.their_prices) >= 2 else gap
            late = left <= 3
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
        # the best terms depend on the price (e.g. above the fallback price a short contract looks
        # "cheaper"): choose them at the price we ask, not at the supplier's (Fable review #3)
        base = levers.best_terms(
            case, {**base, **fixed, "unit_price": round(p, 2)}, std, supplier, fixed=tuple(fixed), exclude=exclude
        )
        ours = {**base, "unit_price": round(p, 2)}
        if self.p.rfq_beat_leader and len(case["suppliers"]) > 1:
            leader = self.leader_cost(case, threads, exclude=sid)
            if leader < math.inf:
                # ask for a package that beats the best rival; conceding past the rival is pointless
                cap = levers.price_for(case, ours, leader * (1 - self.p.rfq_margin), std, supplier)
                if cap <= 0:
                    return None
                ours["unit_price"] = round(min(ours["unit_price"], cap), 2)
        # their sheet already as cheap as ours (on all terms): nothing to win by writing
        c_theirs = total_cost(case, theirs, std, supplier)
        c_ours = total_cost(case, ours, std, supplier)
        if c_theirs <= c_ours * (1 + self.p.close_gap):
            return None
        return ours

    def sheets(self, case, sid, ours, std, supplier):
        """Our main sheet, plus up to two trades: a term the supplier values for a lower price."""
        out = [complete_offer(case, ours)]
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
        for change in trades:
            if len(out) >= 3:
                break
            t = complete_offer(case, {**out[0], **change})
            if not must_haves_ok(case, t, std):
                continue
            t["unit_price"] = levers.price_for(case, t, target, std, supplier)
            if t["unit_price"] > 0 and t not in out and t["unit_price"] < out[0]["unit_price"] * 1.2:
                out.append(t)
        return out

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
        avoid = " ".join(a.get("argument", "") for a in st.intel.profile.get("arguments_to_avoid", [])).lower()
        out = []
        for c in claims:
            key = tuple(c.ids) if c.kind != "rival" else (sid, *c.ids)
            if key in self.used_ids or any(i in self.used_ids for i in c.ids if c.kind != "rival"):
                continue
            if c.kind in avoid:
                continue
            out.append(c)
            self.used_ids.add(key)
            self.used_ids.update(i for i in c.ids if c.kind != "rival")
            if len(out) >= self.p.max_claims:
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
        """Accept the cheapest valid standing sheet, walk away, or None to keep negotiating."""
        live = live_threads(threads)
        if not live:
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
                if not sheet_id or terms.get("unit_price") is None or not must_haves_ok(case, terms, std):
                    continue
                c = total_cost(case, terms, std, supplier)
                if c < c_alt and (best is None or c < best[0]):
                    best = (c, sid, sheet_id)
        if best is None:
            return {"supplier_id": live[0], "message": {"action": {"type": "walk_away"}}}
        log.info("%s: accept %s %s at C=%.0f (alt %.0f)", case["case_id"], best[1], best[2], best[0], c_alt)
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
