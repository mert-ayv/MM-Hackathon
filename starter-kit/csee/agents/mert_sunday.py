"""Isolated Sunday structure experiments. No final-router changes."""
import math

from arena_kit.cost import complete_offer, must_haves_ok, total_cost
from csee import levers
from .mert import MertRfqAnchorAgent
from .mert_dossier import PlanMesoRawDossierClaims


class MertRfqLeadMenuAgent(MertRfqAnchorAgent):
    """Offer extra delivery time only in exchange for a lower total buyer cost.

    Keep the first two established packages; add one feasible longer-lead cash
    package. Price includes the case's explicit late-delivery penalty.
    """

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if case.get('type') != 'rfq' or 'lead_time_days' not in case['negotiable'] or len(out) >= 3:
            return out
        source = out[-1]
        candidates = []
        for days in levers.options(case, 'lead_time_days'):
            t = complete_offer(case, {**source, 'lead_time_days': days})
            if days > source['lead_time_days'] and must_haves_ok(case, t, std):
                candidates.append(t)
        if not candidates:
            return out
        t = max(candidates, key=lambda t: t['lead_time_days'])
        target = total_cost(case, source, std, supplier) * (1 - self.p.trade_gain)
        price = levers.price_for(case, t, target, std, supplier)
        if price is None or price <= 0:
            return out
        t['unit_price'] = math.floor(price * 100) / 100
        if total_cost(case, t, std, supplier) > target + .01:
            t['unit_price'] = round(t['unit_price'] - .01, 2)
        if total_cost(case, t, std, supplier) <= target + .01:
            out.append(t)
        return out


class MertRawLongAgent(PlanMesoRawDossierClaims):
    """Put the longer commitment on the main clause sheet, not a fixed-price alt.

    The routed policy's longer alternative removes the clause and suppliers
    reject that structure. Keep its clause, payment choices and price planning.
    Only extend when the buyer cost function charges no additional cost.
    """

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        ours = super().next_terms(case, threads, sid, theirs, std, supplier, left)
        return self.longer(case, ours, std, supplier)

    def sheets(self, case, sid, ours, std, supplier):
        # The parent may add the required clause only while constructing sheets.
        # Apply after that step too, so the intended package is actually sent.
        out = super().sheets(case, sid, ours, std, supplier)
        return [self.longer(case, t, std, supplier) for t in out]

    @staticmethod
    def longer(case, ours, std, supplier):
        if not ours or case.get('type') != 'raw_material' or not ours.get('index_clause'):
            return ours
        if 'contract_months' not in case['negotiable']:
            return ours
        baseline = total_cost(case, ours, std, supplier)
        for months in sorted(levers.options(case, 'contract_months'), reverse=True):
            t = complete_offer(case, {**ours, 'contract_months': months})
            if months > ours['contract_months'] and must_haves_ok(case, t, std) and total_cost(case, t, std, supplier) <= baseline + .01:
                return t
        return ours
