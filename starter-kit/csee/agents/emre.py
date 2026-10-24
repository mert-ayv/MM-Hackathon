"""Emre's agent: raw-material cases (index-priced material: bar, sheet, ...). Every other case type plays
exactly like base. Only Emre edits this file.

For `type == "raw_material"`, on top of base (same opening offer, concessions, arguments and closing):
- A fixed price leads; the case's widest-deadband index clause is offered as the alternative, priced so it
  costs us trade_gain less than the fixed price. Base deals had ended on a 0 % deadband clause; with this
  alternative both suppliers settled on 5 % (practice P08/P18).
- The e-mail says which sheet carries the clause (the template's wording leaves clauses out).
- **One checked argument per e-mail**, not all of them in the first (base sends max_claims + 1 in the
  first and runs dry): in every practice replay rounds 2+ carried none.
- **Payment for price:** when the supplier's own sheets show faster payment is worth more to it than money
  costs us (P18: EUR 5.60 at 30 days vs 5.70 at 90 = about 11 % a year, we pay 8 %), offer its shorter
  term at a price between the two rates, so both gain. Untested on real suppliers.
- **A small push after the final offer** (base's `final_push`, 0.5 %, once).
- **Index falls pass the profile's "avoid" filter.** Its warnings are about twelve-month rises ("steel
  prices are flat" while the index rose 12 % a year), but base's filter drops every argument on that
  index by topic, also a true, checked fall over recent months (P08: "it holds and we took it into
  account"). Every index argument we cite is a fall, so it cannot repeat what the warning is about.

Tried and dropped (practice P08/P18, 24 Oct): an opening offer from data (today's or another supplier's
price minus the supplier's usual give) - suppliers answered as before, turned final earlier and higher
(0.549/0.467 -> 0.505/0.401); our order price with another supplier - "irrelevant", "does not concern this
part or our company"; a fixed-price alternative behind a clause - "we cannot offer a fixed price for 36
months"; holding at a target - the simulator's suppliers turned final early; one argument per round with
more windows of the same index (v3: every argument verified and "factored in", price still EUR 5.50; a
second window of an index already cited came back "duplicate").

    uv run python -m csee --agent emre sim --cases case:P08 case:P16 case:P18   free, offline
"""

import dataclasses
import logging

from arena_kit.cost import complete_offer, must_haves_ok, total_cost

from .. import levers
from ..agent import CseeAgent
from ..writer import SIGN

log = logging.getLogger("csee")

RAW = "raw_material"
FINAL_PUSH = 0.005  # after its final offer, ask once this share below it (sandbox D01 agreed to 0.5 %)
CLAIMS_PER_MESSAGE = 1  # checked arguments per e-mail, the first one included
PAY_MARGIN = 1.2  # trade payment only if its rate beats ours by this factor (a clear mutual gain)


def is_raw(case):
    return case.get("type") == RAW


def has_clause(sheet):
    return bool(sheet.get("index_clause"))


def widest_clause(case):
    clauses = [c for c in levers.options(case, "index_clause") if c]
    return max(clauses, key=lambda c: c.get("deadband_pct") or 0) if clauses else None


def revealed_payment(case, events):
    """What faster payment is worth to the supplier, from its own latest sheets that differ only in price and
    payment days: (yearly rate, its shorter payment days) or None. Its cost of money, revealed."""
    for m in reversed(events):
        if m.get("from") == "buyer" or not m.get("term_sheets"):
            continue
        sheets = [s.get("terms") or {} for s in m["term_sheets"]]
        best = None
        for a in sheets:
            for b in sheets:
                da, db = a.get("payment_days"), b.get("payment_days")
                if not (da and db and da < db and a.get("unit_price") and b.get("unit_price")):
                    continue
                same = all(a.get(f) == b.get(f) for f in case["negotiable"] if f not in ("unit_price", "payment_days"))
                if same and b["unit_price"] > a["unit_price"]:
                    rate = (b["unit_price"] / a["unit_price"] - 1) / ((db - da) / 360)
                    if best is None or rate > best[0]:
                        best = (rate, da)
        return best  # its latest sheets only: older ones may be stale
    return None


class EmreAgent(CseeAgent):
    raw = False

    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.raw = is_raw(case)
        if not self.raw:
            return
        self.p = dataclasses.replace(self.p, final_push=FINAL_PUSH)
        self.revealed = {}
        for st in self.threads.values():
            for c in st.intel.claims:
                if c.kind == "index":  # base cites only falls: no topic filter (see the docstring)
                    c.tag = ""

    def pick_claims(self, case, threads, sid):
        if not self.raw:
            return super().pick_claims(case, threads, sid)
        first = not any(m.get("from") == "buyer" for m in threads[sid])
        with self.shared_lock:  # base allows max_claims + 1 in the first e-mail
            keep, self.p.max_claims = self.p.max_claims, CLAIMS_PER_MESSAGE - (1 if first else 0)
            try:
                return super().pick_claims(case, threads, sid)
            finally:
                self.p.max_claims = keep

    # ---------- term sheets: the clause and faster payment as priced alternatives ----------
    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if not self.raw:
            return out
        try:
            extra = [self.payment_sheet(case, sid, out[0], std, supplier)]
            if not has_clause(out[0]):  # if it insisted on a clause, base already asks for the cheapest one
                extra.append(self.clause_sheet(case, out[0], std, supplier))
            for alt in extra:
                if alt and alt not in out:
                    out = [out[0], alt] + out[1:]
        except Exception:  # a sheet we cannot build must never cost the case
            log.exception("%s %s: raw sheets failed", case["case_id"], sid)
        return out[:3]

    def payment_sheet(self, case, sid, main, std, supplier):
        """`main` at the supplier's shorter payment term, at a price between its rate and ours."""
        found = self.revealed.get(sid)
        ours = case["buyer"].get("interest_rate")
        if not found or not ours or found[0] < ours * PAY_MARGIN:
            return None
        rate, days = found
        if days >= (main.get("payment_days") or 0) or days not in levers.options(case, "payment_days"):
            return None
        t = complete_offer(case, {**main, "payment_days": days})
        cut = (rate + ours) / 2 * (main["payment_days"] - days) / 360
        t["unit_price"] = round(main["unit_price"] * (1 - cut), 2)
        if not must_haves_ok(case, t, std) or total_cost(case, t, std, supplier) >= total_cost(case, main, std, supplier):
            return None
        return t

    def clause_sheet(self, case, main, std, supplier):
        """`main` with the widest-deadband clause, at the price that costs us trade_gain less than `main`."""
        clause = widest_clause(case)
        if not clause:
            return None
        t = complete_offer(case, {**main, "index_clause": clause})
        if not must_haves_ok(case, t, std):
            return None
        target = total_cost(case, main, std, supplier) * (1 - self.p.trade_gain)
        price = levers.price_for(case, t, target, std, supplier)
        if price is None or price <= 0:  # no price gets this sheet to the target C
            return None
        t["unit_price"] = price
        return t

    # ---------- the e-mail: say which sheet carries a clause ----------
    def thread_move(self, case, threads, sid):
        if self.raw:
            self.revealed[sid] = revealed_payment(case, threads[sid])
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
