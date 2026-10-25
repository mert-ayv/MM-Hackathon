"""Team agents: one file per person, so four strategies grow side by side on main without conflicts.

Every agent plays through the same runner, ledger and board, so their scores compare directly.
Subclassing `CseeAgent` and overriding only what you change gives you all of the contract below.

Run one with `--agent NAME` (e.g. `uv run python -m csee --agent ege sim`). `router` plays each
case with the agent that owns its case type (`agents/router.py`, ROUTES), meant for the final.

The runner's contract (`runner.play_case`), in call order:

1. `agent.log = <runlog.CaseLog or runlog.NULL>` - set by the runner before `prepare` (the router passes it
   on to the agent it routes to). API: `self.log.event(type, **fields)` (never raises) and
   `self.log.enabled` (False with --no-runlog and in tests: skip building expensive fields). Event types
   and fields: `docs/run-log.md`. `CseeAgent` emits `plan` (before each send) and `decision` (`send` /
   `wait` per thread move) through `note_plan` / `note_decision`. Logging observes; it must never change
   a decision.
2. `prepare(case, threads)` - once, single-threaded, before any worker starts. Then the runner sets
   `agent.cap_at` (Live Final: a function returning when the safety close happens; else None).
3. `thread_move(case, threads, sid) -> message | None` - one worker per supplier calls it, so calls for
   DIFFERENT suppliers run concurrently, and never two at once for the same `sid`. It runs WITHOUT the
   runner's lock, so it may be slow (LLM strategy or writer calls, 10-30 s) without stalling other threads.
   - `threads` is a snapshot: a fresh dict of list copies, taken under the lock just before the call.
     Read it freely (including other suppliers' e-mails, e.g. for `leader_cost`); don't mutate it - the
     runner appends the sent message and the reply to its own copy.
   - Mutate freely: `self.threads[sid]` (this supplier's own `ThreadState`).
   - Read only: other suppliers' `self.threads[s]` (their worker may be updating it).
   - Anything shared across suppliers that you check-and-update (e.g. `self.used_ids`, so two threads never
     cite the same data ID; a cross-thread cache) only inside `with self.shared_lock:` (an RLock made in
     `CseeAgent.__init__`; call `super().__init__`). Keep that block short: never an LLM or network call in it.
   - Optional `msg["_write"]`: a no-argument function returning the e-mail body. The runner pops it and
     calls it with a time budget (`runner.WRITE_BUDGET_S`), keeping `msg["body"]` (the template) if it is
     slow or fails. Use it for the model's wording so a hung model can't make the reply late.
   - Return None to stop writing to this supplier; set `self.threads[sid].ready = True` then.
   - If the case is closing when the decision returns (wave cap near, or another thread ended the case),
     the runner drops the message.
4. `close(case, threads, force) -> {"supplier_id", "message": {"action": accept | walk_away}}` - called
   UNDER the runner's lock with the live `threads`: as a probe while workers still run (is an idle thread
   holding the best deal?), and for the real close when every thread is ready, an idle thread holds the
   best deal, or the wave's cap is near (`max(CLOSE_BEFORE_CAP_S, slowest round + ROUND_MARGIN_S)` before
   it). It may run while other threads' `thread_move` calls are in flight: keep it fast and read-only
   (no logging; set `self.close_reason` to a short string - the runner logs the real close as a
   `decision` with that reason). Workers still deciding at the real close are not waited for.
5. `self.threads[sid].ready` and `self.threads[sid].round_s` - the runner reads the first and sets it True
   when a thread's worker fails; it appends each round's seconds (our move + the reply) to the second.
"""

