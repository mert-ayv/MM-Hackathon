"""The supplier dossier (csee/dossier): coverage, hedges incl. call-note wording, safe fallbacks. Free, no arena."""

from datetime import date
from pathlib import Path

import pytest

from arena_kit.data import DataPackage
from csee import dossier
from csee.agents.mert import hedge_of

DATA = next(
    (p for p in (Path(__file__).parents[1] / "data" / "package", Path(__file__).parents[2] / "data") if p.exists()),
    Path(__file__).parents[1] / "data" / "package",
)
pytestmark = pytest.mark.skipif(not DATA.exists(), reason="no data package")


@pytest.fixture(scope="module")
def pkg():
    return DataPackage(DATA)


def test_covers_the_46_final_suppliers(pkg):
    sids = {r["id"] for r in pkg.query("SELECT id FROM suppliers WHERE detail = 'full'")}
    assert len(sids) == 46 and sids <= set(dossier._load())


@pytest.mark.parametrize("sid,series,until", [
    ("sup:70710", "AS-14404", date(2027, 3, 1)),  # letter
    ("sup:70520", "WB-CU", date(2027, 3, 1)),  # letter + call note
    ("sup:70560", "WB-CU", date(2027, 3, 1)),  # call note only: "bought their copper forward until March 2027"
    ("sup:70730", "AS-14404", date(2027, 1, 1)),  # call note only
    ("sup:70190", "PPI-D351", date(2028, 12, 1)),  # call note only (electricity)
])
def test_hedges(pkg, sid, series, until):
    d = dossier.get(sid, pkg)
    assert series in dossier.hedged_series(d, date(2026, 11, 1))
    assert series not in dossier.hedged_series(d, date(2029, 1, 1))
    assert hedge_of(pkg, sid) == until


def test_unknown_supplier_is_neutral(pkg):
    assert dossier.get("sup:DEMO-F1", pkg) is None
    assert dossier.hedged_series(None) == set()
    assert dossier.plan_overrides(None) == {}


def test_planner_priors_only_for_fitted_personas(pkg):
    assert dossier.plan_overrides(dossier.get("sup:70110", pkg))  # P01, fitted on 27 replies
    assert dossier.plan_overrides(dossier.get("sup:70130", pkg)) == {}  # never met: inferred prior, not applied
    assert "default_rate" not in dossier.plan_overrides(dossier.get("sup:70110", pkg))
