"""Annika's agent file. Only Annika edits this file.

    uv run python -m csee --agent annika sim    free, offline
    uv run python -m csee --agent annika bench  free, sandbox

Sun 25 Oct 09:30, from the scoring-gap analysis (docs/notes/scoring-gap-analysis.md): bots agree to OUR sheet
the moment it is worth their ask (P02 reply 1, P05 reply 2, P18 5.30), so a lever sheet that costs us more
than our main sheet hands the supplier its ask and ends the game. P02: 362 + copper clause (lever sheet priced
at the supplier's indifference to its opening ask) = 0.733 in 6 of 6 runs; no clause at 362-366 scores 0.99-1.0.
"""

import math
import os
import sys

from arena_kit.cost import RELATIONSHIP_GOALS, total_cost

from .. import levers

from ..agent import CseeAgent
from .mert_dossier import PlanMesoLeverDossierClaims, PlanMesoRawDossierClaims


class AnnikaAgent(CseeAgent):
    pass


class LeverCapMixin:
    """No alternative sheet in our message may cost us more (true model, relationship charge included) than our
    main sheet. Bots take the sheet that is best for THEM: P02's hedge sheet (362 + copper clause, priced at the
    relationship optimum and gated only against the supplier's ask) was agreed at reply 1 for 0.733, while the
    main sheet (358.48, no clause) would have scored 1.0 at any close up to 366. A dearer sheet is repriced down
    to the main sheet's C when a price above the main price does that, else dropped."""

    def _model(self, case, sid, std):
        for name in ("true_model", "calibrated"):
            f = getattr(self, name, None)
            if f:
                try:
                    m = f(case, sid, std)
                    if m:
                        return m
                except Exception:
                    pass
        return None

    def _cap_sheets(self, case, sid, std, out):
        if not out:
            return out
        sup = self._model(case, sid, std)
        main, notes = out[0], []
        b = case["buyer"]
        rel_opt = None
        clause_option = any(c for c in (case.get("term_options") or {}).get("index_clause") or [])
        clause_pattern = (b.get("category_goal") in RELATIONSHIP_GOALS and sup and clause_option
                          and "index_clause" in case["negotiable"] and "unit_price" in case["negotiable"] and main.get("unit_price"))
        # P01 (no clause option): the planner's low anchor still ends at 133.1 (0.99); lifting it to the relationship
        # optimum (134.5) ended at 134.49 (0.93) on realsim, so the lift is only for the clause pattern below.
        if clause_pattern:
            # stabilise / secure_supply: never ask below the price that minimises OUR true C (price + relationship
            # charge). P02: the planner's 12 % anchor (330.85) costs us 2.35M under the true model; the C-minimal
            # no-clause price is ~362 (2.23M), and every close up to 366 scores 1.0.
            ask = (self.threads[sid].opening or {}).get("unit_price") or main["unit_price"]
            hi = max(main["unit_price"], ask)
            rel_opt = levers.relationship_optimal_price(case, main, std, sup, main["unit_price"] * 0.9, hi, steps=600)
            if rel_opt and rel_opt > main["unit_price"] + 0.005:
                notes.append(f"anchor {main['unit_price']}->{rel_opt:.2f} (relationship optimum)")
                main = {**main, "unit_price": math.ceil(rel_opt * 100) / 100}
        # P02 pattern (stabilise + an index clause the supplier blames): it agrees to ANY clause sheet at once
        # (353.48 -> 0.39, 355.89 -> 0.56, 357 -> 0.63, 362 -> 0.733: the clause's 4 % index risk caps the score at
        # ~0.73) and without one steps ~1 EUR a reply from its ask, goes final at reply 4 (371.89 -> 0.51) or walks
        # when we are still far below. The record (0.875) is ~367.8 with no clause: inside its 2 % desk authority.
        # So: two no-clause asks inside that band (C is flat 362-368 for us: 1.0 -> 0.87), then the clause sheet at
        # its relationship optimum as the fallback it always takes.
        n_sent = sum(1 for m in self.threads[sid].events if m.get("from") == "buyer")
        theirs = [m for m in self.threads[sid].events if m.get("from") != "buyer"]
        status = (theirs[-1].get("status") if theirs else None) or ""
        clause_sheets = [t for t in out[1:] if t.get("index_clause") and not main.get("index_clause")]
        fallback = None
        if clause_pattern and rel_opt:
            step = (1.0, 1.5, 1.5)[min(n_sent, 2)] / 100
            band = math.ceil(rel_opt * (1 + step) * 100) / 100
            if abs(main.get("unit_price", 0) - band) > 0.005:
                notes.append(f"desk band {main.get('unit_price')}->{band} (r{n_sent + 1})")
                main = {**main, "unit_price": band}
            if n_sent < 2 and status != "final_offer":
                if clause_sheets:
                    notes.append("clause sheets held back")
                out = [main] + [t for t in out[1:] if not t.get("index_clause")]
            elif clause_sheets:
                fallback = min(clause_sheets, key=lambda t: total_cost(case, t, std, sup))
        cap = total_cost(case, main, std, sup) + 0.01
        kept = [main]
        for t in out[1:]:
            if fallback is not None and t == fallback:
                kept.append(t)
                notes.append(f"clause fallback {t.get('unit_price')}")
                continue
            if total_cost(case, t, std, sup) <= cap:
                kept.append(t)
                continue
            p, lo = t.get("unit_price"), main.get("unit_price")
            fixed = None
            if p and lo and p > lo:
                for i in range(1, 201):  # highest price above main's at which the sheet beats the main sheet
                    q = p - (p - lo) * i / 200
                    if total_cost(case, {**t, "unit_price": q}, std, sup) <= cap:
                        q = math.floor(q * 100) / 100
                        fixed = {**t, "unit_price": q} if q > lo else None
                        break
            if fixed:
                kept.append(fixed)
                notes.append(f"{p}->{fixed['unit_price']}")
            else:
                notes.append(f"dropped {p} ({ {k: v for k, v in t.items() if k != 'unit_price' and t.get(k) != main.get(k)} })")
        if notes:
            self.threads[sid].why += "; cap: " + ", ".join(notes)
        if os.environ.get("CSEE_CAP_DEBUG"):
            print("CAP-DEBUG r%d" % (n_sent + 1), sid,
                  "in:", [(t.get("unit_price"), bool(t.get("index_clause")), t.get("payment_days"), round(total_cost(case, t, std, sup))) for t in out],
                  "out:", [(t.get("unit_price"), bool(t.get("index_clause")), t.get("payment_days"), round(total_cost(case, t, std, sup))) for t in kept], notes, file=sys.stderr)
        return kept

    def sheets(self, case, sid, ours, std, supplier):
        return self._cap_sheets(case, sid, std, super().sheets(case, sid, ours, std, supplier))

    def price_lever(self, case, sid, std, sheet, theirs, main):
        priced = super().price_lever(case, sid, std, sheet, theirs, main)
        if not priced:
            return None
        sup = self._model(case, sid, std)
        cap = total_cost(case, main, std, sup) + 0.01
        p, note = priced
        if total_cost(case, {**sheet, "unit_price": p}, std, sup) <= cap:
            return priced
        lo = main["unit_price"]
        for i in range(201):
            q = p - (p - lo) * i / 200
            if total_cost(case, {**sheet, "unit_price": q}, std, sup) <= cap:
                q = math.floor(q * 100) / 100
                return (q, f"capped at main C ({note})") if q > lo else None
        return None


class AnnikaLeverCap(LeverCapMixin, PlanMesoLeverDossierClaims):
    """price_increase slot candidate: mert-plan-meso-lever-dc + the lever-sheet cap."""


class AnnikaRawLeverCap(LeverCapMixin, PlanMesoRawDossierClaims):
    """raw_material slot candidate: mert-plan-meso-raw-dc + the lever-sheet cap."""
