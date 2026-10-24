"""Emre's agent: raw-material cases (index-priced material: bar, sheet, ...). Every other case type plays
exactly like base. Only Emre edits this file.

Every rule comes from the case file and from data any supplier has (`emre_data.py`), never from supplier
names or practice cases; without that data it plays like base. For `type == "raw_material"`:
- **Opening offer from data**, not only from the supplier's ask: reference = today's price, or the same
  part's lower price from another supplier (our orders); target = reference minus how far this supplier
  usually settles below its ask (negotiation history). We open ANCHOR_ROOM below the target (practice
  deals landed ~3 % above our opening), then concede like base: holding firm at the target made the local
  simulator's suppliers turn final early (raw cases x 8 seeds: 0.186 with the hold, 0.202 without).
- **Clause form:** a clause in our current contract is the status quo, so we lead with the widest-deadband
  clause and offer a fixed price as the alternative (worth the same to us). Otherwise a fixed price leads
  and the clause is the alternative. Either way the supplier sees the cheaper-for-us deadband.
- **Arguments:** our lower order price for the same part from another supplier (PO IDs, checked by the
  arena); with a clause in the current contract, that market moves are already passed through.

    uv run python -m csee --agent emre sim --cases case:P08 case:P16 case:P18   free, offline
"""

import logging

from arena_kit.cost import complete_offer, must_haves_ok, total_cost

from .. import intel as intel_mod
from .. import levers
from ..agent import CseeAgent
from ..writer import SIGN
from . import emre_data

log = logging.getLogger("csee")

RAW = "raw_material"
ANCHOR_ROOM = 0.03  # open this far below the target: deals land about this much above our opening
MIN_ANCHOR_SHARE = 0.85  # never open below this share of the reference price


def is_raw(case):
    return case.get("type") == RAW


def has_clause(sheet):
    return bool(sheet.get("index_clause"))


def widest_clause(case):
    clauses = [c for c in levers.options(case, "index_clause") if c]
    return max(clauses, key=lambda c: c.get("deadband_pct") or 0) if clauses else None


class EmreAgent(CseeAgent):
    raw = False
    plans = {}

    # ---------- preparation: one plan per supplier, from data ----------
    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.raw, self.plans = is_raw(case), {}
        if not self.raw:
            return
        for sid, st in self.threads.items():
            try:
                plan = self.plans[sid] = self.raw_plan(case, sid, st)
                if plan:
                    st.intel.claims = self.raw_claims(st, plan) + st.intel.claims
                log.info("%s %s: raw plan %s", case["case_id"], sid, plan)
            except Exception:  # data we cannot read must never cost the case: play like base
                log.exception("%s %s: raw plan failed", case["case_id"], sid)
                self.plans[sid] = None

    def raw_plan(self, case, sid, st):
        current = case["buyer"].get("current_unit_price")
        give = emre_data.typical_give(self.pkg, sid)
        if not current or give is None:
            return None
        bench = emre_data.benchmark(self.pkg, case["parts"][0], sid) if case.get("parts") else None
        ref = min(current, bench["price"]) if bench else current
        target = ref * (1 - give / 100)
        return {
            "clause": emre_data.current_clause(self.pkg, sid),
            "give": give,
            "bench": bench,
            "ref": round(ref, 2),
            "target": round(target, 2),
            "anchor": round(max(target * (1 - ANCHOR_ROOM), ref * MIN_ANCHOR_SHARE), 2),
        }

    def raw_claims(self, st, plan):
        out = []
        bench, ask = plan["bench"], st.opening.get("unit_price")
        if bench and ask and bench["price"] < ask:
            out.append(
                intel_mod.Claim(
                    f"We currently pay EUR {bench['price']:.2f} per unit for this part from another approved "
                    f"supplier ({', '.join(bench['ids'])}).",
                    bench["ids"],
                    "po",
                    strength=6.0,
                )
            )
        if plan["clause"]:
            out.append(
                intel_mod.Claim(
                    f"Our current agreement already follows {plan['clause']['series']}, so market moves are passed "
                    "through and should not be priced into the base price a second time.",
                    [],
                    "status_quo",
                    strength=5.0,
                )
            )
        return out

    # ---------- price: the opening offer from the data target ----------
    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        ours = super().next_terms(case, threads, sid, theirs, std, supplier, left)
        plan = self.plans.get(sid) if self.raw else None
        if ours is None or not plan:
            return ours
        st = self.threads[sid]
        if not st.our_prices and plan["anchor"] < ours["unit_price"]:  # the opening offer, never above base's
            ours["unit_price"] = plan["anchor"]
            why = f"raw: open at {plan['anchor']:.2f} (target {plan['target']:.2f} = ref {plan['ref']:.2f} - {plan['give']:.1f}%)"
            st.why = f"{st.why}; {why}" if st.why else why
        return ours

    # ---------- term sheets: the clause form ----------
    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if not self.raw or has_clause(out[0]):
            return out  # it insisted on a clause: base already asks for the cheapest one
        try:
            if (self.plans.get(sid) or {}).get("clause"):  # status quo is a clause: lead with it
                main = self.with_clause(case, out[0], std)
                fixed = self.repriced(case, out[0], main, std, supplier) if main else None
                if main and fixed:
                    return ([main, fixed] + [s for s in out[1:] if s != fixed])[:3]
            alt = self.with_clause(case, out[0], std)
            alt = self.repriced(case, alt, out[0], std, supplier) if alt else None
            if alt and alt not in out:
                out = [out[0], alt] + out[1:]
        except Exception:
            log.exception("%s %s: raw sheets failed", case["case_id"], sid)
        return out[:3]

    def with_clause(self, case, sheet, std):
        """The same sheet with the widest-deadband clause, at the same price (None if no clause fits)."""
        clause = widest_clause(case)
        t = complete_offer(case, {**sheet, "index_clause": clause}) if clause else None
        return t if t and must_haves_ok(case, t, std) else None

    def repriced(self, case, sheet, main, std, supplier):
        """`sheet` at the price that costs us trade_gain less than `main`: an alternative worth taking."""
        t = complete_offer(case, sheet)
        if not must_haves_ok(case, t, std):
            return None
        target = total_cost(case, main, std, supplier) * (1 - self.p.trade_gain)
        t["unit_price"] = levers.price_for(case, t, target, std, supplier)
        return t if t["unit_price"] > 0 else None

    # ---------- the e-mail: say which sheet carries a clause ----------
    def thread_move(self, case, threads, sid):
        msg = super().thread_move(case, threads, sid)
        if not self.raw or not msg or SIGN not in (msg.get("body") or ""):
            return msg
        sheets = [s["terms"] for s in msg.get("term_sheets") or []]
        if len({has_clause(s) for s in sheets}) < 2:
            return msg  # all sheets alike: the template's wording is enough
        notes = []
        for i, s in enumerate(sheets):
            which = "Our proposal" if i == 0 else "The alternative"
            c = s.get("index_clause")
            notes.append(
                f"{which} at EUR {s['unit_price']:.2f} includes an index clause on {c['series']} "
                f"({c['material_share']:.0%} material share, {c['deadband_pct']}% deadband)."
                if c
                else f"{which} at EUR {s['unit_price']:.2f} is a fixed price without index clause."
            )
        msg["body"] = msg["body"].replace(SIGN, "\n".join(notes) + "\n\n" + SIGN)
        return msg
