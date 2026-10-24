"""Emre's agent: raw-material cases (index-priced material: bar, sheet, ...). Every other case type plays
exactly like base. Only Emre edits this file.

For `type == "raw_material"`, on top of base (same opening offer, concessions, arguments and closing):
- A fixed price leads; the case's widest-deadband index clause is offered as the alternative, priced so it
  costs us trade_gain less than the fixed price. Base deals had ended on a 0 % deadband clause; with this
  alternative both suppliers settled on 5 % (practice P08/P18).
- The e-mail says which sheet carries the clause (the template's wording leaves clauses out).
- **One new checked argument in every e-mail**, not all of them in the first: in every practice replay
  rounds 2+ carried none, and only replies to messages with arguments said "we took it into account".
  1 argument per e-mail (base sends max_claims + 1 in the first and runs dry); the pool gets more recent
  index falls of the same cost drivers over disjoint month pairs (each data ID counts once per case).
- **A small push after the final offer** (base's `final_push`, 0.5 %, once).

Tried and dropped (practice P08/P18, 24 Oct): an opening offer from data (today's or another supplier's
price minus the supplier's usual give) - suppliers answered as before, turned final earlier and higher
(0.549/0.467 -> 0.505/0.401); our order price with another supplier - "irrelevant", "does not concern this
part or our company"; a fixed-price alternative behind a clause - "we cannot offer a fixed price for 36
months"; holding at a target - the simulator's suppliers turned final early.

    uv run python -m csee --agent emre sim --cases case:P08 case:P16 case:P18   free, offline
"""

import dataclasses
import logging

from arena_kit.cost import complete_offer, must_haves_ok, total_cost

from .. import intel as intel_mod
from .. import levers
from ..agent import CseeAgent
from ..writer import SIGN

log = logging.getLogger("csee")

RAW = "raw_material"
FINAL_PUSH = 0.005  # after its final offer, ask once this share below it (sandbox D01 agreed to 0.5 %)
CLAIMS_PER_MESSAGE = 1  # checked arguments per e-mail, the first one included
EXTRA_PER_SERIES = 3  # more index falls per cost driver, over disjoint month pairs
MIN_FALL_PCT = -0.5  # only a clear fall argues for us
WINDOWS = (3, 4, 6, 9, 12)  # months between the two index values (the arena checks <= 12)
RECENT_MONTHS = 6  # the later value lies within this many months of the series' latest: a current argument


def is_raw(case):
    return case.get("type") == RAW


def has_clause(sheet):
    return bool(sheet.get("index_clause"))


def widest_clause(case):
    clauses = [c for c in levers.options(case, "index_clause") if c]
    return max(clauses, key=lambda c: c.get("deadband_pct") or 0) if clauses else None


def index_falls(pkg, case, series, exclude=(), limit=EXTRA_PER_SERIES):
    """Falls of `series` over month pairs ending in its last RECENT_MONTHS, the steepest first, sharing no
    ID with each other or with `exclude`: a fresh checkable argument for every round."""
    ids = {i for i in (pkg.ids(f"idx:{series}@") if pkg else []) if "@" in i}
    ids |= {k for k in (case.get("facts") or {}) if k.startswith(f"idx:{series}@")}
    if len(ids) < 2:
        return []
    last = max(ids).split("@")[1]
    ends = [i for i in sorted(ids) if i.split("@")[1] > intel_mod._month_minus(last, RECENT_MONTHS)]
    found = []
    for b in ends:
        vb = (intel_mod._fact(case, pkg, b) or {}).get("value")
        for k in WINDOWS:
            a = f"idx:{series}@{intel_mod._month_minus(b.split('@')[1], k)}"
            va = (intel_mod._fact(case, pkg, a) or {}).get("value") if a in ids else None
            if va and vb:
                pct = (float(vb) / float(va) - 1) * 100
                if pct <= MIN_FALL_PCT:
                    found.append((pct, a, b))
    used, out = set(exclude), []
    label = intel_mod.series_label(pkg, series)
    for pct, a, b in sorted(found):
        if a in used or b in used:
            continue
        used |= {a, b}
        out.append(
            intel_mod.Claim(
                f"{label} changed {pct:+.1f}% from {a.split('@')[1]} to {b.split('@')[1]} ({a}, {b}).",
                [a, b],
                "index",
                strength=0.5 * (1.0 - pct),  # after base's own arguments
                tag=series,
            )
        )
        if len(out) >= limit:
            break
    return out


class EmreAgent(CseeAgent):
    raw = False

    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.raw = is_raw(case)
        if not self.raw:
            return
        self.p = dataclasses.replace(self.p, final_push=FINAL_PUSH)
        for sid, st in self.threads.items():
            try:
                st.intel.claims = st.intel.claims + self.more_index_claims(case, sid, threads, st)
            except Exception:  # an argument we cannot build must never cost the case
                log.exception("%s %s: extra index claims failed", case["case_id"], sid)

    def more_index_claims(self, case, sid, threads, st):
        """Index falls of the part's cost drivers, the series the supplier blames and the clause's series."""
        series = [r["series_id"] for p in case.get("parts", []) for r in intel_mod._q(
            self.pkg, "SELECT series_id FROM cost_drivers WHERE part_id = ? ORDER BY weight DESC", (p,))]
        first = next((m for m in threads.get(sid, []) if m.get("from") != "buyer"), {})
        series += intel_mod.DRIVER_RE.findall(first.get("body") or "")
        series += [c["series"] for c in levers.options(case, "index_clause") if c and c.get("series")]
        taken = {i for c in st.intel.claims for i in c.ids}
        out = []
        for s in dict.fromkeys(series):  # each series once, in order
            new = index_falls(self.pkg, case, s, taken)
            taken |= {i for c in new for i in c.ids}
            out += new
        log.info("%s %s: %d extra index claims", case["case_id"], sid, len(out))
        return out

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
