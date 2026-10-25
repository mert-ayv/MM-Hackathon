"""Frontier experiments and the validated modest-growth raw evidence route."""

import math
from dataclasses import replace

from arena_kit.cost import must_haves_ok, total_cost
from arena_kit.play import latest

from .. import levers
from ..agent import CseeAgent, standard_terms
from ..intel import Claim, supplier_facts
from ..writer import before_signature
from .mert import MertSkipHedgeAgent, PlanMixin, scoped_writer
from .mert_dossier import (
    DossierClaimsMixin,
    PlanMesoRawDossierClaims,
    PlannerDossierClaims,
    RfqAnchorDossierClaims,
)
from .records import PayMesoMixin


class EgeRawFinalAgent(PlanMesoRawDossierClaims):
    """One 2% closing request after substantial, comparable raw concessions.

    Reuse the ordinary one-push, move-reserve, time and agreement guards. Do not
    change the opening, evidence order or packages before a genuine final offer.
    The threshold is an experimental risk gate, not an inferred supplier floor.
    """

    def final_push_size(self, case, events):
        if case.get("type") != "raw_material" or latest(events).get("status") != "final_offer":
            return 0.0
        replies = [e for e in events if e.get("from") != "buyer" and e.get("term_sheets")]
        if len(replies) < 3:
            return 0.0
        first = replies[1]["term_sheets"][0]["terms"]
        final = replies[-1]["term_sheets"][0]["terms"]
        std = standard_terms(events)
        before, now = total_cost(case, first, std), total_cost(case, final, std)
        if not 0 < now < before < float("inf") or (before - now) / before < .02:
            return 0.0
        return .02


class MidDeadbandMixin:
    """Test a middle positive deadband before the planner prices the package."""

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        ours = super().next_terms(case, threads, sid, theirs, std, supplier, left)
        if not ours or case.get("type") != "raw_material" or "index_clause" not in case["negotiable"]:
            return ours
        clauses = [c for c in levers.options(case, "index_clause") if c]
        series = (ours.get("index_clause") or {}).get("series") or self.status_quo.get(sid)
        choices = [c for c in clauses if c["series"] == series and c.get("deadband_pct", 0) > 0]
        if len({c["deadband_pct"] for c in choices}) < 2:
            return ours
        clause = min(choices, key=lambda c: c["deadband_pct"])
        self.threads[sid].why += "; offer narrower positive index deadband"
        return {**ours, "index_clause": clause}


class EgeRawDeadbandAgent(DossierClaimsMixin, PlanMixin, MidDeadbandMixin, PayMesoMixin, MertSkipHedgeAgent):
    """Narrower indexed main package, ordinary payment menu and no final push."""


class EgeRfqDeepAgent(RfqAnchorDossierClaims):
    """Extend the measured RFQ opening experiment, leaving concessions intact."""

    def prepare(self, case, threads):
        super().prepare(case, threads)
        if case.get("type") == "rfq":
            self.p = replace(self.p, anchor_leverage=.35, rfq_anchor_vs_leader=.22)


class EgeRawIndexMenuAgent(PlanMesoRawDossierClaims):
    """Price index protection alone at equal buyer cost beside the routed main.

    The cash-only supplier model cannot price index insurance. Let its choice
    among equal-cost packages reveal that value; preserve payment and coverage.
    """

    def sheets(self, case, sid, ours, std, supplier):
        original = super().sheets(case, sid, ours, std, supplier)
        if case.get("type") != "raw_material" or not original:
            return original
        main = original[0]
        clause = main.get("index_clause")
        if not clause or not {"index_clause", "unit_price"} <= set(case["negotiable"]):
            return original
        choices = sorted([c for c in levers.options(case, "index_clause") if c
                          and c["series"] == clause["series"]
                          and c["deadband_pct"] < clause["deadband_pct"]],
                         key=lambda c: c["deadband_pct"], reverse=True)
        target = total_cost(case, main, std, supplier)
        menu = [main]
        prior = [s["terms"] for e in self.threads[sid].events if e.get("from") == "buyer"
                 for s in e.get("term_sheets", [])]
        for alternative in choices:
            t = {**main, "index_clause": alternative}
            price = levers.price_for(case, t, target, std, supplier)
            if price is None or price <= 0:
                continue
            t["unit_price"] = math.floor(price * 100 + 1e-7) / 100
            if total_cost(case, t, std, supplier) > target + .001:
                t["unit_price"] = round(t["unit_price"] - .01, 2)
            previous = [s["unit_price"] for s in prior if s.get("unit_price") is not None
                        and all(s.get(f) == t.get(f) for f in case["negotiable"] if f != "unit_price")]
            t["unit_price"] = max([t["unit_price"], *previous])
            if must_haves_ok(case, t, std) and total_cost(case, t, std, supplier) <= target + .001:
                menu.append(t)
            if len(menu) == 3:
                break
        return menu if len(menu) > 1 else original


class EgeRenewalStagedAgent(PlannerDossierClaims):
    """Spread independent renewal arguments across concessions, one per message."""

    def pick_claims(self, case, threads, sid):
        if case.get("type") != "renewal":
            return super().pick_claims(case, threads, sid)
        first = not any(e.get("from") == "buyer" for e in threads[sid])
        with self.shared_lock:
            original = self.p.max_claims
            try:
                self.p.max_claims = 0 if first else 1
                return super().pick_claims(case, threads, sid)
            finally:
                self.p.max_claims = original


