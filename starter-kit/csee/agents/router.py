"""The router: plays each case with the team agent that wins its case type.

Each slot in ROUTES is `agent` or `agent/variant` - the same labels the board shows. Point a slot
at whichever agent beats the others on that type (`python -m csee board`, `sim --agents ...`).
Without a variant in the slot, the router's own `--variant` applies. The final runs
`python -m csee --agent router final`.

The case type is known only when the case opens, so the real agent is built in `prepare` and
every call and attribute is forwarded to it.
"""

import logging

log = logging.getLogger("csee")

# case type -> agent[/variant]; every type the arena knows (brief/api.md, "Case file")
ROUTES = {
    # "-d"/"-dc" agents (Sat 21:00): + supplier dossier (csee/dossier, all 46 final suppliers): index arguments on a
    # series the supplier is hedged on go last (letters AND call notes; re-derived from the Sunday release at runtime).
    # Persona priors for the planner stay off (no average gain in the engine, losses when the persona is wrong).
    # "a" variants (Sat 20:00) add one guarded argument: the case's alternative quote, cited only when it is below the
    # supplier's ask (verified; bots then give "half the step now"). It never fires on the 10 practice cases, so the
    # practice results below carry over unchanged.
    # practice evidence, Sat 24 Oct (experiments/ ledger); v15's push after a final offer made P02 walk (0.48 -> 0)
    "price_increase": "mert-plan-meso-lever-dc/v14a",  # P01 0.975 (planner + 14-day MESO; engine 0.962), P02 engine = mert-lever 0.733 (copper clause kept). NEVER mert-lever* on raw material
    "renewal": "mert-plan-dc/v14a",  # A/B Sat 20:43: P03 0.923 / P04 0.86 in both routers; planner far fewer walk-aways on perturbed suppliers
    "rfq": "base-d/v7a",  # P05 v7 0.81 vs base 0.35, ege/v9 0.52
    "raw_material": "mert-plan-meso-raw-dc/v16a",  # A/B: P08 0.744 vs skip-hedge 0.711 (its runs avg 0.72, best 0.754); P18 0.552 both; engine >=
    "capacity": "base-d/v14s",  # soft-anchor study Sat 21:30: Ravensteiner (desk authority 2 %) answers a 4 % anchor "open" (12 %: final at
    # reply 1); it charges ~2.00/unit for 42 vs 56 days lead, 14 late days cost us 0.71. base/v14s switched to 56 d itself -> 31.50 = 0.679;
    # the planner kept 42 d and took a final 33.20 = 0.601 (4 % and 6 %), 0.671 only when the bot volunteered its 54-d alternative
    "quality": "base-d/v14a",  # A/B: P11 0.71 vs planner 0.626 (planner accepted a hold at 46.00; rule since disabled, untested)
    "bundling": "base-d/basea",  # A/B: P07 0.766 (best) vs planner 0.734
}
FALLBACK = "base-d/v14a"  # a type the final brings that ROUTES does not list


def resolve(route, params):
    """(agent class, params) for an `agent[/variant]` slot."""
    from .. import variants
    from . import get

    name, _, variant = route.partition("/")
    return get(name), variants.params(variant) if variant else params


class RouterAgent:
    # set on the router by the runner (`agent.log` before prepare, `agent.cap_at` after): the agent playing
    # the case must see them, so they are passed on - __getattr__ only forwards reads
    FORWARD = ("log", "cap_at")

    def __init__(self, package=None, writer=None, params=None):
        self.pkg, self.writer, self.params = package, writer, params
        self.inner, self.case_id = None, None

    def _route(self, case):
        if self.case_id != case["case_id"]:
            route = self.routes().get(case.get("type"), self.fallback())
            cls, params = resolve(route, self.params)
            self.inner, self.case_id = cls(self.pkg, self.writer, params), case["case_id"]
            for name in self.FORWARD:
                if name in self.__dict__:
                    setattr(self.inner, name, self.__dict__[name])
            log.info("%s (%s): %s", case["case_id"], case.get("type"), route)
        return self.inner

    @staticmethod
    def routes():
        return ROUTES

    @staticmethod
    def fallback():
        return FALLBACK

    def prepare(self, case, threads):
        return self._route(case).prepare(case, threads)

    def thread_move(self, case, threads, sid):
        return self._route(case).thread_move(case, threads, sid)

    def close(self, case, threads, force=False):
        return self._route(case).close(case, threads, force)

    def decide(self, case, threads):
        return self._route(case).decide(case, threads)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name in self.FORWARD and self.__dict__.get("inner") is not None:
            setattr(self.inner, name, value)

    def __getattr__(self, name):  # threads, p, ... of the agent playing the case
        inner = self.__dict__.get("inner")
        if inner is None:
            raise AttributeError(f"{name}: no case routed yet")
        return getattr(inner, name)


# A/B candidate for the final (Sat evening): the online move planner on every non-RFQ type. Engine: fitted personas
# .764 vs .752, perturbed unknown suppliers .658 vs .615 with 3 walk-aways vs 36; real P01 0.975 (planner + MESO).
PLAN_ROUTES = {
    "price_increase": "mert-plan-meso-lever/v14a",
    "renewal": "mert-plan/v14a",
    "rfq": "base/v7a",
    "raw_material": "mert-plan-meso-raw/v16a",
    "capacity": "mert-plan/v14a",
    "quality": "mert-plan/v14a",
    "bundling": "mert-plan/basea",
}
PLAN_FALLBACK = "mert-plan/v14a"


class RouterPlanAgent(RouterAgent):
    @staticmethod
    def routes():
        return PLAN_ROUTES

    @staticmethod
    def fallback():
        return PLAN_FALLBACK
