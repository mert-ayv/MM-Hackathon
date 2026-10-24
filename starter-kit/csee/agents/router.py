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
    "price_increase": "base",
    "renewal": "base",
    "rfq": "base",
    "raw_material": "emre/base",  # pinned: emre with v13 switches offered 30 days (raw-material review, P18 -0.048)
    "capacity": "base",
    "quality": "base",
    "bundling": "base",
}
FALLBACK = "base"  # a type the final brings that ROUTES does not list


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
            route = ROUTES.get(case.get("type"), FALLBACK)
            cls, params = resolve(route, self.params)
            self.inner, self.case_id = cls(self.pkg, self.writer, params), case["case_id"]
            for name in self.FORWARD:
                if name in self.__dict__:
                    setattr(self.inner, name, self.__dict__[name])
            log.info("%s (%s): %s", case["case_id"], case.get("type"), route)
        return self.inner

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
