"""Ege's agent: RFQ and bundling cases (P05/P06/D02 RFQs, P07/P15 kits). Every other case type plays
exactly like base. Only Ege edits this file.

What changes:
- RFQ: a bidder that answers "agreed" took our ask as it stood - in P05 two bidders agreed at once to
  EUR 35.13 and 36.89 when ~26.30 was reachable. Ask it again, lower (4 %, then 2 %), while another
  bidder holds a valid offer as our backup, so a walk-away cannot cost the case.
- Bundling: say what the bundle is worth to the supplier - the whole kit's volume in one contract, and
  the capacity it fills when its profile or its e-mails show idle capacity or a hunger for volume (P07:
  second shift idle, the kit 4.7x its business with us; our template e-mails never mentioned it).

    uv run python -m csee --agent ege sim --agents base ege --cases case:P05 case:P06 case:P07 case:P15
    uv run python -m csee --agent ege bench --agents base ege     free, sandbox (D02 is an RFQ)
"""

import logging

from arena_kit.cost import complete_offer, must_haves_ok, total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import latest, live_threads, moves_left, standing

from .. import intel as intel_mod
from .. import levers
from ..agent import CseeAgent
from ..writer import TemplateWriter

log = logging.getLogger("csee")

AGREED_PUSHES = (0.04, 0.02)  # how far below an "agreed" price we ask again, push by push
BACKUP_WITHIN = 1.10  # a rival's offer counts as backup if it costs us at most this much more


def is_rfq(case):
    return case.get("type") == "rfq" and len(case.get("suppliers", [])) > 1


def is_bundle(case):
    return case.get("type") == "bundling"


class EgeAgent(CseeAgent):
    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.agreed_pushes = {sid: 0 for sid in self.threads}
        if is_bundle(case):
            for sid, st in self.threads.items():
                st.intel.claims = [self.volume_claim(case, sid, st, threads.get(sid) or [])] + st.intel.claims

    # ---------- bundling ----------
    def volume_claim(self, case, sid, st, events):
        """The bundle's volume, in words (no data IDs: nothing for the arena to check). "capacity" pressure
        can mean fully booked (P09), so only idle capacity ("utilisation") is called free capacity."""
        b = case["buyer"]
        fixed = case.get("fixed_terms", {}).get("contract_months")
        months = fixed or max(levers.options(case, "contract_months") or [0])
        parts = len(case.get("parts", []))
        sentence = (
            f"This agreement brings the whole kit - {parts} parts, about {b['need_per_year']:,} kits a year"
            + (f" for up to {months} months" if months else "")
            + " - to one supplier instead of several"
        )
        pressures = {p.get("type") for p in st.intel.profile.get("pressures", [])}
        if "utilisation" in pressures:
            sentence += ", and it fills capacity you have free"
        elif "volume" in pressures or "volume" in self.signals(sid, events):
            sentence += ", and it brings you the steady volume you are looking for"
        return intel_mod.Claim(sentence + ".", [], "volume", strength=5.0)

    # ---------- RFQ ----------
    def backup_cost(self, case, threads, sid):
        """The cheapest valid standing offer of any other live bidder (None if there is none)."""
        best = None
        for s in live_threads(threads):
            if s == sid:
                continue
            sheet_id, terms = standing(threads[s])
            std = standard_terms(threads[s])
            if not sheet_id or terms.get("unit_price") is None or not must_haves_ok(case, terms, std):
                continue
            c = total_cost(case, terms, std)
            best = c if best is None else min(best, c)
        return best

    def agreed_push(self, case, threads, sid):
        """Ask an RFQ bidder that agreed to our ask for a lower price - only with a backup in hand."""
        st, ev = self.threads[sid], threads[sid]
        n = self.agreed_pushes.get(sid, 0)
        if n >= len(AGREED_PUSHES) or self.rounds_left(sid, moves_left(case, ev)) <= self.p.reserve_moves:
            return None
        sheet_id, terms = standing(ev)
        std = standard_terms(ev)
        if not sheet_id or terms.get("unit_price") is None or not must_haves_ok(case, terms, std):
            return None
        backup = self.backup_cost(case, threads, sid)
        if backup is None or backup > total_cost(case, terms, std) * BACKUP_WITHIN:
            return None
        price = terms["unit_price"] * (1 - AGREED_PUSHES[n])
        floor = self.floor_price(st)
        if floor and not (self.p.floor_guard and floor >= terms["unit_price"] * 0.97):
            price = max(price, floor)
        ask = complete_offer(case, {**terms, "unit_price": round(price, 2)})
        if ask["unit_price"] >= terms["unit_price"]:
            return None
        self.agreed_pushes[sid] = n + 1
        if not st.their_prices or st.their_prices[-1] != terms["unit_price"]:
            st.their_prices.append(terms["unit_price"])  # the bookkeeping base's thread_move would have done
        st.our_prices.append(ask["unit_price"])
        log.info("%s %s: agreed at %s - asking %s", case["case_id"], sid, terms["unit_price"], ask["unit_price"])
        claims = self.pick_claims(case, threads, sid)
        sheets = [ask]
        msg = {
            "subject": f"Re: {case['title']}"[:300],
            "body": TemplateWriter().write(case, self, sid, ev, sheets, claims, False),
            "term_sheets": [{"terms": ask}],
            "refs": [i for c in claims for i in c.ids][:20],
        }
        if not isinstance(self.writer, TemplateWriter):
            events = list(ev)
            msg["_write"] = lambda: self.writer.write(case, self, sid, events, sheets, claims, False)
        return msg

    def thread_move(self, case, threads, sid):
        if self.case_id != case["case_id"]:
            self.prepare(case, threads)
        if is_rfq(case) and latest(threads[sid]).get("status") == "agreed":
            self.threads[sid].events = threads[sid]
            msg = self.agreed_push(case, threads, sid)
            if msg:
                return msg
        return super().thread_move(case, threads, sid)
