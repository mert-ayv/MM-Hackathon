"""Free tests for csee/fallback.py: auto profiles for unknown suppliers, the intel hook, the async model."""

import json
import time
from pathlib import Path

import pytest

from arena_kit.data import DataPackage
from csee import agents, fallback, intel

CASES = Path(__file__).parents[1] / "csee" / "cases" / "practice.json"
DATA = next(
    (p for p in (Path(__file__).parents[1] / "data" / "package", Path(__file__).parents[2] / "data") if p.exists()),
    Path(__file__).parents[1] / "data" / "package",
)
pytestmark = pytest.mark.skipif(not CASES.exists() or not DATA.exists(), reason="no case files or data package")

NEW_CASE = {
    "case_id": "case:X01",
    "type": "price_increase",
    "title": "Odlewnia Nowak announces +7 % on bearing housings",
    "briefing": "You negotiate for Hollerau Pumpenwerke with Odlewnia Nowak Sp. z o.o.. A Polish foundry.",
    "trigger_doc": "doc:20261020-79999-X01",
    "parts": ["part:399999"],
    "suppliers": ["sup:79999"],
    "negotiable": ["unit_price", "payment_days"],
    "fixed_terms": {
        "lead_time_days": 42,
        "volume_per_year": 5000,
        "contract_months": 12,
        "index_clause": None,
        "incoterm": "FCA",
        "tooling_eur": 0,
    },
    "term_options": {"payment_days": [14, 30, 45, 60]},
    "buyer": {
        "need_per_year": 5000,
        "horizon_years": 1.0,
        "current_unit_price": 40.0,
        "fallback_unit_price": 45.0,
        "interest_rate": 0.08,
        "reference_payment_days": 60,
        "need_lead_time_days": 42,
        "category_goal": "stabilise",
        "fallback_risk_pct": 5,
        "index_risk_pct": 4,
        "late_cost_per_day": 0,
        "cost_per_defect": 0,
        "sustainable_margin_pct": 3,
        "relationship_eur_per_point": 5000,
        "freight_eur_per_unit": {"EXW": 1.0, "FCA": 0.8, "DAP": 0.0},
        "index_paths": {},
        "must_haves": [],
        "alternative": {"kind": "none"},
    },
    "round_limit": 10,
    "refs": ["doc:20261020-79999-X01", "cost:399999"],
    "facts": {
        "doc:20261020-79999-X01": {
            "supplier": "sup:79999",
            "date": "2026-10-20",
            "type": "letter",
            "title": "Price adjustment: energy and liquidity",
            "asked_pct": 7.0,
            "days": 30,
        },
        "cost:399999": {"part": "part:399999", "unit_cost": 44.0, "price_unit": 1},
    },
}
OPENING = {
    "from": "sales@79999",
    "status": "open",
    "body": "Dear Sir or Madam,\n\nowing to energy costs we must ask EUR 42.80. To keep our liquidity we would "
    "need payment within 14 days.\nThis offer remains valid for 21 days.\n\nYours faithfully\n"
    "Jan Nowak\nOwner, Odlewnia Nowak Sp. z o.o.",
    "term_sheets": [{"term_sheet_id": "offer:79999-0", "terms": {"unit_price": 42.8, "payment_days": 30}}],
    "attachments": [
        {
            "name": "quote-offer-79999-0.pdf",
            "text": "Odlewnia Nowak Sp. z o.o.\nAngebot / Quote\n"
            "Offered terms\nUnit price (EUR) 42.80\nOur standard terms (apply to everything not stated above)\n"
            "Payment terms (days net) 30\nIncoterm FCA\nValidity: 21 days.",
        }
    ],
}


@pytest.fixture(scope="module")
def pkg():
    p = DataPackage(DATA)
    p.lookup("")
    return p


def test_archetypes_file_is_current():
    """profiles/_archetypes.json is generated: regenerate with `python -m csee.fallback archetypes`."""
    built = json.loads(json.dumps(fallback.build_archetypes(fallback.curated_profiles())))
    assert json.loads(fallback.ARCHETYPES.read_text()) == built


