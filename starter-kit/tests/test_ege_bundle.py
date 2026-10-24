"""Offline checks for sourced bundle quantities and dimensionally comparable claims."""

import copy
import json
from pathlib import Path

import pytest

from arena_kit.data import DataPackage
from csee.agents.bundle_evidence import bundle_claim, bundle_context, claim_is_comparable
from csee.agents.strategy_support import EvidenceDesk
from csee.intel import Claim

ROOT = Path(__file__).parents[2]


def unknown_case():
    return {
        "case_id": "case:UNSEEN-KIT",
        "type": "bundling",
        "parts": ["part:alpha", "part:beta"],
        "suppliers": ["sup:unseen"],
        "trigger_doc": "doc:kit-definition",
        "refs": ["doc:kit-definition"],
        "buyer": {"need_per_year": 1250},
        "fixed_terms": {"volume_per_year": 1250},
        "facts": {
            "doc:kit-definition": {"body": "Kit per unit:\n- 3 x Long pin (part:alpha)\n- 8 x Clip (part:beta)\n"}
        },
    }


def desk_for(case):
    return EvidenceDesk(case, None, case["suppliers"][0], {})


def test_actual_p07_has_sourced_quantities_normalized_prices_and_scoped_spend():
    cases = json.loads((ROOT / "starter-kit/csee/cases/practice.json").read_text())
    case = next(c for c in cases if c["case_id"] == "case:P07")
    package = DataPackage(ROOT / "data")
    try:
        report = bundle_context(case, EvidenceDesk(case, package, case["suppliers"][0], {}))
        assert report["available"]
        assert report["source_ids"] == ["doc:20260909-70610-P07"]
        parts = {row["part_id"]: row for row in report["parts"]}
        assert [parts[p]["quantity_per_kit"] for p in case["parts"]] == [19, 6, 21, 23]
        assert [parts[p]["annual_units"] for p in case["parts"]] == [570000, 180000, 630000, 690000]
        own_nut = next(p for p in parts["part:360012"]["price_benchmarks"] if p["supplier_id"] == "sup:70610")
        own_washer = next(p for p in parts["part:360030"]["price_benchmarks"] if p["supplier_id"] == "sup:70610")
        assert own_nut["price_eur"] == 4.91 and own_nut["eur_per_component"] == 0.0491
        assert own_washer["price_eur"] == 12.78 and own_washer["eur_per_component"] == 0.01278
        assert parts["part:360010"]["incumbent_sourcing"][0]["source"]["table"] == "sourcing"
        assert report["component_price_benchmark"]["eur_per_kit"] == pytest.approx(5.94762)
        assert "not a bundle quotation" in report["component_price_benchmark"]["meaning"]
        assert report["supplier_incumbent_spend"]
        assert "not necessarily this kit" in report["supplier_incumbent_spend"][0]["scope"]
        claim = bundle_claim(report)
        assert claim.kind == "bundle_scope" and claim.ids == report["source_ids"]
        assert "570000" in claim.sentence and "30000 kits" in claim.sentence
    finally:
        package.db.close()


def test_unseen_memo_calculates_requirements_without_inventing_prices_or_extra_volume():
    case = unknown_case()
    report = bundle_context(case, desk_for(case))
    assert report["available"] and report["annual_volume_is_fixed"]
    assert [p["annual_units"] for p in report["parts"]] == [3750, 10000]
    assert all(p["price_benchmarks"] == [] for p in report["parts"])
    assert all(p["incumbent_sourcing"] == [] for p in report["parts"])
    assert "component_price_benchmark" not in report
    assert report["supplier_incumbent_spend"] == []
    claim = bundle_claim(report)
    assert "1250 kits" in claim.sentence and "extra" not in claim.sentence
    assert claim.ids == ["doc:kit-definition"]


def test_structured_hidden_case_bom_overrides_old_package_memo():
    case = unknown_case()
    case["facts"]["doc:hidden-kit"] = {
        "bom": [
            {"part_id": "part:alpha", "quantity_per_kit": 0.5},
            {"part_id": "part:beta", "quantity_per_kit": 4},
        ]
    }
    report = bundle_context(case, desk_for(case))
    assert report["available"]
    assert report["source_ids"] == ["doc:hidden-kit"]
    assert [p["annual_units"] for p in report["parts"]] == [625, 5000]


@pytest.mark.parametrize(
    "body",
    [
        "Kit per unit:\n- 3 x Long pin (part:alpha)",
        "Kit per unit:\n- 3 x Long pin (part:alpha)\n- 8 x Clip (part:beta)\n- 3 x Pin (part:alpha)",
        "Kit per unit:\n- 3 x Pin (part:alpha)\n- 8 x Clip (part:unexpected)",
        "Kit per unit:\n- about three Long pin (part:alpha)\n- 8 x Clip (part:beta)",
        "Kit per unit:\n- 0 x Long pin (part:alpha)\n- 8 x Clip (part:beta)",
        "Kit per unit:\n- -3 x Long pin (part:alpha)\n- 8 x Clip (part:beta)",
        "Old totals:\n- 3 x Long pin (part:alpha)\n- 8 x Clip (part:beta)",
    ],
)
def test_missing_ambiguous_duplicate_and_mismatched_boms_do_not_create_claims(body):
    case = unknown_case()
    case["facts"]["doc:kit-definition"]["body"] = body
    report = bundle_context(case, desk_for(case))
    assert not report["available"] and report["warnings"]
    assert report["parts"] == [] and bundle_claim(report) is None


