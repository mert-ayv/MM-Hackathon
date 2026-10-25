"""EHL-final lessons, free and offline: freight decides the incoterm trap, and the challengers are wired up."""

import json
from pathlib import Path

import pytest

from arena_kit.cost import complete_offer, total_cost
from csee import agents, variants

CASES = Path(__file__).parents[1] / "csee" / "cases" / "practice.json"
pytestmark = pytest.mark.skipif(not CASES.exists(), reason="no case files")


def case(cid):
    return next(c for c in json.loads(CASES.read_text()) if c["case_id"] == cid)


def test_cheaper_exw_price_can_cost_more_than_dap():
    # EHL H03: EXW at 82.80 scored 0.25, DAP at 83.30 scored 0.97 - the unit price alone misleads
    c = case("case:P06")
    fr = c["buyer"]["freight_eur_per_unit"]
    p = c["buyer"]["fallback_unit_price"]
    dap = {**complete_offer(c, {"unit_price": p}), "incoterm": "DAP"}
    exw = {**dap, "unit_price": round(p - (fr["EXW"] - fr["DAP"]) / 2, 2), "incoterm": "EXW"}
    assert exw["unit_price"] < dap["unit_price"]
    assert total_cost(c, exw) > total_cost(c, dap)


def test_challengers_registered():
    assert agents.get("emre-plan-deep").plan.anchor == 0.18
    assert agents.get("emre-plan-meso-lever-deep").plan.anchor == 0.18
    assert agents.get("emre-plan-deep").plan.anchor_rel == agents.get("mert-plan-dc").plan.anchor_rel
    assert variants.params("baseacr").close_room == 0.05
    assert variants.params("v7acr").close_room == 0.05


def test_supplier_kind_from_signature_and_profile():
    from csee.agents.emre_ehl import supplier_kind

    assert supplier_kind({}, "Gruß\nSabine Rottaler\nOwner, Feinmechanik Rottaler GmbH") == "owner"
    assert supplier_kind({}, "Best regards\nTomáš Veselý\nKey Account Manager, Vesmo a.s.") == "corporate"
    assert supplier_kind({}, "Grace Chen\nExport Manager, Meridune Precision Castings") == "corporate"
    assert supplier_kind({"owner_type": "group"}, "Regards") == "corporate"
    assert supplier_kind({"owner_type": "family", "staff": 40}, "Regards") == "owner"
    assert supplier_kind({"owner_type": "family", "staff": 900}, "Regards") is None
    # the signature wins over the profile (a group shop whose owner still signs)
    assert supplier_kind({"owner_type": "group"}, "Max Huber\nInhaber") == "owner"


def test_typed_router_wraps_routed_agent():
    from csee.agents.emre_ehl import SupplierTypeMixin

    r = agents.get("emre-router-typed")()
    inner = r._route({"case_id": "case:X", "type": "renewal"})
    assert isinstance(inner, SupplierTypeMixin)
    assert isinstance(inner, agents.get("mert-plan-dc"))