from ..agent import CseeAgent
from .annika import AnnikaAgent
from .annika_capacity import AnnikaCapacity9Agent, AnnikaCapacity9J2Agent, AnnikaCapacity9JAgent, AnnikaCapacityAgent
from .ege import EgeAgent
from .emre import EmreAgent
from .mert import (
    AnchorCapAgent,
    FinalCandidateAgent,
    GatedPushAgent,
    MertAgent,
    MertQualityMenuAgent,
    MertFixedProbeAgent,
    MertFixedLadderAgent,
    MertRawJointMenuAgent,
    MertAnchorAgent,
    MertClauseAgent,
    MertConsistentAgent,
    MertRawFocusedAgent,
    MertRfqAnchorAgent,
    MertDialogueAgent,
    MertHedgeAgent,
    MertHedgeLateAgent,
    MertLeverAgent,
    MertLeverRawAgent,
    MertRawAgent,
    MertSkipHedgeAgent,
    PlannerAgent,
    PlannerLeverAgent,
    PlannerRawAgent,
)
from .records import (
    PlanDb0Raw,
    PlanMesoBase,
    MesoBase,
    MesoLever,
    MesoMert,
    PlanMesoLever,
    PlanMesoRaw,
    PlanMesoRawSoft,
    PlanMesoRawSoft12,
    PlanMesoRawSoft18,
    PlanMesoLeverReal,
    PlannerSoftRel,
    PledgeBase,
)
from .mert_dossier import (
    RfqAnchorDossierClaims,
    PlannerTickClaims,
    PlanMesoLeverTickClaims,
    PlanMesoRawTickClaims,
    BaseDossier,
    PlanMesoLeverDossier,
    PlanMesoLeverDossierClaims,
    PlanMesoRawDossier,
    PlannerDossier,
    PlannerDossierClaims,
    PlanMesoRawDossierClaims,
    PlannerSoftClaims,
    PlanMesoRawSoftClaims,
    SkipHedgeDossier,
)
from .router import RouterAgent, RouterClaimsAgent, RouterPlanAgent
from .mert_sunday import MertRfqLeadMenuAgent, MertRawLongAgent, MertRawCashFirstAgent, MertRfqCashFirstAgent, MertQualityReciprocalAgent, MertQualityReciprocalSingleAgent, MertSundayRouterAgent
from .mert_sunday import MertQualityMeasuredAgent, MertMeasuredRouterAgent, MertQualityRouterAgent
from .unified import UnifiedAgent, UnifiedFastAgent, UnifiedReviewAgent, UnifiedSingleAgent

