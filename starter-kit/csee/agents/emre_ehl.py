"""Emre's EHL-final challengers: the router's planner agents with a deeper first ask. Only Emre edits this file.

Evidence (EHL Grand Finale, 11 Oct 2026, same world and suppliers: 30 cases, 474 replays): a first counter 20-25 %
below the supplier's ask ranked 0.62 within its case, 5-15 % below ranked 0.39-0.44 (0 = worst team, 1 = best).
H34: 7 % below drew "agreed" at reply 2 (0.49); 14 % below and slow steps reached its final 23.50 (0.81).

Only `anchor` changes (price_increase / renewal / capacity outside relationship goals); `anchor_rel` stays 12 %
(stabilise / secure_supply pay a relationship charge for squeezing) and `anchor_raw` stays 22 %.

    uv run python -m csee sim --agents mert-plan-dc emre-plan-deep --variants v14a   free, offline
"""

from dataclasses import replace

from .mert import PlanParams
from .mert_dossier import PlanMesoLeverDossierClaims, PlannerDossierClaims

DEEP_ANCHOR = 0.18


class PlannerDeepClaims(PlannerDossierClaims):
    """renewal / capacity route (mert-plan-dc) with an 18 % first ask."""

    plan = replace(PlanParams(), anchor=DEEP_ANCHOR)


class PlanMesoLeverDeepClaims(PlanMesoLeverDossierClaims):
    """price_increase route (mert-plan-meso-lever-dc) with an 18 % first ask."""

    plan = replace(PlanParams(), anchor=DEEP_ANCHOR)
