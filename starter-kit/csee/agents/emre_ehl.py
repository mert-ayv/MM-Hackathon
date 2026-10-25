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

from arena_kit.cost import RELATIONSHIP_GOALS

from .mert import PlanParams
from .mert_dossier import PlanMesoLeverDossierClaims, PlannerDossierClaims
from ..writer import before_signature
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
    owner_anchor = OWNER_ANCHOR  # owner: first ask at least this far below its opening (outside relationship goals)
    owner_anchor_rel = None  # owner, relationship goals: at least this (None: as routed)
    owner_step = OWNER_STEP  # owner: our steps x this (planner probe; base follow_share cap)
    owner_skip_types = frozenset()  # case types where owners stay as routed (capacity: its soft anchor is deliberate)
    corporate = True  # corporate: trade sheets + faster-payment sheet (practice P11: 0.710 vs 0.877 with it on)
    corporate_anchor_cap = None  # corporate: first ask at most this far below its opening (desk authority is small)
    corporate_step = 1.0  # corporate: our steps x this
    corporate_alt_discount = 0.0  # corporate: our alternative sheets this much cheaper (P02: a KAM agreed to one at r1)
    corporate_skip_types = frozenset()  # case types where corporate suppliers stay as routed
    skip_types = frozenset()  # case types left exactly as routed, every supplier type

    def prepare(self, case, threads):
        super().prepare(case, threads)
        self.kinds = {}
        if case.get("type") in self.skip_types:
            return
        for sid in case["suppliers"]:
            st = self.threads.get(sid)
            profile = getattr(getattr(st, "intel", None), "profile", None)
            kind = supplier_kind(profile, first_body(threads.get(sid)))
            if kind == "owner" and case.get("type") in self.owner_skip_types:
                kind = None
            if kind == "corporate" and case.get("type") in self.corporate_skip_types:
                kind = None
            self.kinds[sid] = kind
        kinds = set(self.kinds.values())
        p = self.p
        if kinds == {"owner"}:  # base's Params are per case: change them only when every supplier is that type
            p = replace(
                p,
                anchor_below_open=max(p.anchor_below_open, self.owner_anchor),
                anchor_leverage=max(p.anchor_leverage, self.owner_anchor) if p.anchor_leverage else 0.0,
                follow_share=p.follow_share * self.owner_step,
            )
        elif kinds == {"corporate"}:
            if self.corporate:
                p = replace(p, **CORPORATE_TERMS)
            cap = self.corporate_anchor_cap
            if cap is not None:
                p = replace(
                    p,
                    anchor_below_open=min(p.anchor_below_open, cap),
                    anchor_leverage=min(p.anchor_leverage, cap) if p.anchor_leverage else 0.0,
                )
            p = replace(p, follow_share=p.follow_share * self.corporate_step)
        self.p = p
        log.info("%s supplier types: %s", case["case_id"], self.kinds)

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        rel = case["buyer"].get("category_goal") in RELATIONSHIP_GOALS  # A3 P02: a KAM agreed to the cheaper clause
        # sheet (356.57 vs 362.00) and C went UP - below the relationship-optimal price the relationship term costs more
        if self.corporate_alt_discount and not rel and self.kinds.get(sid) == "corporate" and len(out) > 1:
            out = [out[0]] + [
                {**s, "unit_price": round(s["unit_price"] * (1 - self.corporate_alt_discount), 2)}
                if s.get("unit_price") is not None
                else s
                for s in out[1:]
            ]
        return out

    def plan_for(self, sid):  # the planner's per-supplier parameters (PlanMixin); unused by other agents
        P = super().plan_for(sid)
        kind = self.kinds.get(sid)
        if kind == "owner":
            P = replace(P, anchor=max(P.anchor, self.owner_anchor), probe=P.probe * self.owner_step)
            if self.owner_anchor_rel is not None:
                P = replace(P, anchor_rel=max(P.anchor_rel, self.owner_anchor_rel))
        elif kind == "corporate":
            cap = self.corporate_anchor_cap
            if cap is not None:
                P = replace(P, anchor=min(P.anchor, cap), anchor_raw=min(P.anchor_raw, cap))
            P = replace(P, probe=P.probe * self.corporate_step)
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


class AuthorityRouterAgent(TypedRouterAgent):
    """A1 "authority": owners decide alone and move big (deep 22 % first ask); a corporate desk moves within a small
    band (EHL KAM ~1 %, practice P10 segment manager final at reply 1 after a 12 % ask): never ask deeper than 12 %."""

    settings = (
        ("owner_anchor", 0.22),
        ("owner_step", 1.0),
        ("owner_skip_types", frozenset({"capacity"})),
        ("corporate", False),
        ("corporate_anchor_cap", 0.12),
    )


class SlowRouterAgent(TypedRouterAgent):
    """A2 "slow down": openings as routed (A1: a 12 % corporate cap made P08 walk and cost P11 0.08), owners 22 % also
    with relationship goals (16 %); our steps x 0.67 for both types - owners give big early steps, corporate desks
    decide late (EHL KAM final at reply 5). Capacity as routed."""

    settings = (
        ("owner_anchor", 0.22),
        ("owner_anchor_rel", 0.16),
        ("owner_step", 0.67),
        ("corporate", False),
        ("corporate_step", 0.67),
        ("skip_types", frozenset({"capacity"})),
    )