def test_type_c_stranger_from_case_and_opening(pkg):
    t0 = time.perf_counter()
    p = fallback.auto_profile("sup:79999", NEW_CASE, pkg, OPENING)
    assert time.perf_counter() - t0 < 1.0
    assert p["source"] == "auto" and p["confidence"] == "low" and p["stage"] == 2
    assert p["name"] == "Odlewnia Nowak Sp. z o.o." and p["country"] == "PL" and p["category"] == "castings"
    types = [x["type"] for x in p["pressures"]]
    assert "cash" in types and "energy" in types
    assert p["what_it_values"][0] == "faster payment (cash)"
    assert p["likely_tradeables"][0]["lever"] == "payment_days"
    assert p["standard_terms_hint"]["payment_days"] == 30 and p["quote_validity_days"] == 21
    # should-cost from the case's own cost: fact, at the Polish factor
    assert p["floor_estimate"] == pytest.approx(44.0 * 0.82) and p["floor_feed"]
    for key in ("supplier_id", "parts", "persona", "negotiation_history", "situation", "arguments_to_avoid"):
        assert key in p


def test_stage_1_without_opening(pkg):
    p = fallback.auto_profile("sup:79999", NEW_CASE, pkg)
    assert p["stage"] == 1 and p["floor_estimate"]


def test_long_tail_supplier(pkg):
    """Type (b): in `suppliers` and the spend cube only."""
    sid = pkg.query("SELECT id FROM suppliers WHERE detail != 'full' AND category = 'castings' LIMIT 1")[0]["id"]
    case = {**NEW_CASE, "suppliers": [sid], "facts": {}}
    p = fallback.auto_profile(sid, case, pkg)
    assert p["category"] == "castings" and p["our_spend_fy2026_eur"] > 0
    assert p["floor_method"] == "quote"


def test_hook_keeps_curated_and_fills_unknown(pkg):
    case = json.loads(CASES.read_text())[0]
    curated = intel.build(case, pkg, case["suppliers"][0])
    assert curated.profile == intel.load_profile(case["suppliers"][0]) and curated.profile.get("source") != "auto"
    stranger = intel.build(NEW_CASE, pkg, "sup:79999", 42.8, opening=OPENING)
    assert stranger.profile["source"] == "auto"
    assert stranger.full_cost == pytest.approx(44.0 * 0.82) and stranger.country == "PL"


def test_agent_plays_a_stranger(pkg):
    agent = agents.get("base")(pkg)
    threads = {"sup:79999": [OPENING]}
    agent.prepare(NEW_CASE, threads)
    msg = agent.thread_move(NEW_CASE, threads, "sup:79999")
    assert msg and all(set(ts["terms"]) == set(NEW_CASE["negotiable"]) for ts in msg["term_sheets"])
    # its own words made it cash-short: the agent values payment days at the cash-short rate
    est = agent.supplier_estimate(NEW_CASE, "sup:79999", {})
    assert est["interest_rate"] == agent.p.cash_rate and est["full_cost"] == pytest.approx(44.0 * 0.82 * 0.95)


def test_enrich_async_merges_when_ready(pkg):
    p = fallback.auto_profile("sup:79999", NEW_CASE, pkg, OPENING)

    def fake(system, user):
        assert "Odlewnia Nowak" in user and "liquidity" in user
        return json.dumps(
            {
                "situation": "Polish foundry short of cash.",
                "pressures": [
                    {"type": "ownership", "evidence": "Owner, Odlewnia Nowak Sp. z o.o."},
                    {"type": "succession", "evidence": "the owner is retiring next year"},
                    {"type": "bogus"},
                ],
                "what_it_values": ["fast payment", "a two-year contract"],
                "persona": {"style": "formal, worried"},
            }
        )

    fut = fallback.enrich_async(p, NEW_CASE, OPENING, complete=fake, budget_s=5)
    assert fut.result(timeout=5)
    assert p["enriched"] and p["situation"].startswith("Polish foundry")
    types = [x["type"] for x in p["pressures"]]
    assert "ownership" in types  # quoted from the e-mail
    assert "succession" not in types and "bogus" not in types  # not in the text / not a type
    assert p["what_it_values"][0] == "faster payment (cash)" and p["persona"]["style"] == "formal, worried"


def test_enrich_async_too_late_or_broken_changes_nothing(pkg):
    p = fallback.auto_profile("sup:79999", NEW_CASE, pkg, OPENING)
    before = json.dumps(p, sort_keys=True, default=str)

    def slow(system, user):
        time.sleep(0.3)
        return '{"situation": "late"}'

    def broken(system, user):
        raise RuntimeError("model down")

    t0 = time.perf_counter()
    f1 = fallback.enrich_async(p, NEW_CASE, OPENING, complete=slow, budget_s=0.1)
    f2 = fallback.enrich_async(p, NEW_CASE, OPENING, complete=broken, budget_s=5)
    assert time.perf_counter() - t0 < 0.1  # never blocks the move
    assert f1.result(timeout=5) is None
    with pytest.raises(RuntimeError):
        f2.result(timeout=5)
    assert json.dumps(p, sort_keys=True, default=str) == before
