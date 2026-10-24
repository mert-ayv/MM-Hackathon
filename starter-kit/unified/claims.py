"""NEGOTIATE, the arguments: which checked facts go into an e-mail (cost and contract facts, history,
rivals that beat this supplier), never one ID twice in a case."""

from arena_kit.play import standing

from . import intel as intel_mod
from .intel import _fact


class Claims:
    """Mixin of UnifiedAgent (needs self.p, self.threads, self.pkg, self.shared_lock, ...)."""

    def keep_claim(self, case, c):
        """Cost-first arguments only; never a history should-cost whose figure the data does not know."""
        if c.kind not in self.p.claim_kinds:
            return False
        if c.source == "history" and c.kind == "should_cost" and any(not _fact(case, self.pkg, i) for i in c.ids):
            return False
        return True

    def pick_claims(self, case, threads, sid):
        st = self.threads[sid]
        claims = [c for c in st.intel.claims if self.p.history_claims or c.source != "history"]
        if len(case["suppliers"]) > 1:
            stand = {s: standing(threads[s]) for s in threads}
            rivals = intel_mod.rival_claims(case, stand, sid)
            mine = stand.get(sid, (None, {}))[1].get("unit_price") or 0
            cited = st.cited_rival
            rivals = [
                c for c in rivals if c.price is not None and c.price < mine and (cited is None or c.price < cited)
            ]
            if rivals:
                st.cited_rival = rivals[0].price
            claims = [c for c in rivals if c.kind in self.p.claim_kinds] + claims
        out = []
        with self.shared_lock:  # check-and-claim: two threads must not cite the same ID
            for c in claims:
                key = tuple(c.ids) if c.kind != "rival" else (sid, *c.ids)
                if key in self.used_ids or any(i in self.used_ids for i in c.ids if c.kind != "rival"):
                    continue
                out.append(c)
                self.used_ids.add(key)
                self.used_ids.update(i for i in c.ids if c.kind != "rival")
                first = not any(m.get("from") == "buyer" for m in threads[sid])
                if len(out) >= (self.p.max_claims + 1 if first and self.p.first_extra_claim else self.p.max_claims):
                    break
        return out