AGENTS = {
    "unified": UnifiedAgent,
    "unified-single": UnifiedSingleAgent,
    "unified-fast": UnifiedFastAgent,
    "unified-review": UnifiedReviewAgent,
    "base": CseeAgent,
    "annika": AnnikaAgent,
    "annika-k": AnnikaCapacityAgent,  # capacity expert (P10/P09 evidence: docs/playbooks/capacity.md), H2 3.75 %
    "annika-k9": AnnikaCapacity9Agent,  # the same with a 9 % anchor (practice #3 P10 0.679)
    "annika-k9j": AnnikaCapacity9JAgent,  # k9 + appreciation/pay-on-terms in R1 + one R2 jump (P10 #5: 0.686)
    "annika-k9j2": AnnikaCapacity9J2Agent,  # k9j with a 12 % anchor and the R2 jump to 31.34 (fit on #2/#3/#5)
    "ege": EgeAgent,
    "emre": EmreAgent,
    "mert": MertAgent,
    "mert-quality-menu": MertQualityMenuAgent,
    "mert-fixed-probe": MertFixedProbeAgent,
    "mert-fixed-ladder": MertFixedLadderAgent,
    "mert-raw-joint-menu": MertRawJointMenuAgent,
    "mert-dialogue": MertDialogueAgent,
    "mert-anchor": MertAnchorAgent,
    "mert-consistent": MertConsistentAgent,
    "mert-raw-focused": MertRawFocusedAgent,
    "mert-rfq-anchor": MertRfqAnchorAgent,
    "mert-rfq-lead-menu": MertRfqLeadMenuAgent,
    "mert-raw-long": MertRawLongAgent,
    "mert-raw-cash-first": MertRawCashFirstAgent,
    "mert-rfq-cash-first": MertRfqCashFirstAgent,
    "mert-quality-reciprocal": MertQualityReciprocalAgent,
    "mert-quality-reciprocal-single": MertQualityReciprocalSingleAgent,
    "mert-sunday-router": MertSundayRouterAgent,
    "mert-quality-measured": MertQualityMeasuredAgent,
    "mert-measured-router": MertMeasuredRouterAgent,
    "mert-quality-router": MertQualityRouterAgent,
    "mert-clause": MertClauseAgent,
    "mert-raw": MertRawAgent,
    "mert-hedge": MertHedgeAgent,
    "mert-hedge-late": MertHedgeLateAgent,
    "mert-lever": MertLeverAgent,
    "mert-lever-raw": MertLeverRawAgent,
    "mert-skiphedge": MertSkipHedgeAgent,
    "mert-anchorcap": AnchorCapAgent,
    "mert-gatedpush": GatedPushAgent,  # rejected: P18 afada094 walked after a push inside the gate
    "mert-final": FinalCandidateAgent,
    "mert-plan": PlannerAgent,  # online move planner (engine-model caps / gap budget), base terms
    "mert-plan-lever": PlannerLeverAgent,  # planner + mert-lever sheets (price_increase)
    "mert-plan-raw": PlannerRawAgent,  # planner + mert raw-material sheets
    "mert-meso": MesoBase,  # records study: shortest/longest payment sheets at equal C (P01 record = 14 days)
    "mert-meso-lever": MesoLever,
    "mert-meso-raw": MesoMert,
    "mert-plan-meso-lever": PlanMesoLever,  # planner + payment MESO + levers (P01 14-day route)
    "mert-plan-meso-raw": PlanMesoRaw,  # planner + payment MESO + skip-hedge raw packages
    "mert-plan-raw-soft": PlanMesoRawSoft,  # soft-anchor study: 15 % raw anchor + tight gap budget (P18)
    "mert-plan-raw-soft12": PlanMesoRawSoft12,  # 12 % raw anchor, default gaps
    "mert-plan-raw-soft18": PlanMesoRawSoft18,  # 18 % raw anchor + tight gap budget
    "mert-plan-softrel": PlannerSoftRel,  # 4 % anchor for relationship goals (P10 capacity)
    "mert-plan-meso-lever-r": PlanMesoLeverReal,  # real-cost study: relationship sheets at should-cost x 0.965 (P02)
    "mert-plan-db0-raw": PlanDb0Raw,  # P18 record route: 0 % deadband clause + 45 d on the main sheet
    "mert-pledge": PledgeBase,  # P11 record: on-time-payment commitment when payment is fixed and we paid late
    # dossier (csee/dossier): hedge-aware claims; "-d" planners also take the supplier's fitted persona priors
    "base-d": BaseDossier,
    "mert-skiphedge-d": SkipHedgeDossier,
    "mert-plan-d": PlannerDossier,
    "mert-plan-meso-lever-d": PlanMesoLeverDossier,
    "mert-plan-meso-lever-dc": PlanMesoLeverDossierClaims,  # claims hook only
    "mert-plan-meso-raw-d": PlanMesoRawDossier,
    "mert-plan-dc": PlannerDossierClaims,  # claims hook only
    "mert-plan-meso-raw-dc": PlanMesoRawDossierClaims,  # claims hook only
    "mert-plan-soft": PlannerSoftClaims,  # 6 % anchor (P10 challenger)
    "mert-plan-meso-raw-soft": PlanMesoRawSoftClaims,  # 12 % raw anchor (P18 challenger)
    "mert-plan-tick": PlannerTickClaims,  # + tick rule
    "mert-plan-meso-lever-tick": PlanMesoLeverTickClaims,  # + tick rule
    "mert-plan-meso-raw-tick": PlanMesoRawTickClaims,  # + tick rule
    "mert-plan-meso": PlanMesoBase,  # planner + payment MESO on base terms (renewal / capacity / bundling candidate)
    "mert-rfq-anchor-d": RfqAnchorDossierClaims,  # final RFQ route: deeper opening + dossier claims
    "router": RouterAgent,
    "router-plan": RouterPlanAgent,  # A/B candidate: the planner on every non-RFQ type
    "router-c": RouterClaimsAgent,  # Sunday A/B candidate: ROUTES with every slot on its c-variant (claim_evidence)
}


def get(name):
    if name not in AGENTS:
        raise SystemExit(f"unknown agent {name!r}; known: {', '.join(AGENTS)}")
    return AGENTS[name]