class RawForecastMixin:
    """Retain modest positive demand growth as evidence after useful indices.

    The shared generator requires 3% growth. This isolated ablation also admits
    smaller positive current forecasts, without implying a larger commitment.
    """

    def prepare(self, case, threads):
        super().prepare(case, threads)
        if case.get("type") != "raw_material":
            return
        known = {**(self.pkg.facts if self.pkg else {}), **(case.get("facts") or {})}
        for st in self.threads.values():
            if any(c.kind == "forecast" for c in st.intel.claims):
                continue
            for part in case.get("parts", []):
                rows = sorted((ref, fact) for ref, fact in known.items()
                              if ref.startswith(f"fc:{part.split(':')[-1]}@") and isinstance(fact, dict))
                if not rows:
                    continue
                ref, fact = rows[-1]
                growth = fact.get("change_pct")
                if not isinstance(growth, (int, float)) or not 0 < growth < 3:
                    continue
                claim = Claim(f"Our demand forecast for this part grows {growth:+.1f}% ({ref}).",
                              [ref], "forecast", strength=1.2)
                # Keep strong cost/notice/quote evidence ahead of a modest
                # forecast too. Dossier order leaves hedged indices at the end.
                strong = {"index", "should_cost", "notice", "rival"}
                at = next((i for i, c in enumerate(st.intel.claims) if c.kind not in strong),
                          len(st.intel.claims))
                st.intel.claims.insert(at, claim)
                break


class EgeRawForecastAgent(RawForecastMixin, PlanMesoRawDossierClaims):
    """Forecast evidence with the current router's planner and payment menu."""


class EgeRawReciprocalAgent(RawForecastMixin, DossierClaimsMixin, MertSkipHedgeAgent):
    """Forecast evidence with the earlier winning raw reciprocal price policy."""


class EgeRawDualEvidenceAgent(EgeRawReciprocalAgent):
    """Test independent index and demand evidence together in the opening."""

    def pick_claims(self, case, threads, sid):
        first = not any(e.get("from") == "buyer" for e in threads[sid])
        st = self.threads[sid]
        forecasts = [c for c in st.intel.claims if c.kind == "forecast"]
        if case.get("type") != "raw_material" or not first or not forecasts:
            return super().pick_claims(case, threads, sid)
        original = st.intel.claims
        if not original or original[0].kind != "index":
            return super().pick_claims(case, threads, sid)
        with self.shared_lock:
            budget = self.p.max_claims
            try:
                chosen = [original[0], forecasts[0]]
                st.intel.claims = chosen + [c for c in original if c not in chosen]
                self.p.max_claims = 1  # Base adds one on the opening only.
                return CseeAgent.pick_claims(self, case, threads, sid)
            finally:
                st.intel.claims = original
                self.p.max_claims = budget


class EgeRawPaceAgent(EgeRawReciprocalAgent):
    """Test larger early reciprocal steps without changing the opening anchor."""

    def prepare(self, case, threads):
        super().prepare(case, threads)
        if case.get("type") == "raw_material":
            self.p = replace(self.p, concede_early=.45)


class EgeRawScopedAgent(EgeRawReciprocalAgent):
    """Give the writer the enquiry's actual fixed quantity and trade limits."""

    def prepare(self, case, threads):
        super().prepare(case, threads)
        if case.get("type") == "raw_material":
            self.writer = scoped_writer(self.writer)


def owner_calculation_note(case, pkg, sid):
    """Find a documented invitation; do not invent an approval process."""
    if pkg is None:
        return None
    rows = supplier_facts(case, pkg, sid, "doc:")
    for ref in sorted(rows, reverse=True):
        try:
            body = pkg.document(ref).lower()
        except (FileNotFoundError, KeyError, TypeError):
            continue
        if all(s in body for s in ("owner", "offered to walk us through", "calculation")):
            return ref
    return None


class EgeRawOwnerReviewAgent(EgeRawReciprocalAgent):
    """Request the owner's documented cost review on the opening packages."""

    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.owner_notes = ({sid: owner_calculation_note(case, self.pkg, sid) for sid in threads}
                            if case.get("type") == "raw_material" else {})

    def thread_move(self, case, threads, sid):
        msg = super().thread_move(case, threads, sid)
        ref = self.owner_notes.get(sid)
        if not msg or not msg.get("term_sheets") or not ref or any(e.get("from") == "buyer" for e in threads[sid]):
            return msg
        addition = (f"Your owner offered to walk us through the calculation ({ref}). "
                    "Please take up that offer: ask the owner to review these packages and the base-price "
                    "calculation, and confirm the best price they can approve before issuing a final offer. "
                    "Which package can the owner support?")
        msg["refs"] = list(dict.fromkeys([*msg.get("refs", []), ref]))[:20]
        msg["body"] = before_signature(msg["body"], addition)
        write = msg.get("_write")
        if write:
            msg["_write"] = lambda: before_signature(write(), addition)
        return msg