def test_conflicting_memos_are_rejected():
    case = unknown_case()
    case["refs"].append("doc:other-kit")
    case["facts"]["doc:other-kit"] = {"body": "Kit per unit:\n- 4 x Pin (part:alpha)\n- 8 x Clip (part:beta)"}
    report = bundle_context(case, desk_for(case))
    assert not report["available"] and any("disagree" in w for w in report["warnings"])


@pytest.mark.parametrize("quantity", [True, None, -1, float("nan"), float("inf"), "three"])
def test_structured_bom_requires_real_positive_quantities(quantity):
    case = unknown_case()
    case["facts"] = {
        "doc:kit-definition": {
            "bundle_components": [
                {"part_id": "part:alpha", "quantity_per_kit": quantity},
                {"part_id": "part:beta", "quantity_per_kit": 8},
            ]
        }
    }
    assert not bundle_context(case, desk_for(case))["available"]


def test_case_prices_must_supply_currency_and_price_unit_to_be_normalized():
    case = unknown_case()
    case["facts"].update(
        {
            "price:alpha": {
                "type": "price_condition",
                "part_id": "part:alpha",
                "supplier_id": "sup:unseen",
                "price": 12.5,
                "price_unit": 100,
                "currency": "EUR",
            },
            "price:beta": {
                "type": "price_condition",
                "part_id": "part:beta",
                "supplier_id": "sup:other",
                "price": 22,
                "price_unit": 1000,
                "currency": "EUR",
            },
            "price:wrong-currency": {
                "type": "price_condition",
                "part_id": "part:alpha",
                "price": 1,
                "price_unit": 100,
                "currency": "USD",
            },
            "price:missing-unit": {
                "type": "price_condition",
                "part_id": "part:beta",
                "price": 1,
                "currency": "EUR",
            },
        }
    )
    report = bundle_context(case, desk_for(case))
    assert [p["price_benchmarks"][0]["eur_per_component"] for p in report["parts"]] == [0.125, 0.022]
    assert report["component_price_benchmark"]["eur_per_kit"] == pytest.approx(0.551)
    assert report["parts"][0]["price_benchmarks"][0]["source"] == {"id": "price:alpha"}


@pytest.mark.parametrize("need,volume", [(None, 1250), (1250, 1300)])
def test_uncertain_annual_volume_does_not_create_an_annual_commitment(need, volume):
    case = unknown_case()
    case["buyer"]["need_per_year"], case["fixed_terms"]["volume_per_year"] = need, volume
    report = bundle_context(case, desk_for(case))
    assert report["available"] and report["annual_kits"] is None
    assert all(p["annual_units"] is None for p in report["parts"])
    assert "per year" not in bundle_claim(report).sentence


def test_negotiable_volume_report_is_demand_not_a_binding_supplier_commitment():
    case = unknown_case()
    case["fixed_terms"].pop("volume_per_year")
    report = bundle_context(case, desk_for(case))
    assert report["available"] and report["annual_kits"] == 1250
    assert not report["annual_volume_is_fixed"]
    assert "requirement" in bundle_claim(report).sentence


def test_long_or_incomplete_memo_is_rejected_after_two_bounded_pages():
    case = unknown_case()
    case["facts"]["doc:kit-definition"]["body"] += "\n" + " " * 20000
    report = bundle_context(case, desk_for(case))
    assert not report["available"]
    assert any("incomplete" in warning for warning in report["warnings"])


def test_generic_component_history_and_should_cost_do_not_become_kit_benchmarks():
    case = unknown_case()
    case["facts"].update(
        {
            "po:component": {"part": "part:alpha", "unit_price": 12, "price_unit": 100, "uom": "pc"},
            "cost:alpha": {"part": "part:alpha", "unit_cost": 1},
        }
    )
    desk = desk_for(case)
    assert not claim_is_comparable(case, Claim("Our orders were EUR 12.", ["po:component"], "history"), desk)
    assert not claim_is_comparable(case, Claim("Cost is EUR 1.", ["cost:alpha"], "should_cost"), desk)
    assert claim_is_comparable(case, Claim("Delivery was good.", ["sc:new"], "scorecard"), desk)
    single = {**case, "parts": ["part:alpha"]}
    assert claim_is_comparable(single, Claim("Cost is EUR 1.", ["cost:alpha"], "should_cost"), desk)


def test_explicit_aggregate_kit_unit_history_passes_but_mismatched_scope_does_not():
    case = unknown_case()
    good = {"scope": "kit", "uom": "kit", "price_unit": 1, "part_ids": case["parts"], "unit_price": 7.2}
    case["facts"]["po:kit"] = good
    claim = Claim("Our kit orders were EUR 7.20.", ["po:kit"], "history")
    assert claim_is_comparable(case, claim, desk_for(case))
    for changes in ({"part_ids": ["part:alpha"]}, {"uom": "pc"}, {"scope": None}, {"price_unit": 100}):
        wrong = copy.deepcopy(case)
        wrong["facts"]["po:kit"].update(changes)
        assert not claim_is_comparable(wrong, claim, desk_for(wrong))