class LeverPriceRouterAgent(TypedRouterAgent):
    """A3: owners 22 % outside relationship goals (A2: 16 % with one cost P01 0.08), normal steps; corporate openings and
    steps as routed (A1/A2: every change there knocked P11 off its 0.877 path) but alternative sheets 1.5 % cheaper - a
    KAM accepts a lever sheet readily (P02 agreed to our clause sheet at reply 1 in every run). Quality and capacity as
    routed for corporate; capacity as routed for owners."""

    settings = (
        ("owner_anchor", 0.22),
        ("owner_step", 1.0),
        ("owner_skip_types", frozenset({"capacity"})),
        ("corporate", False),
        ("corporate_alt_discount", 0.015),
        ("corporate_skip_types", frozenset({"quality", "capacity"})),
    )


# ---------- hold guard: never answer a supplier's hold with a second hold of ours near agreement ----------
# A1 practice P08 (Donautal, inside sales): it held at 5.43, we held at 5.35 twice (planner "no-cross cap"), it walked
# away - score 0 instead of ~0.6. Router sim: 7 of 330 threads repeat an identical ask, 5 of them P08's raw route.
HOLD_GAP = 0.02  # accept its standing offer when it is within this share of our ask


def _main_price(msg):
    sheets = msg.get("term_sheets") or []
    return (sheets[0].get("terms") or {}).get("unit_price") if sheets else None


class HoldGuardMixin:
    def thread_move(self, case, threads, sid):
        msg = super().thread_move(case, threads, sid)
        if not msg:
            return msg
        ev = threads.get(sid) or []
        ours = [p for p in (_main_price(m) for m in ev if m.get("from") == "buyer") if p]
        theirs = [p for p in (_main_price(m) for m in ev if m.get("from") != "buyer") if p]
        new = (msg.get("term_sheets") or [{}])[0].get("terms", {}).get("unit_price")
        if (
            new
            and ours
            and len(theirs) >= 2
            and abs(new - ours[-1]) <= 0.001 * new  # we would hold ...
            and abs(theirs[-1] - theirs[-2]) <= 0.001 * theirs[-1]  # ... after it held
            and theirs[-1] <= new * (1 + HOLD_GAP)  # and it is close
        ):
            self.threads[sid].ready = True  # close() takes its standing offer if it beats the alternative
            log.info("%s %s: hold guard - it held at %.2f, we would hold at %.2f: take it", case["case_id"], sid,
                     theirs[-1], new)
            return None
        return msg


class GuardedRouterAgent(TypedRouterAgent):
    """The final router unchanged (no supplier-type settings) + the hold guard."""

    settings = (("corporate", False), ("owner_anchor", 0.0), ("owner_step", 1.0))

    def _route(self, case):
        fresh = self.case_id != case["case_id"]
        inner = RouterAgent._route(self, case)
        if fresh and not isinstance(inner, HoldGuardMixin):
            inner.__class__ = type(f"Guarded{type(inner).__name__}", (HoldGuardMixin, type(inner)), {})
        return inner


# ---------- department questions: let the supplier's back office tell us what it values ----------
# Tacto deck (slide 05): each supplier is a team of agents - sales asks Finance (costs, payment terms) and Logistics
# (capacity, delivery dates) before it answers. EHL H34, the winner asked "whether faster payment would buy any
# additional reduction and how you would quantify it"; the supplier answered with its levers ("Faster payment is
# welcome ... we are well loaded ... with overtime 35 days, at a premium"). A priced payment alternative also feeds the
# planner's revealed money rate. First message only, only terms the case lets us negotiate.
def department_questions(case):
    neg = set(case.get("negotiable") or [])
    out = []
    if "payment_days" in neg:
        out.append(
            "Could your finance team tell us what payment within 14 days would be worth to you on the unit price?"
        )
    if "lead_time_days" in neg or "volume_per_year" in neg or "contract_months" in neg:
        out.append(
            "Could your logistics team tell us whether a longer lead time or firm call-offs over the term would "
            "lower your price, and by how much?"
        )
    return "\n".join(out)


class DeptQuestionsMixin:
    def thread_move(self, case, threads, sid):
        msg = super().thread_move(case, threads, sid)
        if not msg or not msg.get("term_sheets"):
            return msg
        if any(m.get("from") == "buyer" for m in threads.get(sid) or []):
            return msg  # first message only
        addition = department_questions(case)
        if not addition:
            return msg

        def ask(body):
            return before_signature(body, addition)

        msg["body"] = ask(msg["body"])
        write = msg.get("_write")
        if write:
            msg["_write"] = lambda: ask(write())
        return msg


class DeptRouterAgent(RouterAgent):
    """The final router unchanged + department questions in the first e-mail to each supplier."""

    def _route(self, case):
        fresh = self.case_id != case["case_id"]
        inner = super()._route(case)
        if fresh and not isinstance(inner, DeptQuestionsMixin):
            inner.__class__ = type(f"Dept{type(inner).__name__}", (DeptQuestionsMixin, type(inner)), {})
        return inner
