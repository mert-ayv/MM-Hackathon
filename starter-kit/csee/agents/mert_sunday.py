"""Isolated Sunday structure experiments. No final-router changes."""
import math

from arena_kit.cost import complete_offer, must_haves_ok, total_cost
from csee import levers
from .mert import MertRfqAnchorAgent, MertQualityMenuAgent
from .mert_dossier import PlanMesoRawDossierClaims
from .router import RouterAgent


class MertSundayRouterAgent(RouterAgent):
    """Reviewable combined candidate; inherits all other current router slots."""

    @staticmethod
    def routes():
        return {**RouterAgent.routes(),
                'rfq': 'mert-rfq-anchor/v7a',
                'quality': 'mert-quality-reciprocal/v14a'}


class CashFirstMixin:
    """Put a feasible fast-payment package first, preserving the main clause.

    Require the price cut to cover our financing cost. Keep the original main
    package as an alternative, and never retract a previously quoted price on
    the same structure. This is a research candidate, not a supplier-rate claim.
    """

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        if case.get('type') not in ('raw_material', 'rfq') or not out:
            return out
        if not {'unit_price', 'payment_days'} <= set(case['negotiable']):
            return out
        main = out[0]
        faster = [d for d in levers.options(case, 'payment_days') if d < main['payment_days']]
        if not faster:
            return out
        t = complete_offer(case, {**main, 'payment_days': min(faster)})
        if not must_haves_ok(case, t, std):
            return out
        target = total_cost(case, main, std, supplier)
        price = levers.price_for(case, t, target, std, supplier)
        if price is None or price <= 0:
            return out
        t['unit_price'] = math.floor(price * 100) / 100
        if total_cost(case, t, std, supplier) > target + .01:
            t['unit_price'] = round(t['unit_price'] - .01, 2)
        fields = [f for f in case['negotiable'] if f != 'unit_price']
        previous = [s['terms']['unit_price']
                    for m in self.threads[sid].events if m.get('from') == 'buyer'
                    for s in m.get('term_sheets', [])
                    if all(s.get('terms', {}).get(f) == t.get(f) for f in fields)
                    and s.get('terms', {}).get('unit_price') is not None]
        if previous:
            t['unit_price'] = max(t['unit_price'], max(previous))
        if total_cost(case, t, std, supplier) > target + .01:
            return out
        # CseeAgent records ours.unit_price after sheets(); keep its concession
        # history aligned with the actual first sheet sent to the supplier.
        ours.clear()
        ours.update(t)
        return [t, main]


class MertRawCashFirstAgent(CashFirstMixin, PlanMesoRawDossierClaims):
    pass


class MertRfqCashFirstAgent(CashFirstMixin, MertRfqAnchorAgent):
    pass


class MertQualityReciprocalAgent(MertQualityMenuAgent):
    """Test larger reciprocal steps while a quality supplier is still open.

    Infer a price increment from observed concessions, without hard-coded case
    prices. Offer up to twice that increment, staying one increment below its
    current ask. The ordinary final-offer and must-have guards still apply.
    """

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        ours = super().next_terms(case, threads, sid, theirs, std, supplier, left)
        st = self.threads[sid]
        if not ours or case.get('type') != 'quality' or not st.our_prices or 'unit_price' not in case['negotiable']:
            return ours
        prices = st.their_prices[-4:]
        steps = [a-b for a,b in zip(prices,prices[1:]) if a-b > .009]
        if not steps:
            return ours
        tick = min(steps)
        target = min(st.our_prices[-1]+2*tick, theirs['unit_price']-tick)
        candidate = {**ours,'unit_price':round(max(ours['unit_price'],target),2)}
        return candidate if must_haves_ok(case,candidate,std) else ours


class MertQualityReciprocalSingleAgent(MertQualityReciprocalAgent):
    """Ablate the quality alternatives while keeping the reciprocal price policy."""

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        return out[:1] if case.get('type') == 'quality' else out


class MertQualityMeasuredAgent(MertQualityReciprocalAgent):
    """Use reciprocal increments only after observing a coarse, repeated step.

    Geometric or fine-grained concessions retain the established policy. Two
    similar reductions, each 0.5-2% of the current ask, support a coarse-step
    hypothesis; this gate does not assume supplier IDs or absolute prices.
    """

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        prices = self.threads[sid].their_prices[-3:]
        ask = theirs.get('unit_price') or 0
        repeated = False
        if len(prices) == 3 and ask > 0:
            a,b = prices[0]-prices[1], prices[1]-prices[2]
            repeated = (.005*ask <= min(a,b) <= max(a,b) <= .02*ask
                        and abs(a-b) <= max(.011,.05*min(a,b)))
        if repeated:
            return super().next_terms(case, threads, sid, theirs, std, supplier, left)
        return MertQualityMenuAgent.next_terms(self,case,threads,sid,theirs,std,supplier,left)


class MertMeasuredRouterAgent(MertSundayRouterAgent):
    @staticmethod
    def routes():
        return {**MertSundayRouterAgent.routes(),'quality':'mert-quality-measured/v14a'}


class MertQualityRouterAgent(RouterAgent):
    """Conservative promotion candidate: only the guarded quality improvement."""

    @staticmethod
    def routes():
        return {**RouterAgent.routes(),'quality':'mert-quality-measured/v14a'}


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
