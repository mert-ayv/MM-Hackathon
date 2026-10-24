"""Emre's agent: raw-material cases (index-priced material: bar, sheet, ...). Every other case type plays
exactly like base. Only Emre edits this file.

For `type == "raw_material"`, on top of base (same opening offer, concessions, arguments and closing):
- A fixed price leads; the case's widest-deadband index clause is offered as the alternative, priced so it
  costs us trade_gain less than the fixed price. Base deals had ended on a 0 % deadband clause; with this
  alternative both suppliers settled on 5 % (practice P08/P18).
- The e-mail says which sheet carries the clause (the template's wording leaves clauses out).

Tried and dropped (practice P08/P18, 24 Oct): an opening offer from data (today's or another supplier's
price minus the supplier's usual give) - suppliers answered as before, turned final earlier and higher
(0.549/0.467 -> 0.505/0.401); our order price with another supplier - "irrelevant", "does not concern this
part or our company"; a fixed-price alternative behind a clause - "we cannot offer a fixed price for 36
months"; holding at a target - the simulator's suppliers turned final early.

    uv run python -m csee --agent emre sim --cases case:P08 case:P16 case:P18   free, offline
"""

import logging

from arena_kit.cost import complete_offer, must_haves_ok, total_cost

from .. import levers
from ..agent import CseeAgent
from ..writer import SIGN

log = logging.getLogger("csee")

RAW = "raw_material"


def is_raw(case):
    return case.get("type") == RAW


def has_clause(sheet):
    return bool(sheet.get("index_clause"))


def widest_clause(case):
    clauses = [c for c in levers.options(case, "index_clause") if c]
    return max(clauses, key=lambda c: c.get("deadband_pct") or 0) if clauses else None


class EmreAgent(CseeAgent):
    raw = False

    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.raw = is_raw(case)

    # ---------- term sheets: the clause as a priced alternative ----------
    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if not self.raw or has_clause(out[0]):
            return out  # it insisted on a clause: base already asks for the cheapest one
        try:
            alt = self.clause_sheet(case, out[0], std, supplier)
            if alt and alt not in out:
                out = [out[0], alt] + out[1:]
        except Exception:  # a sheet we cannot build must never cost the case
            log.exception("%s %s: raw sheets failed", case["case_id"], sid)
        return out[:3]

    def clause_sheet(self, case, main, std, supplier):
        """`main` with the widest-deadband clause, at the price that costs us trade_gain less than `main`."""
        clause = widest_clause(case)
        if not clause:
            return None
        t = complete_offer(case, {**main, "index_clause": clause})
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
