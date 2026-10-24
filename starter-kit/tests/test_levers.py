"""The lever engine on real practice cases: quality tie-break (P11) and price_for in secure_supply (P09, P10)."""

import json
from pathlib import Path

import pytest

from arena_kit.cost import total_cost
from csee import levers

CASES = {c["case_id"]: c for c in json.loads((Path(__file__).parents[1] / "csee/cases/practice.json").read_text())}
QUALITY = ("ppm_commitment", "chargeback_eur_per_complaint")

# P11 (Kalwisz): its standard terms from the quote PDF, 6,400 ppm and no chargeback; scorecard 2,376 ppm
P11_STD = {
    "payment_days": 60,
    "incoterm": "FCA",
    "chargeback_eur_per_complaint": 0,
    "tooling_eur": 0,
    "ppm_commitment": 6400,
}
P11_SCORECARD_PPM = 2376


def quality_terms(t):
    return {f: t[f] for f in QUALITY}


@pytest.mark.parametrize(
    "base",
    [
        {"unit_price": 45.15},
        # the sheet base actually ended on: (1,500 ppm, EUR 500), quality cost EUR 0 to us
        {"unit_price": 45.15, "ppm_commitment": 1500, "chargeback_eur_per_complaint": 500},
    ],
)
def test_best_terms_p11_lowest_ppm_and_standard_chargeback(base):
    case = CASES["case:P11"]
    t = levers.best_terms(case, base, P11_STD, supplier_ppm=P11_SCORECARD_PPM)
    assert quality_terms(t) == {"ppm_commitment": 300, "chargeback_eur_per_complaint": 0}


def test_p11_chargeback_costs_the_supplier_more_than_it_is_worth_to_us():
    """The arithmetic behind the fix: EUR 500 vs 0 costs Kalwisz 2,376 ppm x 500 = EUR 1.19/unit; to us it is
    worth 300 ppm x 450 = EUR 0.135/unit (EUR 2,146 over 15,900 units)."""
    case = CASES["case:P11"]
    value = levers.supplier_value_fn(case, P11_STD, real_ppm=P11_SCORECARD_PPM)
    t = {"unit_price": 45.15, "ppm_commitment": 300}
    its_cost = value({**t, "chargeback_eur_per_complaint": 0}) - value({**t, "chargeback_eur_per_complaint": 500})
    assert its_cost == pytest.approx(1.188)
    ours = total_cost(case, {**t, "chargeback_eur_per_complaint": 0}, P11_STD) - total_cost(
        case, {**t, "chargeback_eur_per_complaint": 500}, P11_STD
    )
    assert ours == pytest.approx(2146.5, abs=1)
    # a low ppm commitment does not change its real ppm: free to it
    assert value({**t, "ppm_commitment": 1500}) == value(t)


def test_best_terms_buys_a_chargeback_only_when_it_pays_for_itself():
    """A supplier that really runs at 100 ppm: EUR 500 costs it EUR 0.05/unit, saves us EUR 0.135/unit."""
    t = levers.best_terms(CASES["case:P11"], {"unit_price": 45.15}, P11_STD, supplier_ppm=100)
    assert quality_terms(t) == {"ppm_commitment": 300, "chargeback_eur_per_complaint": 500}


def test_best_terms_old_yardstick_for_the_local_simulator():
    """supplier_cost_aware=False is the old pure-C pick with the 'supplier likes' tie-break (localsim C_best)."""
    t = levers.best_terms(CASES["case:P11"], {"unit_price": 45.15}, P11_STD, supplier_cost_aware=False)
    assert quality_terms(t) == {"ppm_commitment": 1500, "chargeback_eur_per_complaint": 500}


# secure_supply: full cost of its own plant (docs/playbooks/capacity.md, experiments/playbooks/lever_values.py)
SECURE = {
    "case:P10": (
        {
            "payment_days": 30,
            "incoterm": "DAP",
            "ppm_commitment": 300,
            "chargeback_eur_per_complaint": 0,
            "tooling_eur": 0,
            "lead_time_days": 54,
        },
        24.31,
        {"unit_price": 29.89, "lead_time_days": 42, "volume_per_year": 23400, "contract_months": 36},
    ),
    "case:P09": (
        {
            "payment_days": 30,
            "incoterm": "EXW",
            "lead_time_days": 35,
            "ppm_commitment": 731,
            "chargeback_eur_per_complaint": 0,
            "tooling_eur": 0,
        },
        15.40,
        {"unit_price": 16.02, "lead_time_days": 28, "volume_per_year": 15600, "payment_days": 60},
    ),
}


def secure_setup(cid):
    std, full, terms = SECURE[cid]
    case = CASES[cid]
    standard = {
        **std,
        **case.get("fixed_terms", {}),
        "volume_per_year": case["buyer"]["need_per_year"],
        "contract_months": 12,
        "unit_price": terms["unit_price"],
    }
    return case, std, {"full_cost": full, "interest_rate": 0.08, "standard": standard}, terms


@pytest.mark.parametrize("cid, p_min", [("case:P10", 26.31), ("case:P09", 15.74)])
def test_cost_minimal_price_secure_supply(cid, p_min):
    case, std, sup, terms = secure_setup(cid)
    p = levers.cost_minimal_price(case, terms, std, sup, 0.0, terms["unit_price"] * 4)
    assert p == pytest.approx(p_min, abs=0.02)
    c = total_cost(case, {**terms, "unit_price": p}, std, sup)
    # C rises on both sides: the relationship term below, the price above
    assert total_cost(case, {**terms, "unit_price": p - 1}, std, sup) > c
    assert total_cost(case, {**terms, "unit_price": p + 1}, std, sup) > c


@pytest.mark.parametrize("cid, price", [("case:P10", 29.71), ("case:P09", 15.78)])
def test_price_for_secure_supply_trade_sheet_target(cid, price):
    """The trade-sheet target (C x (1 - 0.6 %)): the old bisection from 0 converged to 0.00 here."""
    case, std, sup, terms = secure_setup(cid)
    target = total_cost(case, terms, std, sup) * (1 - 0.006)
    p = levers.price_for(case, terms, target, std, sup)
    assert p == pytest.approx(price, abs=0.02)
    # rounded to the cent: the target lies within one cent of the price, on the monotone branch
    assert total_cost(case, {**terms, "unit_price": p - 0.01}, std, sup) <= target
    assert total_cost(case, {**terms, "unit_price": p + 0.01}, std, sup) > target


@pytest.mark.parametrize("cid", ["case:P10", "case:P09"])
def test_price_for_unreachable_target_is_none(cid):
    case, std, sup, terms = secure_setup(cid)
    p_min = levers.cost_minimal_price(case, terms, std, sup, 0.0, terms["unit_price"] * 4)
    c_min = total_cost(case, {**terms, "unit_price": p_min}, std, sup)
    assert levers.price_for(case, terms, c_min - 1, std, sup) is None


def test_price_for_monotone_case_unchanged():
    """No relationship term (P11, quality_first): plain bisection from 0, as before."""
    case = CASES["case:P11"]
    terms = {"unit_price": 45.15, "ppm_commitment": 300, "chargeback_eur_per_complaint": 0}
    target = total_cost(case, terms, P11_STD) * 0.99
    p = levers.price_for(case, terms, target, P11_STD)
    assert (
        total_cost(case, {**terms, "unit_price": p}, P11_STD)
        <= target
        < total_cost(case, {**terms, "unit_price": p + 0.01}, P11_STD)
    )
    assert levers.price_for(case, terms, -1.0, P11_STD) is None
