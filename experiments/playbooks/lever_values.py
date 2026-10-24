"""What each lever is worth in EUR for the capacity (P09, P10) and quality (P11, P12) practice cases.

Pure arithmetic over the published cost function; no arena calls. Run from the repo root:
    uv run --directory starter-kit python ../experiments/playbooks/lever_values.py
Feeds docs/playbooks/capacity.md and docs/playbooks/quality.md.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "starter-kit"))
from arena_kit.cost import cost_breakdown, total_cost  # noqa: E402

CASES = {c["case_id"]: c for c in json.loads((ROOT / "starter-kit/csee/cases/practice.json").read_text())}

# Reference deals: the supplier's standard terms (quote PDF in our real games, else the case/alternative)
# and a plausible landing point. Full cost = should-cost of its own plant where the data has one.
SETUPS = {
    "case:P09": dict(
        std={"payment_days": 30, "incoterm": "EXW", "lead_time_days": 35, "ppm_commitment": 731,
             "chargeback_eur_per_complaint": 0, "tooling_eur": 0},
        deal={"unit_price": 16.02, "lead_time_days": 28, "volume_per_year": 15600, "payment_days": 60},
        full_cost=15.40,
    ),
    "case:P10": dict(
        std={"payment_days": 30, "incoterm": "DAP", "ppm_commitment": 300, "chargeback_eur_per_complaint": 0,
             "tooling_eur": 0, "lead_time_days": 54},
        deal={"unit_price": 29.89, "lead_time_days": 42, "volume_per_year": 23400, "contract_months": 36},
        full_cost=24.31,
    ),
    "case:P11": dict(
        std={"payment_days": 60, "incoterm": "FCA", "chargeback_eur_per_complaint": 0, "tooling_eur": 0,
             "ppm_commitment": 6400},
        deal={"unit_price": 45.15, "ppm_commitment": 300, "chargeback_eur_per_complaint": 0},
        full_cost=None,
    ),
    "case:P12": dict(
        std={"payment_days": 45, "incoterm": "DAP", "chargeback_eur_per_complaint": 150, "tooling_eur": 0,
             "ppm_commitment": 4118, "lead_time_days": 21},
        deal={"unit_price": 100.14, "ppm_commitment": 800, "chargeback_eur_per_complaint": 150, "lead_time_days": 21},
        full_cost=None,
    ),
}


def supplier(case_id, rate=0.08):
    s = SETUPS[case_id]
    if not s["full_cost"]:
        return None
    case = CASES[case_id]
    std = {**s["std"], **case.get("fixed_terms", {})}
    std.setdefault("volume_per_year", case["buyer"]["need_per_year"])
    std.setdefault("contract_months", 12)
    std.setdefault("lead_time_days", case["buyer"]["need_lead_time_days"])
    std.setdefault("unit_price", s["deal"]["unit_price"])
    return {"full_cost": s["full_cost"], "interest_rate": rate, "standard": std}


def c(case_id, **over):
    s = SETUPS[case_id]
    return total_cost(CASES[case_id], {**s["deal"], **over}, s["std"], supplier(case_id))


def report(case_id):
    case, s = CASES[case_id], SETUPS[case_id]
    b = case["buyer"]
    base = c(case_id)
    print(f"\n=== {case_id} {case['type']} ({b['category_goal']}) - reference deal {s['deal']}")
    print(f"C = {base:,.0f}")
    print("  breakdown:", {k: round(v) for k, v in cost_breakdown(case, s["deal"], s["std"], supplier(case_id)).items() if v})
    per_eur = c(case_id, unit_price=s["deal"]["unit_price"] + 1) - base
    print(f"  +1.00 EUR unit price           = {per_eur:>12,.0f} EUR")
    for f, opts in case.get("term_options", {}).items():
        if f not in case["negotiable"]:
            continue
        row = []
        for v in opts:
            d = c(case_id, **{f: v}) - base
            row.append(f"{v}: {d:+,.0f} ({d / per_eur:+.2f} EUR/u)")
        print(f"  {f:<30} " + " | ".join(row))
    if b.get("relationship_eur_per_point") and s["full_cost"]:
        print("  relationship term vs price (supplier at 8% / cash-short 14%):")
        for p in [round(s["full_cost"] * k, 2) for k in (1.0, 1.03, 1.06, 1.08, 1.1, 1.12, 1.15, 1.2)]:
            br = cost_breakdown(case, {**s["deal"], "unit_price": p}, s["std"], supplier(case_id))
            br14 = cost_breakdown(case, {**s["deal"], "unit_price": p}, s["std"], supplier(case_id, 0.14))
            print(f"    price {p:>7.2f}: relationship {br['relationship']:>10,.0f}   (cash-short: {br14['relationship']:>10,.0f})")


if __name__ == "__main__":
    for cid in SETUPS:
        report(cid)
