"""OPEN, the term sheets: our main sheet, the priced trades (faster payment, longer contract, earlier start,
more volume), the risk-sharing index-clause sheet on the index the supplier blames, and faster payment
for price when its own sheets reveal a high cost of money. At most three sheets."""

import logging

from arena_kit.cost import complete_offer, must_haves_ok, total_cost

from . import levers
from .intel import _q

log = logging.getLogger("unified")
PAY_MARGIN = 1.2  # trade payment only if its revealed rate beats ours by this factor (a clear mutual gain)


class Opening:
    """Mixin of UnifiedAgent (needs self.p, self.threads, self.pkg, self.shared_lock, ...)."""

    def current_clause(self, sid):
        """The index series our current contract with this supplier follows, or None (also without data)."""
        if self.pkg is None:
            return None
        try:
            rows = _q(
                self.pkg,
                "SELECT cc.series FROM contract_clauses cc JOIN contracts c ON c.id = cc.contract_id "
                "WHERE c.supplier_id = ? AND cc.type = 'index' AND cc.series IS NOT NULL AND cc.series != ''",
                (sid,),
            )
        except Exception:
            return None
        return rows[0]["series"] if rows else None

    # ---------- OPEN: term sheets ----------
    def sheets(self, case, sid, ours, std, supplier):
        """Base sheets, plus the risk-sharing clause sheet and the payment-for-price sheet (at most 3)."""
        out = self.base_sheets(case, sid, ours, std, supplier)
        if "unit_price" not in case["negotiable"]:
            return out
        try:
            if not out[0].get("index_clause"):
                clause = self.clause_sheet(case, sid, out[0], std, supplier)
                if clause and clause not in out:  # an alternative, never the lead (sim P14: leading 0.40 -> 0.25)
                    out = [out[0], clause] + out[1:]
            pay = self.payment_sheet(case, sid, out[0], std, supplier)
            if pay and pay not in out:
                out = [out[0], pay] + out[1:]
        except Exception:  # a sheet we cannot build must never cost the case
            log.exception("%s %s: extra sheets failed", case["case_id"], sid)
        return out[:3]

    def clause_sheet(self, case, sid, main, std, supplier):
        """`main` with an index clause on the series the supplier blames (any for raw material), widest deadband,
        priced so it costs us trade_gain less than `main`: taking it is never worse for us."""
        if "index_clause" not in case["negotiable"]:
            return None
        st = self.threads[sid]
        options = [c for c in levers.options(case, "index_clause") if c]
        wanted = st.blamed | ({st.status_quo_clause} if st.status_quo_clause else set())
        clauses = [c for c in options if c.get("series") in wanted]
        if not clauses and case.get("type") == "raw_material":
            clauses = options
        if not clauses:
            return None
        clause = max(clauses, key=lambda c: c.get("deadband_pct") or 0)
        t = complete_offer(case, {**main, "index_clause": clause})
        if not must_haves_ok(case, t, std):
            return None
        if self.p.trade_no_rel:
            supplier = None  # with the relationship term C is not monotone in price: price_for returns None (P02)
        target = total_cost(case, main, std, supplier) * (1 - self.p.trade_gain)
        price = levers.price_for(case, t, target, std, supplier)
        if price is None or price <= 0:
            return None
        t["unit_price"] = price
        # no relationship-charge veto here (base's trade sheets have one): our should-cost runs above P02's real
        # cost, so it would drop the very sheet that won P02 (copper clause, 368 -> 357, score 0.63)
        return t

    def payment_sheet(self, case, sid, main, std, supplier):
        """`main` at the supplier's shorter payment term, at a price between its revealed rate and ours."""
        found = self.threads[sid].revealed_pay
        ours = case["buyer"].get("interest_rate")
        if not found or not ours or found[0] < ours * PAY_MARGIN or "payment_days" not in case["negotiable"]:
            return None
        rate, days = found
        if days >= (main.get("payment_days") or 0) or days not in levers.options(case, "payment_days"):
            return None
        t = complete_offer(case, {**main, "payment_days": days})
        cut = (rate + ours) / 2 * (main["payment_days"] - days) / 360
        t["unit_price"] = round(main["unit_price"] * (1 - cut), 2)
        if not must_haves_ok(case, t, std):
            return None
        if total_cost(case, t, std, supplier) >= total_cost(case, main, std, supplier):
            return None
        return t

    @staticmethod
    def revealed_payment(case, events):
        """What faster payment is worth to it, from its latest sheets that differ only in price and payment days:
        (yearly rate, its shorter payment days) or None."""
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
                    same = all(
                        a.get(f) == b.get(f) for f in case["negotiable"] if f not in ("unit_price", "payment_days")
                    )
                    if same and b["unit_price"] > a["unit_price"]:
                        rate = (b["unit_price"] / a["unit_price"] - 1) / ((db - da) / 360)
                        if best is None or rate > best[0]:
                            best = (rate, da)
            return best  # its latest sheets only: older ones may be stale
        return None

    def base_sheets(self, case, sid, ours, std, supplier):
        """Our main sheet, plus up to two trades: a term the supplier values for a lower price."""
        full = supplier
        if self.p.trade_no_rel:
            supplier = None  # with the relationship term C is not monotone in price: price_for returned 0 (P01)
        out = [complete_offer(case, ours)]
        if "unit_price" not in case["negotiable"]:
            return out  # a trade is a term for a lower price: nothing to trade with a fixed price
        c_main = total_cost(case, out[0], std, supplier)
        target = c_main * (1 - self.p.trade_gain)
        trades = []
        if "payment_days" in case["negotiable"]:
            faster = [d for d in levers.options(case, "payment_days") if d < out[0]["payment_days"]]
            if faster:
                trades.append(
                    {"payment_days": max(d for d in faster if d <= 30) if any(d <= 30 for d in faster) else min(faster)}
                )
        if "contract_months" in case["negotiable"]:
            longer = [m for m in levers.options(case, "contract_months") if m > out[0]["contract_months"]]
            if longer:
                trades.append({"contract_months": max(longer)})
        if "effective_date" in case["negotiable"]:
            earlier = [
                d for d in levers.options(case, "effective_date") if d and d < (out[0].get("effective_date") or "9")
            ]
            if earlier:
                trades.append({"effective_date": max(earlier)})
        if "volume_per_year" in case["negotiable"] and levers.options(case, "volume_per_year"):
            more = [v for v in levers.options(case, "volume_per_year") if v > out[0]["volume_per_year"]]
            if more:
                trades.append({"volume_per_year": min(more)})
        for change in trades:
            if len(out) >= 3:
                break
            t = complete_offer(case, {**out[0], **change})
            if not must_haves_ok(case, t, std):
                continue
            price = levers.price_for(case, t, target, std, supplier)
            if price is None or price <= 0:
                continue  # no price on the monotone branch reaches the target: no trade sheet
            t["unit_price"] = price
            if self.p.trade_no_rel and full and total_cost(case, t, std, full) > total_cost(case, out[0], std, full):
                continue  # below its cost: dearer for us with the relationship charge (P17: 29.38 vs cost 35.38)
            if t not in out and price < out[0]["unit_price"] * 1.2:
                out.append(t)
        return out
