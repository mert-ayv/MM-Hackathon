"""Emre's EHL-final challengers: the router's planner agents with a deeper first ask. Only Emre edits this file.

Evidence (EHL Grand Finale, 11 Oct 2026, same world and suppliers: 30 cases, 474 replays): a first counter 20-25 %
below the supplier's ask ranked 0.62 within its case, 5-15 % below ranked 0.39-0.44 (0 = worst team, 1 = best).
H34: 7 % below drew "agreed" at reply 2 (0.49); 14 % below and slow steps reached its final 23.50 (0.81).

Only `anchor` changes (price_increase / renewal / capacity outside relationship goals); `anchor_rel` stays 12 %
(stabilise / secure_supply pay a relationship charge for squeezing) and `anchor_raw` stays 22 %.

    uv run python -m csee sim --agents mert-plan-dc emre-plan-deep --variants v14a   free, offline
"""

import logging
import re
from dataclasses import replace

from .mert import PlanParams
from .mert_dossier import PlanMesoLeverDossierClaims, PlannerDossierClaims
from .router import RouterAgent

log = logging.getLogger("csee")

DEEP_ANCHOR = 0.18


class PlannerDeepClaims(PlannerDossierClaims):
    """renewal / capacity route (mert-plan-dc) with an 18 % first ask."""

    plan = replace(PlanParams(), anchor=DEEP_ANCHOR)


class PlanMesoLeverDeepClaims(PlanMesoLeverDossierClaims):
    """price_increase route (mert-plan-meso-lever-dc) with an 18 % first ask."""

    plan = replace(PlanParams(), anchor=DEEP_ANCHOR)


# ---------- supplier type: owner-run shop vs corporate desk (EHL final, 411 single-supplier replays) ----------
# Who signs the supplier's e-mails predicted how its bot moved:
#   owner (206 sessions): price fell 7 % (median) from its opening, final offer at reply 3, agreed to OUR number in
#     24 % - it gives big steps early, so a deeper first ask and smaller steps of ours keep more of that room;
#   key account / export manager (110): price fell ~1 %, final at reply 5 - price barely moves, the value is in the
#     other terms (H04 Vesmo KAM: copper index clause 0.79 vs fixed price 0.46-0.69): offer trade sheets from reply 1.
# The signature works for suppliers we have never met (final wave 4 "New faces"); the profile's owner type is the
# fallback. Untested on practice suppliers.
OWNER_SIG = re.compile(r"\b(owner|inhaber(in)?|founder|gründer(in)?|jednatel|majitel)\b", re.I)
CORPORATE_SIG = re.compile(
    r"\b(key account|account manager|export manager|sales director|head of sales|vertriebsleiter(in)?|area sales)\b", re.I
)
OWNER_TYPES = {"family", "founder", "private"}
SMALL_STAFF = 150
OWNER_ANCHOR = 0.18  # planner and base: first ask at least this far below the opening (outside relationship goals)
OWNER_STEP = 0.67  # planner: our probe step x this; base: follow at most this share of its step
CORPORATE_TERMS = {"generic_trades": True, "cash_trade_always": True}


def first_body(events):
    return next((m.get("body") or "" for m in events or [] if m.get("from") != "buyer"), "")


def supplier_kind(profile, opening_body):
    """'owner', 'corporate' or None, from the signature of its first e-mail, else its profile."""
    sig = (opening_body or "")[-300:]
    if CORPORATE_SIG.search(sig):
        return "corporate"
    if OWNER_SIG.search(sig):
        return "owner"
    profile = profile or {}
    owner_type = (profile.get("owner_type") or "").lower()
    try:
        staff = int(profile.get("staff") or 0)
    except (TypeError, ValueError):
        staff = 0
    if owner_type == "group":
        return "corporate"
    if owner_type in OWNER_TYPES and 0 < staff <= SMALL_STAFF:
        return "owner"
    return None


class SupplierTypeMixin:
    """Put first: class X(SupplierTypeMixin, Parent). Paces each case by its suppliers' type (see above)."""

    kinds: dict = {}
    owner_anchor = OWNER_ANCHOR
    owner_step = OWNER_STEP
    corporate = True  # practice P11 (Export Manager): 0.710 vs the router's 0.877 with the corporate terms on
    skip_types = frozenset()  # case types left exactly as routed (e.g. capacity: its soft anchor is deliberate)

    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.kinds = {}
        if case.get("type") in self.skip_types:
            return
        for sid in case["suppliers"]:
            st = self.threads.get(sid)
            profile = getattr(getattr(st, "intel", None), "profile", None)
            self.kinds[sid] = supplier_kind(profile, first_body(threads.get(sid)))
        kinds = set(self.kinds.values())
        if kinds == {"owner"}:  # base's Params are per case: change them only when every supplier is that type
            self.p = replace(
                self.p,
                anchor_below_open=max(self.p.anchor_below_open, self.owner_anchor),
                follow_share=min(self.p.follow_share, self.owner_step),
            )
        elif kinds == {"corporate"} and self.corporate:
            self.p = replace(self.p, **CORPORATE_TERMS)
        log.info("%s supplier types: %s", case["case_id"], self.kinds)

    def plan_for(self, sid):  # the planner's per-supplier parameters (PlanMixin); unused by other agents
        P = super().plan_for(sid)
        if self.kinds.get(sid) == "owner":
            return replace(P, anchor=max(P.anchor, self.owner_anchor), probe=P.probe * self.owner_step)
        return P


_TYPED = {}


def typed(cls, settings=()):
    key = (cls, tuple(settings))
    if key not in _TYPED:
        _TYPED[key] = type(f"Typed{cls.__name__}", (SupplierTypeMixin, cls), dict(settings))
    return _TYPED[key]


class TypedRouterAgent(RouterAgent):
    """The final router (same ROUTES), every routed agent paced by supplier type."""

    settings = ()  # SupplierTypeMixin attributes to override: (("owner_anchor", 0.15), ...)

    def _route(self, case):
        fresh = self.case_id != case["case_id"]
        inner = super()._route(case)
        if fresh and not isinstance(inner, SupplierTypeMixin):
            inner.__class__ = typed(type(inner), self.settings)
        return inner


class OwnerRouterAgent(TypedRouterAgent):
    """Owner side only: the corporate terms off (P11), capacity left as routed (its soft anchor is deliberate).

    Sim sweep (owner cases, 12 seeds, anchor 0.12-0.26 x step 0.5-1.0): smaller steps of ours only cost (P05 -0.03),
    a deeper first ask helps P13/P15 up to ~22 % (+0.03/+0.05), flat beyond; P09's +0.13 is its 4 % capacity anchor
    going deep at any depth - skipped here."""

    settings = (
        ("owner_anchor", 0.22),
        ("owner_step", 1.0),
        ("corporate", False),
        ("skip_types", frozenset({"capacity"})),
    )
