"""Dossier-aware versions of the routed agents (csee/dossier: one record per final supplier).

DossierClaimsMixin - put first. An index claim on a series the supplier is hedged on at the horizon start (its
    own letter or our call note: "covered at fixed prices / bought forward until March 2027") goes LAST: P08 cited
    AS-14404 in round 1 every time and got "not our reality"; the unhedged PPI-C2431 fall moved it. mert-skiphedge
    did this for raw material only and missed hedges that are only in call notes (70190, 70560, 70730).
dossier_plan = True - the planner (PlanMixin) takes the supplier's fitted persona priors (money rate, cap decay,
    final reply, gap budget from its early-final trigger) where we met it in practice; defaults otherwise.

Nothing changes for a supplier the dossier lacks, or one with no hedge / no fitted persona.
"""

import logging
from datetime import date

from arena_kit.cost import horizon_start

from .. import dossier
from ..agent import CseeAgent
from .mert import MertSkipHedgeAgent, PlannerAgent
from .records import PlanMesoLever, PlanMesoRaw

log = logging.getLogger("csee")


def _series(claim):
    return {i[4:].split("@")[0] for i in claim.ids if isinstance(i, str) and i.startswith("idx:")}


class DossierClaimsMixin:
    def prepare(self, case, threads):
        super().prepare(case, threads)
        try:
            at = horizon_start(case) or date.today()
        except Exception:
            at = date.today()
        for sid, st in self.threads.items():
            try:
                hedged = dossier.hedged_series(dossier.get(sid, self.pkg), at)
                if not hedged:
                    continue
                late = [c for c in st.intel.claims if c.kind == "index" and _series(c) & hedged]
                if late:
                    st.intel.claims = [c for c in st.intel.claims if c not in late] + late
                    log.info("%s %s: dossier hedge %s -> %d index claims last", case["case_id"], sid,
                             sorted(hedged), len(late))
            except Exception as e:  # advisory only
                log.warning("dossier claims %s: %s", sid, e)


class BaseDossier(DossierClaimsMixin, CseeAgent):
    """base + hedge-aware claim order."""


class SkipHedgeDossier(DossierClaimsMixin, MertSkipHedgeAgent):
    """mert-skiphedge + hedge-aware claim order on every material (call-note hedges too)."""


class PlannerDossier(DossierClaimsMixin, PlannerAgent):
    dossier_plan = True


class PlanMesoLeverDossier(DossierClaimsMixin, PlanMesoLever):
    """price_increase route (mert-plan-meso-lever) + dossier planner priors + hedge-aware claims."""

    dossier_plan = True


class PlanMesoRawDossier(DossierClaimsMixin, PlanMesoRaw):
    dossier_plan = True


class PlanMesoLeverDossierClaims(DossierClaimsMixin, PlanMesoLever):
    """Claims hook only (planner on today's defaults): isolates the two hooks in the engine check."""


# claims hook only (planner on today's defaults): the final router's agents. The persona priors stay off: in the
# engine they did not help on average and lost twice in the mismatch test (sub-dossier report, Sat 21:00).
class PlannerDossierClaims(DossierClaimsMixin, PlannerAgent):
    pass


class PlanMesoRawDossierClaims(DossierClaimsMixin, PlanMesoRaw):
    pass


# soft-anchor challengers (Sat 21:15). P10: Ravensteiner goes final at reply 1 every time against our 12 % anchor
# (43 % of the room left); P18: five agents all end at 0.552, final at reply 3 after a 22 % raw anchor. The engine's
# final rule fires on a wide gap from an early reply, so a softer first ask may keep them open longer.
from dataclasses import replace as _replace  # noqa: E402

from .mert import PlanParams  # noqa: E402


class PlannerSoftClaims(PlannerDossierClaims):
    plan = _replace(PlanParams(), anchor=0.06, anchor_rel=0.06)


class PlanMesoRawSoftClaims(PlanMesoRawDossierClaims):
    plan = _replace(PlanParams(), anchor_raw=0.12)


# tick rule (P11 lesson) on the planner routes: candidates until the engine and a practice run confirm them
class PlannerTickClaims(PlannerDossierClaims):
    plan = _replace(PlanParams(), tick_rule=True)


class PlanMesoLeverTickClaims(PlanMesoLeverDossierClaims):
    plan = _replace(PlanParams(), tick_rule=True)


class PlanMesoRawTickClaims(PlanMesoRawDossierClaims):
    plan = _replace(PlanParams(), tick_rule=True)


from .mert import MertRfqAnchorAgent  # noqa: E402


class RfqAnchorDossierClaims(DossierClaimsMixin, MertRfqAnchorAgent):
    """Final RFQ route (Sun 07:50): the deeper RFQ opening (28 % / 15 % vs rivals) + hedge-aware claims.
    Live: P05 0.831 / 0.831 / 0.854, sandbox D02 0.786 / 0.77 / 0.77 vs 0.736, no walk-aways in 6 runs."""
