"""Emre's agent: raw-material cases (index-priced metal, e.g. P08/P18 1.4404 bar, P16 steel sheet).
Every other case type plays exactly like base. Only Emre edits this file.

What changes for `type == "raw_material"`:
- A fixed price is the main ask. With the case's index path rising, any index clause costs us
  (P08: deadband 0 = +17 cents/kg, deadband 5 = +5 cents/kg), so a clause is only offered as an
  alternative sheet, at its widest deadband and a price that leaves us cheaper than the fixed one.
- Raw-material arguments go first: the index's fall since its recent peak (two `idx` IDs, checked
  by the arena) and, if the supplier wrote that its material is bought at fixed prices, that letter.
- Rule tweaks for these suppliers (bets to measure): stop fighting terms it held twice, hold our
  price while it asks its pricing committee, up to 3 arguments per message.

    uv run python -m csee --agent emre sim --cases case:P08 case:P16 case:P18   free, offline
    uv run python -m csee --agent emre bench                                     free, sandbox
"""

import dataclasses
import logging
import re

from arena_kit.cost import complete_offer, must_haves_ok, total_cost

from .. import intel as intel_mod
from .. import levers
from ..agent import CseeAgent
from ..writer import SIGN

log = logging.getLogger("csee")

RAW = "raw_material"
MIN_DROP_PCT = 1.0  # an index fall smaller than this is not worth an argument
HEDGED = re.compile(r"covered at fixed prices until ([A-Z][a-z]+ \d{4})")


def is_raw(case):
    return case.get("type") == RAW


def clause_series(case):
    """The index series the case's clause options follow (one per case in practice)."""
    for c in levers.options(case, "index_clause"):
        if c and c.get("series"):
            return c["series"]
    return None


def index_peak_claim(pkg, series):
    """The series' fall from its highest month in the last 12 to its latest month, as a checked claim."""
    if not pkg or not series:
        return None
    ids = sorted(i for i in pkg.ids(f"idx:{series}@") if "@" in i)[-12:]
    values = [(i, (pkg.lookup(i) or {}).get("value")) for i in ids]
    values = [(i, float(v)) for i, v in values if v]
    if len(values) < 2:
        return None
    peak_id, peak = max(values[:-1], key=lambda x: x[1])
    last_id, last = values[-1]
    pct = (last / peak - 1) * 100
    if pct > -MIN_DROP_PCT:
        return None
    name = intel_mod.series_name(pkg, series).split(" (")[0]
    month = peak_id.split("@")[1]
    return intel_mod.Claim(
        f"{name} has changed {pct:+.1f}% since its peak in {month} ({peak_id}, {last_id}).",
        [peak_id, last_id],
        "index",
        strength=4.0,
    )


def hedged_claim(pkg, supplier_id):
    """The supplier's own letter that its material is bought at fixed prices: an index clause would pass
    on market moves that do not reach its costs. Prose only (a letter is context, not a checked claim)."""
    if not pkg:
        return None
    num = supplier_id.split(":")[-1]
    for path in sorted(p for p in pkg.root.rglob(f"*-{num}-*.md") if "correspondence" in p.parts):
        m = HEDGED.search(path.read_text(encoding="utf-8"))
        if m:
            return intel_mod.Claim(
                f"You wrote to us that your material is covered at fixed prices until {m.group(1)}, so market "
                "moves do not reach your costs before then and an index clause is not justified.",
                [],
                "hedge",
                strength=5.0,
            )
    return None


class EmreAgent(CseeAgent):
    def prepare(self, case, threads):
        super().prepare(case, threads)
        if not is_raw(case):
            return
        self.p = dataclasses.replace(self.p, adopt_insisted=True, hold_on_internal=True, max_claims=3)
        series = clause_series(case)
        for sid, st in self.threads.items():
            try:
                extra = [c for c in (hedged_claim(self.pkg, sid), index_peak_claim(self.pkg, series)) if c]
            except Exception:  # an argument we cannot build must never cost the case
                log.exception("%s %s: raw-material claims failed", case["case_id"], sid)
                extra = []
            st.intel.claims = extra + st.intel.claims
            log.info("%s %s: raw-material claims %s", case["case_id"], sid, [c.kind for c in extra])

    def thread_move(self, case, threads, sid):
        msg = super().thread_move(case, threads, sid)
        if not is_raw(case) or not msg or SIGN not in (msg.get("body") or ""):
            return msg
        # the template's sheet wording leaves index clauses out: say which alternative carries one
        notes = []
        for i, s in enumerate(msg.get("term_sheets") or []):
            c = s["terms"].get("index_clause")
            if i and c and not msg["term_sheets"][0]["terms"].get("index_clause"):
                notes.append(
                    f"The alternative at EUR {s['terms']['unit_price']:.2f} includes an index clause on "
                    f"{c['series']} ({c['material_share']:.0%} material share, {c['deadband_pct']}% deadband)."
                )
        if notes:
            msg["body"] = msg["body"].replace(SIGN, "\n".join(notes) + "\n\n" + SIGN)
        return msg

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if not is_raw(case) or out[0].get("index_clause") is not None:
            return out  # it insisted on a clause: base already asks for the cheapest one
        clause = self.clause_sheet(case, out[0], std, supplier)
        if clause and clause not in out:
            out = [out[0], clause] + out[1:]
        return out[:3]

    def clause_sheet(self, case, main, std, supplier):
        """The widest-deadband clause at a price that makes it cheaper for us than the fixed-price ask."""
        clauses = [c for c in levers.options(case, "index_clause") if c]
        if not clauses:
            return None
        widest = max(clauses, key=lambda c: c.get("deadband_pct") or 0)
        t = complete_offer(case, {**main, "index_clause": widest})
        if not must_haves_ok(case, t, std):
            return None
        target = total_cost(case, main, std, supplier) * (1 - self.p.trade_gain)
        t["unit_price"] = levers.price_for(case, t, target, std, supplier)
        return t if t["unit_price"] > 0 else None
