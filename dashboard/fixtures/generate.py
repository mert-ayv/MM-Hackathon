"""Generate fixture runs for the dashboard, strictly in the `docs/run-log.md` format.

Every C and breakdown comes from Tacto's published cost function (`arena_kit.cost`), so the
numbers are consistent with what the arena would compute. Run it from the agent's env:

    cd agent && uv run python ../dashboard/fixtures/generate.py

It rewrites `dashboard/fixtures/runs/` (deterministic: same input, same output).
"""

import itertools
import json
import random
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from arena_kit.cost import closing_terms, cost_breakdown, must_haves_ok, score, supplier_value

OUT = Path(__file__).resolve().parent / "runs"
TZ = "+02:00"


# --------------------------------------------------------------------------------------------
# Case files (shape of starter-kit/arena_kit/sim_cases/*.json; names and IDs from data/)
# --------------------------------------------------------------------------------------------

P01 = {
    "case_id": "case:P01",
    "set": "practice",
    "type": "price_increase",
    "title": "Volute casing HN 50-200: a price increase",
    "briefing": (
        "Gießerei Brandlhuber (sup:70110) announces +9.5 % on the volute casing HN 50-200 (part:310010) from "
        "1 November 2026, from EUR 126.53 to EUR 138.55, 'due to energy and wages'. Brandlhuber is our sole "
        "source and a strategic supplier: keep it healthy. Need: 7300 pc a year for 1 year."
    ),
    "trigger_doc": "doc:20260911-70110-P01",
    "parts": ["part:310010"],
    "suppliers": ["sup:70110"],
    "negotiable": ["unit_price", "payment_days", "effective_date"],
    "fixed_terms": {"volume_per_year": 7300, "contract_months": 12, "lead_time_days": 42, "incoterm": "FCA",
                    "index_clause": None, "tooling_eur": 0},
    "term_options": {"payment_days": [10, 14, 30, 45, 60, 90],
                     "effective_date": ["2026-11-01", "2027-01-01", "2027-04-01"]},
    "buyer": {
        "need_per_year": 7300, "horizon_years": 1, "current_unit_price": 126.53, "fallback_unit_price": 149.8,
        "interest_rate": 0.08, "reference_payment_days": 60, "need_lead_time_days": 42,
        "category_goal": "stabilise", "sustainable_margin_pct": 6, "relationship_eur_per_point": 2500,
        "fallback_risk_pct": 5, "index_risk_pct": 2, "late_cost_per_day": 250, "cost_per_defect": 60,
        "freight_eur_per_unit": {"EXW": 3.1, "FCA": 2.05, "DAP": 0.0}, "index_paths": {}, "must_haves": [],
        "alternative": {"kind": "none", "ref": None, "terms": {}},
    },
    "round_limit": 10,
    "refs": ["doc:20260911-70110-P01", "ctr:4600070110", "sc:70110@2026Q3", "cost:310010",
             "idx:PPI-D351@2025-08", "idx:PPI-D351@2026-08", "idx:PPI-C241@2025-08", "idx:PPI-C241@2026-08"],
    "facts": {},
}

P13 = {
    "case_id": "case:P13",
    "set": "practice",
    "type": "price_increase",
    "title": "Coupling hub: a price increase at short notice",
    "briefing": (
        "Präzisionsteile Lindlbauer (sup:70230) announces +7.0 % on the coupling hub (part:320060) from "
        "1 November 2026, from EUR 16.30 to EUR 17.44. The framework agreement ctr:4600070230 fixes prices per "
        "calendar year with 90 days' notice. Drehteile Fuchsreiter (sup:70250) is qualified as second source. "
        "Need: 14700 pc a year for 1 year."
    ),
    "trigger_doc": "doc:20260927-70230-P13",
    "parts": ["part:320060"],
    "suppliers": ["sup:70230"],
    "negotiable": ["unit_price", "payment_days", "effective_date"],
    "fixed_terms": {"volume_per_year": 14700, "contract_months": 12, "lead_time_days": 28, "incoterm": "EXW",
                    "index_clause": None, "tooling_eur": 0},
    "term_options": {"payment_days": [14, 30, 45, 60],
                     "effective_date": ["2026-11-01", "2027-01-01", "2027-04-01"]},
    "buyer": {
        "need_per_year": 14700, "horizon_years": 1, "current_unit_price": 16.3, "fallback_unit_price": 18.75,
        "interest_rate": 0.08, "reference_payment_days": 60, "need_lead_time_days": 28,
        "category_goal": "leverage", "fallback_risk_pct": 3, "index_risk_pct": 1, "late_cost_per_day": 200,
        "cost_per_defect": 40, "freight_eur_per_unit": {"EXW": 0.42, "FCA": 0.3, "DAP": 0.0}, "index_paths": {},
        "must_haves": [],
        "alternative": {"kind": "current_contract", "ref": "ctr:4600070230",
                        "terms": {"unit_price": 16.3, "payment_days": 30, "effective_date": "2026-11-01",
                                  "contract_months": 8}},
    },
    "round_limit": 10,
    "refs": ["doc:20260927-70230-P13", "ctr:4600070230", "sc:70230@2026Q3", "quote:7200013",
             "idx:PPI-C2431@2025-08", "idx:PPI-C2431@2026-08"],
    "facts": {},
}

P20 = {
    "case_id": "case:P20",
    "set": "practice",
    "type": "rfq",
    "title": "Volute casing HX 80-200: RFQ for a new part",
    "briefing": (
        "The new HX series starts production in March 2027. We ask three foundries to quote the volute casing "
        "HX 80-200 (part:310070, EN-GJS-500-7, 44 kg): Eisengießerei Velkenreith (sup:70120), Gießerei Wimbacher "
        "(sup:70130) and Odlewnia Kalwisz (sup:70140). Quality first: a casing that leaks costs us a pump. "
        "Need: 4200 pc a year for 2 years (rfq:6000000306)."
    ),
    "trigger_doc": None,
    "parts": ["part:310070"],
    "suppliers": ["sup:70120", "sup:70130", "sup:70140"],
    "negotiable": ["unit_price", "payment_days", "contract_months", "incoterm"],
    "fixed_terms": {"volume_per_year": 4200, "index_clause": None},
    "term_options": {"payment_days": [30, 45, 60, 90], "contract_months": [12, 24],
                     "incoterm": ["EXW", "FCA", "DAP"]},
    "buyer": {
        "need_per_year": 4200, "horizon_years": 2, "current_unit_price": None, "fallback_unit_price": 205.0,
        "interest_rate": 0.08, "reference_payment_days": 60, "need_lead_time_days": 56,
        "category_goal": "quality_first", "fallback_risk_pct": 6, "index_risk_pct": 2, "late_cost_per_day": 300,
        "cost_per_defect": 120, "freight_eur_per_unit": {"EXW": 5.6, "FCA": 3.9, "DAP": 0.0}, "index_paths": {},
        "must_haves": [{"field": "ppm_commitment", "op": "<=", "value": 2500}],
        "alternative": {"kind": "none", "ref": None, "terms": {}},
    },
    "round_limit": 10,
    "refs": ["rfq:6000000306", "sc:70120@2026Q3", "sc:70130@2026Q3", "sc:70140@2026Q3",
             "news:20260322-05", "news:20260911-28", "idx:PPI-C2451@2025-08", "idx:PPI-C2451@2026-08"],
    "facts": {},
}

SUPPLIERS = {
    "sup:70110": {"name": "Gießerei Brandlhuber GmbH & Co. KG", "role": "sales@70110",
                  "standard": {"payment_days": 30, "incoterm": "FCA", "lead_time_days": 42, "ppm_commitment": 800,
                               "chargeback_eur_per_complaint": 0},
                  "estimate": {"interest_rate": 0.14, "usual_rate": 0.08, "full_cost": 128.9}},
    "sup:70230": {"name": "Präzisionsteile Lindlbauer KG", "role": "sales@70230",
                  "standard": {"payment_days": 30, "incoterm": "EXW", "lead_time_days": 28, "ppm_commitment": 600,
                               "chargeback_eur_per_complaint": 150},
                  "estimate": {"interest_rate": 0.08, "full_cost": 15.6}},
    "sup:70120": {"name": "Eisengießerei Velkenreith GmbH", "role": "sales@70120",
                  "standard": {"payment_days": 45, "incoterm": "FCA", "lead_time_days": 49, "ppm_commitment": 700,
                               "chargeback_eur_per_complaint": 0, "tooling_eur": 16000, "contract_months": 12},
                  "estimate": {"interest_rate": 0.08, "full_cost": 158.0}},
    "sup:70130": {"name": "Gießerei Wimbacher GmbH", "role": "sales@70130",
                  "standard": {"payment_days": 30, "incoterm": "FCA", "lead_time_days": 45, "ppm_commitment": 750,
                               "chargeback_eur_per_complaint": 0, "tooling_eur": 18500, "contract_months": 12},
                  "estimate": {"interest_rate": 0.09, "full_cost": 156.5}},
    "sup:70140": {"name": "Odlewnia Kalwisz Sp. z o.o.", "role": "sales@70140",
                  "standard": {"payment_days": 60, "incoterm": "FCA", "lead_time_days": 70, "ppm_commitment": 2400,
                               "chargeback_eur_per_complaint": 0, "tooling_eur": 12000, "contract_months": 12},
                  "estimate": {"interest_rate": 0.16, "usual_rate": 0.09, "full_cost": 152.0}},
}

# What the dossier step would have produced (persona from correspondence, news, intel, scorecards)
DOSSIERS = {
    "sup:70110": {
        "summary": ("Family-owned foundry since 1921, our sole source for HN casings. The owner admits he has not "
                    "followed material and energy prices since 2022 and works from a two-year-old spreadsheet. "
                    "Cash is tight: equity ratio 24.7 % and he asked us to pay invoices within 10 days."),
        "persona": {"owner_type": "family", "style": "personal, loyal, proud of 2022",
                    "pressures": ["cash flow (asked for 10-day payment)", "wages: LCI-C +2.7 %",
                                  "pig iron and scrap (PPI-C241 +6.5 %)"],
                    "what_moves_it": ["faster payment", "verified index figures he can show his office manager",
                                      "recognition of the 2022 partnership"],
                    "avoid": ["threatening to re-source", "questioning his honesty"]},
        "floor_estimate": 131.6,
        "floor_source": "cost:310010 should-cost 132.64 (no margin) less 1.5 % for cash value of 14-day payment",
        "facts": [{"id": "doc:20260911-70110-P01", "text": "Letter: +9.5 % from 2026-11-01, EUR 126.53 → 138.55"},
                  {"id": "doc:20260824-70110-M1", "text": "Owner works from his own index spreadsheet, 2 years old"},
                  {"id": "doc:20260902-70110-M2", "text": "Asked us to pay within 10 days for a cash discount"},
                  {"id": "doc:20260917-70110-M3", "text": "Reminded us: kept 2022 prices for a quarter, expects partnership"},
                  {"id": "cost:310010", "text": "Should-cost EUR 132.64 per pc, no margin (±5 %)"},
                  {"id": "sc:70110@2026Q3", "text": "OTD 85.2 %, 712 ppm, amber"},
                  {"id": "idx:PPI-D351@2026-08", "text": "Electricity producer prices −3.7 % in 12 months"}],
    },
    "sup:70230": {
        "summary": ("Mid-sized machining shop with a new sales director since May 2026. The price letter gives "
                    "35 days' notice where ctr:4600070230 requires 90 days before year end. Fuchsreiter quoted "
                    "EUR 17.87 EXW in September, so Lindlbauer is still the cheapest source."),
        "persona": {"owner_type": "family", "style": "formal, rule-following; new MD wants a win",
                    "pressures": ["wage increase April 2026", "new MD's margin targets"],
                    "what_moves_it": ["the contract's notice clause", "a later effective date", "volume certainty"],
                    "avoid": ["pushing past a final_offer", "ultimatums"]},
        "floor_estimate": 16.85,
        "floor_source": "PPI-C2431 and LCI-C weighted on the 2025 price; new MD unlikely to accept < +3 %",
        "facts": [{"id": "doc:20260927-70230-P13", "text": "Letter: +7.0 % from 2026-11-01, 35 days' notice"},
                  {"id": "ctr:4600070230", "text": "Prices fixed per calendar year; 90 days' notice"},
                  {"id": "quote:7200013", "text": "Fuchsreiter: EUR 17.87 EXW, 30 days, 28 days lead"},
                  {"id": "sc:70230@2026Q3", "text": "OTD 82.1 %, 544 ppm, green"}],
    },
    "sup:70120": {
        "summary": ("Solid family foundry, VDA 6.3 grade A, 240 staff, equity ratio 38.5 %. Not under pressure and "
                    "it knows it: quotes high and moves in small steps. Reacts to a credible rival offer."),
        "persona": {"owner_type": "family", "style": "engineering-led, deliberate",
                    "pressures": ["capacity is full until Q2 2027"],
                    "what_moves_it": ["a rival's lower offer, cited", "24-month commitment"],
                    "avoid": ["haggling over cents"]},
        "floor_estimate": 171.5,
        "floor_source": "PPI-C2451 path on its HN 100-315 prices, scaled by weight",
        "facts": [{"id": "sc:70120@2026Q3", "text": "OTD 74.5 %, 734 ppm, amber"},
                  {"id": "idx:PPI-C2451@2026-08", "text": "Iron casting prices +1.8 % in 12 months"}],
    },
    "sup:70130": {
        "summary": ("Family foundry whose 66-year-old owner seeks a successor and is open to a sale "
                    "(news:20260322-05). A 24-month order book makes the company worth more: volume security "
                    "matters more to it than price."),
        "persona": {"owner_type": "family", "style": "warm, wants long-term customers",
                    "pressures": ["succession: needs a full order book for a sale"],
                    "what_moves_it": ["24-month contract", "DAP is cheap for it (own trucks to Bavaria)"],
                    "avoid": ["mentioning the succession openly"]},
        "floor_estimate": 168.0,
        "floor_source": "its quote:7100005 margin on HN 100-315, scaled by weight; succession premium on volume",
        "facts": [{"id": "news:20260322-05", "text": "Owner (66) seeks a successor, open to a sale"},
                  {"id": "sc:70130@2026Q3", "text": "OTD 88.0 %, 640 ppm, green"}],
    },
    "sup:70140": {
        "summary": ("Polish foundry in a bank-led restructuring after two loss-making years (news:20260911-28). "
                    "Cheapest on price but 70-day lead time and 2376 ppm (red). Cash is critical: it needs "
                    "volume, but cannot fund long payment terms."),
        "persona": {"owner_type": "private", "style": "eager, then rigid when cash is at stake",
                    "pressures": ["bank covenants", "cash: cannot fund 90-day terms"],
                    "what_moves_it": ["fast payment", "volume"],
                    "avoid": ["90-day terms", "quality accusations in writing"]},
        "floor_estimate": 163.0,
        "floor_source": "its 2025 quote:7100002 on HN 50-200, scaled by weight",
        "facts": [{"id": "news:20260911-28", "text": "Restructuring with its banks"},
                  {"id": "sc:70140@2026Q3", "text": "OTD 63.5 %, 2376 ppm, red"}],
    },
}


# --------------------------------------------------------------------------------------------
# Pricing helpers
# --------------------------------------------------------------------------------------------

def sup_est(sid):
    s = SUPPLIERS[sid]
    return {"standard": s["standard"], **s["estimate"]}


def priced(case, terms, sid):
    std = SUPPLIERS[sid]["standard"]
    breakdown = {k: round(v, 2) for k, v in cost_breakdown(case, terms, std, sup_est(sid)).items()}
    return {"terms": terms, "c": round(sum(breakdown.values()), 2), "breakdown": breakdown}


def c_of(case, terms, sid):
    return priced(case, terms, sid)["c"]


def units(case, terms, sid):
    t = closing_terms(case, terms, SUPPLIERS[sid]["standard"])
    years = min(t["contract_months"] / 12 if t["contract_months"] else 1.0, case["buyer"]["horizon_years"])
    return t["volume_per_year"] * years


def sup_value(case, terms, sid):
    return supplier_value(case, terms, sup_est(sid)) * units(case, terms, sid)


def best_c(case, sid, floor_price):
    """C_best: the floor price with every allowed value of the other negotiable terms."""
    rest = case["negotiable"][1:]
    options = [case["term_options"].get(f) or [None] for f in rest]
    return min(c_of(case, {**dict(zip(rest, combo)), "unit_price": floor_price}, sid)
               for combo in itertools.product(*options))


# --------------------------------------------------------------------------------------------
# Specialists: what each lever is worth, computed with the cost function
# --------------------------------------------------------------------------------------------

def specialists(case, sid, standing, proposal, claims):
    """`standing`: the supplier's current terms; `proposal`: the sheet we lean towards."""
    neg = case["negotiable"]
    out = {}

    def lever(name, field, value, text, claim=None, note=""):
        if field not in neg:
            out[name] = {"lever": field, "value_for_us_eur": 0.0, "value_for_supplier_eur": 0.0,
                         "proposal": None, "claim": claim, "note": note or f"{field} is fixed in this case"}
            return
        moved = {**standing, field: value}
        us = c_of(case, standing, sid) - c_of(case, moved, sid)
        them = sup_value(case, moved, sid) - sup_value(case, standing, sid)
        out[name] = {"lever": field, "value_for_us_eur": round(us, 2), "value_for_supplier_eur": round(them, 2),
                     "proposal": text, "claim": claim, "note": note}

    pick = {c["kind"]: c["text"] for c in claims}
    p = proposal["unit_price"]
    lever("price", "unit_price", p, f"unit_price {p:.2f}", pick.get("price"),
          "anchor below the floor estimate, concede in shrinking steps")
    if "payment_days" in neg:
        pd = proposal.get("payment_days", standing.get("payment_days"))
        lever("cash", "payment_days", pd, f"payment_days {pd}", pick.get("cash"),
              "trade faster payment only against price" if pd < 45 else "longer terms are cheap money for us")
    else:
        lever("cash", "payment_days", None, "")
    if "incoterm" in neg:
        lever("logistics", "incoterm", "DAP", "incoterm DAP", None, "supplier carries freight; costs it the leg")
    else:
        out["logistics"] = {"lever": "incoterm", "value_for_us_eur": 0.0, "value_for_supplier_eur": 0.0,
                            "proposal": None, "claim": None,
                            "note": f"incoterm fixed at {case['fixed_terms'].get('incoterm')}"}
    out["quality"] = {"lever": "ppm_commitment", "value_for_us_eur": 0.0, "value_for_supplier_eur": 0.0,
                      "proposal": None, "claim": pick.get("quality"),
                      "note": "not negotiable here: use the scorecard as an argument"}
    if "contract_months" in neg:
        lever("volume", "contract_months", 24, "contract_months 24", None,
              "commit the full horizon: covers need, worth a lot to a supplier that wants security")
    else:
        out["volume"] = {"lever": "volume_per_year", "value_for_us_eur": 0.0, "value_for_supplier_eur": 0.0,
                         "proposal": None, "claim": None, "note": "volume fixed by the case"}
    if "effective_date" in neg:
        ed = proposal.get("effective_date", standing.get("effective_date"))
        lever("index", "effective_date", ed, f"effective_date {ed}", pick.get("index"),
              "a later start keeps the current price for the first months")
    else:
        out["index"] = {"lever": "index_clause", "value_for_us_eur": 0.0, "value_for_supplier_eur": 0.0,
                        "proposal": None, "claim": pick.get("index"),
                        "note": "no index path expected: a clause only adds index risk"}
    rel = priced(case, {**standing, **proposal}, sid)["breakdown"]["relationship"]
    out["relationship"] = {"lever": "relationship", "value_for_us_eur": round(-rel, 2),
                           "value_for_supplier_eur": 0.0, "proposal": None, "claim": pick.get("relationship"),
                           "note": ("margin below sustainable costs us this much"
                                    if rel > 0 else "supplier margin stays healthy at this proposal")}
    return out


# --------------------------------------------------------------------------------------------
# Event writer with realistic pacing
# --------------------------------------------------------------------------------------------

class Clock:
    def __init__(self, start, rng):
        self.t, self.rng = start, rng

    def tick(self, lo, hi):
        self.t += timedelta(seconds=self.rng.uniform(lo, hi))
        return self.t


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}" + TZ


class CaseWriter:
    def __init__(self, run, case, start, seed, rich=True):
        self.run, self.case, self.rich = run, case, rich
        self.rng = random.Random(seed)
        self.start = start
        self.events = []  # (ts, order, type, fields)
        self.session_id = f"ses_{seed:04x}{self.rng.randrange(16**6):06x}"
        self.n = 0

    def emit(self, t, type_, **fields):
        self.events.append((t, self.n, type_, fields))
        self.n += 1

    def write(self, folder):
        rows = sorted(self.events, key=lambda e: (e[0], e[1]))
        path = folder / f"{self.case['case_id'].replace(':', '_')}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for seq, (t, _, type_, fields) in enumerate(rows):
                line = {"ts": iso(t), "seq": seq, "run_id": self.run["run_id"], "agent": self.run["agent"],
                        "case_id": self.case["case_id"], "session_id": self.session_id, "type": type_, **fields}
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        return rows[-1][0]


def play_case(run, case, start, seed, threads, outcome, rich=True, extras=()):
    """threads: {sid: Thread spec}; outcome: dict for the result event.

    Thread spec: {"opening": terms, "opening_body": str, "rounds": [round spec]}
    Round spec: {"candidates": [...], "choose": idx|None, "kind": send|accept|walk_away, "reason": str,
                 "subject", "body", "claims", "reply": {...} | None}
    """
    w = CaseWriter(run, case, start, seed, rich)
    clock = Clock(start, w.rng)
    t0 = clock.tick(0.4, 0.9)
    opening = {}
    for sid, th in threads.items():
        std = {k: v for k, v in SUPPLIERS[sid]["standard"].items()}
        opening[sid] = {"offer_id": f"offer:{sid[4:]}-0", "supplier_name": SUPPLIERS[sid]["name"],
                        "priced": priced(case, th["opening"], sid), "standard_terms": std,
                        "body": th["opening_body"]}
    alt = case["buyer"]["alternative"]
    c_alt = c_of(case, alt["terms"], case["suppliers"][0]) if alt.get("terms", {}).get("unit_price") else None
    w.emit(t0, "case_opened", case=case, opening=opening, c_alt=c_alt)

    ends = []
    standing_last = {}
    for k, (sid, th) in enumerate(threads.items()):
        c = Clock(t0 + timedelta(seconds=0.2 * k), w.rng)
        if rich:
            d = DOSSIERS[sid]
            w.emit(c.tick(2.0, 4.5), "dossier", supplier_id=sid, supplier_name=SUPPLIERS[sid]["name"],
                   summary=d["summary"], persona=d["persona"], floor_estimate=d["floor_estimate"],
                   floor_source=d["floor_source"], facts=d["facts"])
        standing = dict(th["opening"])
        offer_no = 0
        for r, rd in enumerate(th["rounds"], start=1):
            if rd.get("wait"):
                c.tick(rd["wait"], rd["wait"] + 2)
            cands = rd.get("candidates", [])
            chosen = cands[rd["choose"]] if cands and rd.get("choose") is not None else None
            t_think = c.t
            if rich and rd["kind"] == "send":
                lean = chosen["sheets"][0] if chosen else standing
                w.emit(c.tick(3.0, 6.5), "specialists", round=r, supplier_id=sid,
                       outputs=specialists(case, sid, standing, lean, rd.get("claim_pool", [])))
                w.emit(c.tick(5.0, 10.0), "plan", round=r, supplier_id=sid,
                       target=priced(case, rd["target"], sid), walk_away_c=rd["walk_away_c"],
                       candidates=[{"id": cd["id"], "label": cd["label"],
                                    "sheets": [priced(case, s, sid) for s in cd["sheets"]],
                                    "claims": cd["claims"], "rationale": cd["rationale"]} for cd in cands])
            elif rich and rd["kind"] != "send":
                w.emit(c.tick(2.0, 4.0), "specialists", round=r, supplier_id=sid,
                       outputs=specialists(case, sid, standing, standing, []))
            t_dec = c.tick(2.0, 5.0)
            w.emit(t_dec, "decision", round=r, supplier_id=sid, kind=rd["kind"],
                   candidate_id=chosen["id"] if chosen else None, reason=rd["reason"],
                   decided_in_s=round((t_dec - t_think).total_seconds(), 1))
            if rd["kind"] == "send":
                sheets = rd.get("sheets") or (chosen["sheets"] if chosen else [])
                refs = sorted({cl["id"].split(" ")[0] for cl in (chosen["claims"] if chosen else rd.get("claims", []))})
                w.emit(c.tick(0.2, 0.6), "message_sent", round=r, supplier_id=sid, subject=rd["subject"],
                       body=rd["body"], sheets=[priced(case, s, sid) for s in sheets], refs=refs)
            for err in rd.get("errors", []):
                w.emit(c.tick(1.0, 3.0), "error", supplier_id=sid, status=err["status"], detail=err["detail"])
            rp = rd.get("reply")
            if rp:
                latency = w.rng.uniform(*rp.get("latency", (6.0, 16.0)))
                c.t += timedelta(seconds=latency)
                if rp.get("terms") is not None:
                    offer_no += 1
                    standing = dict(rp["terms"])
                st = {"offer_id": f"offer:{sid[4:]}-{offer_no}", "priced": priced(case, standing, sid)} \
                    if rp["status"] not in ("walked_away", "no_bid") else None
                w.emit(c.t, "reply", round=r, supplier_id=sid, **{"from": SUPPLIERS[sid]["role"]},
                       status=rp["status"], subject=f"Re: {rd.get('subject') or th['subject']}", body=rp["body"],
                       standing=st, claim_results=rp.get("claim_results", []), missing_fields=[],
                       signals={"reply_delay_days": rp.get("delay_days", 2), "validity_days": 30},
                       attachments=rp.get("attachments", []), latency_s=round(latency, 1))
        standing_last[sid] = (standing, offer_no)
        ends.append(c.t)

    t_end = max(ends) + timedelta(seconds=w.rng.uniform(0.5, 1.5))
    # the result, as the arena returns it
    c_open = min(o["priced"]["c"] for o in opening.values())
    sid = outcome.get("supplier_id")
    c_best = min(best_c(case, s, outcome["floors"][s]) for s in threads)
    if c_alt is not None:
        c_best = min(c_best, c_alt)
    res = {"deal": bool(sid), "supplier_id": sid, "offer_id": None, "terms": None, "c_open": c_open,
           "c_deal": None, "c_alt": c_alt, "c_best": c_best,
           "score": round(score(c_open, c_alt, c_best), 4) if c_alt else 0.0, "cost_breakdown": None,
           "end_reason": outcome["end_reason"], "replay_url": None, "must_haves_ok": None}
    if sid:
        terms, offer_no = standing_last[sid]
        full = closing_terms(case, terms, SUPPLIERS[sid]["standard"])
        p = priced(case, terms, sid)
        ok = must_haves_ok(case, full)
        res.update(offer_id=f"offer:{sid[4:]}-{offer_no}", terms=full, c_deal=p["c"], cost_breakdown=p["breakdown"],
                   must_haves_ok=ok, score=round(score(c_open, p["c"], c_best), 4) if ok else 0.0)
    w.emit(t_end, "result", **res)
    for extra in extras:
        w.emit(t_end + timedelta(seconds=1), extra["type"], **{k: v for k, v in extra.items() if k != "type"})
    return w, res


# --------------------------------------------------------------------------------------------
# Scripts: what happened in each fixture negotiation
# --------------------------------------------------------------------------------------------

SIGN = "Best regards\nMaria Huber\nStrategic Purchasing, Hollerau Pumpenwerke GmbH"


def mail(*paras):
    return "\n\n".join(paras)


CL_D351 = {"id": "idx:PPI-D351@2026-08", "text": "Electricity producer prices changed -3.7 % from 2025-08 to 2026-08 (idx:PPI-D351@2025-08, idx:PPI-D351@2026-08).", "kind": "index"}
CL_SC110 = {"id": "sc:70110@2026Q3", "text": "Your on-time delivery over the last 12 months was 85.2 % (sc:70110@2026Q3), against 95 % agreed.", "kind": "quality"}
CL_COST = {"id": "cost:310010", "text": "Our should-cost estimate for the HN 50-200 is EUR 132.64 (cost:310010).", "kind": "price"}
CL_C2451 = {"id": "idx:PPI-C2451@2026-08", "text": "Iron casting prices rose only 1.8 % from 2025-08 to 2026-08 (idx:PPI-C2451@2025-08, idx:PPI-C2451@2026-08).", "kind": "index"}
CL_C241_WRONG = {"id": "idx:PPI-C241@2026-08", "text": "Basic iron and steel prices rose 4.1 % from 2025-08 to 2026-08 (idx:PPI-C241@2025-08, idx:PPI-C241@2026-08).", "kind": "index"}
CL_CASH = {"id": "doc:20260902-70110-M2", "text": "You asked us to pay within 10 days (doc:20260902-70110-M2) - we can do 14.", "kind": "cash"}


def claims(*cs):
    return [{"id": c["id"], "text": c["text"]} for c in cs]


def p01_threads_A():
    sid = "sup:70110"
    T = lambda p, d, e: {"unit_price": p, "payment_days": d, "effective_date": e}  # noqa: E731
    pool = [CL_D351, CL_SC110, CL_COST, CL_CASH]
    rounds = [
        {"kind": "send", "choose": 0, "claim_pool": pool,
         "target": T(131.8, 14, "2027-04-01"), "walk_away_c": None,
         "candidates": [
             {"id": "r1-a", "label": "Index rebuttal + April start", "sheets": [T(129.9, 60, "2027-04-01"), T(128.5, 14, "2027-04-01")],
              "claims": claims(CL_D351, CL_SC110), "rationale": "Energy fell, his letter cites it: disarm the energy argument first and anchor low. Two sheets let him show what he values: price or cash."},
             {"id": "r1-b", "label": "Cash for price", "sheets": [T(131.0, 10, "2027-01-01")],
              "claims": claims(CL_CASH), "rationale": "He asked for 10-day payment. Offer it early - but it gives away our strongest trade before he moves."},
             {"id": "r1-c", "label": "Hold the current price", "sheets": [T(126.53, 60, "2027-04-01")],
              "claims": claims(CL_D351), "rationale": "0 % is not credible against should-cost 132.64: risks his margin and our relationship charge."}],
         "reason": "Open with r1-a. The verified energy figure takes away half his letter's argument, and the 14-day sheet tells him we heard his cash problem without spending it yet. Anchor at 129.90/128.50, well under his 138.55 but above the 126.53 he has today.",
         "subject": "HN 50-200 volute casings - your letter of 11 September",
         "body": mail("Dear Mr Brandlhuber,",
                      "thank you for your letter of 11 September and for the open conversation during your visit. We value the partnership - 2022 is not forgotten here.",
                      "We cannot follow +9.5 % from November, though. Electricity producer prices changed -3.7 % from 2025-08 to 2026-08 (idx:PPI-D351@2025-08, idx:PPI-D351@2026-08). And your on-time delivery over the last 12 months was 85.2 % (sc:70110@2026Q3), against 95 % agreed.",
                      "We propose two packages below: EUR 129.90 at our 60-day terms, or EUR 128.50 if we pay within 14 days - both from 1 April 2027. Could you also send us a cost breakdown?",
                      SIGN),
         "reply": {"status": "open", "terms": T(137.2, 30, "2027-01-01"),
                   "claim_results": [{"index": 0, "result": "verified", "ref": "idx:PPI-D351@2026-08"},
                                     {"index": 1, "result": "verified", "ref": "sc:70110@2026Q3"}],
                   "attachments": [{"attachment_id": "att:70110-1-quote", "name": "Angebot_HN50-200.pdf", "type": "pdf"}],
                   "body": mail("Guten Tag Frau Huber,",
                                "thank you for your quick answer. We checked the electricity figure you cited; it holds and we took it into account. The delivery figure is also correct - the summer shutdown hurt us, we are working on it.",
                                "But energy is only part of it. LCI-C rose 2.7 % in twelve months and is 32 % of our cost. PPI-C241 rose 6.5 % and is 26 %. That remains.",
                                "We can offer EUR 137.20 per unit, 30 days net, valid from 1 January 2027.",
                                "Viele Grüße aus der Gießerei\nJosef Brandlhuber\nGießerei Brandlhuber GmbH & Co. KG")}},
        {"kind": "send", "choose": 0, "claim_pool": pool,
         "target": T(132.2, 14, "2027-04-01"), "walk_away_c": None,
         "candidates": [
             {"id": "r2-a", "label": "Should-cost + 14 days", "sheets": [T(131.5, 14, "2027-04-01")],
              "claims": claims(CL_COST, CL_C2451), "rationale": "He moved 1.35 for two verified facts. Show we know his cost; trade the 14 days he wants for April and price."},
             {"id": "r2-b", "label": "Split the difference", "sheets": [T(133.5, 30, "2027-01-01")],
              "claims": [], "rationale": "Fast close, but leaves the April start and ~€9k on the table."}],
         "reason": "r2-a. He conceded on energy and kept wages and steel; the should-cost of 132.64 is the honest anchor and the 14-day term is exactly what doc M2 asked for. I expect him near 135 next.",
         "subject": "HN 50-200 volute casings - your letter of 11 September",
         "body": mail("Dear Mr Brandlhuber,",
                      "thank you - we understand that wages and steel are real for you.",
                      "Our should-cost estimate for the HN 50-200 is EUR 132.64 (cost:310010). Iron casting prices rose only 1.8 % from 2025-08 to 2026-08 (idx:PPI-C2451@2025-08, idx:PPI-C2451@2026-08).",
                      "You asked us to pay faster. We can pay within 14 days at EUR 131.50 from 1 April 2027. That brings cash to you every two weeks instead of every month.",
                      SIGN),
         "reply": {"status": "open", "terms": T(135.4, 14, "2027-01-01"),
                   "claim_results": [{"index": 0, "result": "verified", "ref": "cost:310010"},
                                     {"index": 1, "result": "irrelevant", "ref": "idx:PPI-C2451@2026-08"}],
                   "body": mail("Guten Tag Frau Huber,",
                                "your cost estimate is close to our own, I admit - my office manager says we are at the limit. The iron casting index is not our cost: we melt scrap and pig iron.",
                                "14 days helps us a lot. For 14 days we can go to EUR 135.40, from 1 January 2027.",
                                "Viele Grüße\nJosef Brandlhuber")}},
        {"kind": "send", "choose": 0, "claim_pool": pool,
         "target": T(132.6, 14, "2027-04-01"), "walk_away_c": None,
         "candidates": [
             {"id": "r3-a", "label": "Push the April start", "sheets": [T(132.4, 14, "2027-04-01")],
              "claims": claims(CL_D351), "rationale": "April is worth ~€12k to us and little to him at 14 days. Concede 0.90 on price to get it."},
             {"id": "r3-b", "label": "Accept 135.40", "sheets": [], "claims": [],
              "rationale": "Score ~0.42. Too early: he is still moving in steps above 1 €."}],
         "reason": "r3-a. The effective date is the cheapest lever left: every month at 126.53 saves us ~€5k. Re-citing the energy index is a duplicate - I keep it in the text for his office manager, not for the arena.",
         "subject": "HN 50-200 volute casings - your letter of 11 September",
         "body": mail("Dear Mr Brandlhuber,",
                      "we are moving towards each other. We go to EUR 132.40 with payment in 14 days.",
                      "What we need in return is time: our budget for 2027 is set, and a new price from 1 April 2027 fits it. Electricity prices changed -3.7 % from 2025-08 to 2026-08 (idx:PPI-D351@2025-08, idx:PPI-D351@2026-08), which also helps you over the winter.",
                      SIGN),
         "reply": {"status": "open", "terms": T(134.1, 14, "2027-04-01"),
                   "claim_results": [{"index": 0, "result": "duplicate", "ref": "idx:PPI-D351@2026-08"}],
                   "body": mail("Guten Tag Frau Huber,",
                                "April is hard for us, but I see that you are serious about the 14 days. EUR 134.10, 14 days net, from 1 April 2027.",
                                "Viele Grüße\nJosef Brandlhuber")}},
        {"kind": "send", "choose": 0, "claim_pool": pool,
         "target": T(132.9, 14, "2027-04-01"), "walk_away_c": None,
         "candidates": [
             {"id": "r4-a", "label": "Meet near the middle", "sheets": [T(132.9, 14, "2027-04-01")],
              "claims": [], "rationale": "His steps shrink (1.35 → 1.80 → 1.30). One more push, framed as partnership."},
             {"id": "r4-b", "label": "Accept 134.10", "sheets": [], "claims": [], "rationale": "Score ~0.55."}],
         "reason": "r4-a. His concessions are getting smaller and the relationship charge starts to bite below ~132.5 (margin under 6 %). 132.90 is my last ask; anything at or under 133.50 I accept.",
         "subject": "HN 50-200 volute casings - your letter of 11 September",
         "body": mail("Dear Mr Brandlhuber,",
                      "thank you for April. Let us close this today: EUR 132.90, 14 days net, from 1 April 2027 - your margin stays healthy and you get our cash every two weeks.",
                      SIGN),
         "reply": {"status": "final_offer", "terms": T(133.4, 14, "2027-04-01"),
                   "attachments": [{"attachment_id": "att:70110-4-quote", "name": "Angebot_HN50-200_final.pdf", "type": "pdf"}],
                   "body": mail("Guten Tag Frau Huber,",
                                "I have talked to my office manager. EUR 133.40, 14 days net, from 1 April 2027 - this is our last word. Below that I lose money on every casing.",
                                "Viele Grüße\nJosef Brandlhuber")}},
        {"kind": "accept", "reason": "Accept the final offer 133.40 / 14 d / April. It is within 1.8 € of my floor estimate, his margin stays above the sustainable 6 %, and a push past a final_offer risks a walk-away for ~€3.6k."},
    ]
    return {sid: {"opening": T(138.55, 30, "2026-11-01"), "subject": "Price adjustment from 01 November 2026",
                  "opening_body": mail("Dear Sir or Madam,",
                                       "as announced in our letter of 11 September, we adjust our price for the volute casing HN 50-200 (part:310010) by 9.5 % from 1 November 2026: from EUR 126.53 to EUR 138.55 per pc. Our quote is attached.",
                                       "Owing to sustained increases in energy, raw material and wage costs we have no other choice.",
                                       "Mit freundlichen Grüßen\nGießerei Brandlhuber GmbH & Co. KG"),
                  "rounds": rounds}}


def p01_threads_C():
    sid = "sup:70110"
    T = lambda p, d, e: {"unit_price": p, "payment_days": d, "effective_date": e}  # noqa: E731
    base = p01_threads_A()[sid]
    rounds = [
        {"kind": "send", "sheets": [T(130.5, 60, "2027-01-01")], "claims": claims(CL_D351, CL_C241_WRONG),
         "reason": "Price increase case. Counter at 130.50 with two index facts; keep 60 days.",
         "subject": "HN 50-200 volute casings - your letter of 11 September",
         "body": mail("Dear Sir or Madam,",
                      "we cannot accept +9.5 %. Electricity producer prices changed -3.7 % from 2025-08 to 2026-08 (idx:PPI-D351@2025-08, idx:PPI-D351@2026-08). Basic iron and steel prices rose 4.1 % from 2025-08 to 2026-08 (idx:PPI-C241@2025-08, idx:PPI-C241@2026-08).",
                      "We offer EUR 130.50 at 60 days from 1 January 2027.", SIGN),
         "reply": {"status": "open", "terms": T(137.8, 30, "2027-01-01"),
                   "claim_results": [{"index": 0, "result": "verified", "ref": "idx:PPI-D351@2026-08"},
                                     {"index": 1, "result": "contradicted", "ref": "idx:PPI-C241@2026-08"}],
                   "body": mail("Guten Tag,",
                                "the electricity figure is right. Your steel figure is not: PPI-C241 rose 6.5 %, not 4.1 %. Please check your numbers before you write to us.",
                                "EUR 137.80, 30 days net, from 1 January 2027.", "Gießerei Brandlhuber")}},
        {"kind": "send", "sheets": [T(133.0, 30, "2027-01-01")], "claims": [],
         "reason": "Supplier is annoyed by the wrong figure. Move up to 133.00 to rebuild goodwill.",
         "subject": "HN 50-200 volute casings - your letter of 11 September",
         "body": mail("Dear Sir or Madam,", "apologies for the steel figure. We can go to EUR 133.00 at 30 days from 1 January 2027.", SIGN),
         "reply": {"status": "final_offer", "terms": T(135.6, 30, "2027-01-01"),
                   "body": mail("Guten Tag,", "EUR 135.60, 30 days, from 1 January 2027. That is our final offer.", "Gießerei Brandlhuber")}},
        {"kind": "accept", "reason": "Final offer received. 135.60 is 2.95 below the opening; accept to avoid a walk-away."},
    ]
    return {sid: {**base, "rounds": rounds}}


def p01_threads_naive():
    sid = "sup:70110"
    T = lambda p, d, e: {"unit_price": p, "payment_days": d, "effective_date": e}  # noqa: E731
    base = p01_threads_A()[sid]
    rounds = [
        {"kind": "send", "sheets": [T(131.67, 60, "2026-11-01")], "reason": "counter at 95 % of the standing price",
         "subject": "Offer", "body": "Dear supplier,\n\nwe offer EUR 131.67.\n\nBest regards\nHollerau Pumpenwerke, Purchasing",
         "reply": {"status": "open", "terms": T(137.9, 30, "2026-11-01"),
                   "body": "Guten Tag,\n\nEUR 137.90, 30 days, from 1 November 2026.\n\nGießerei Brandlhuber"}},
        {"kind": "send", "sheets": [T(134.79, 60, "2026-11-01")], "reason": "split the difference",
         "subject": "Offer", "body": "Dear supplier,\n\nwe offer EUR 134.79.\n\nBest regards\nHollerau Pumpenwerke, Purchasing",
         "reply": {"status": "final_offer", "terms": T(136.9, 30, "2026-11-01"),
                   "body": "Guten Tag,\n\nEUR 136.90 is our final offer.\n\nGießerei Brandlhuber"}},
        {"kind": "accept", "reason": "final offer"},
    ]
    return {sid: {**base, "rounds": rounds}}


def p13_threads(agent):
    sid = "sup:70230"
    T = lambda p, d, e: {"unit_price": p, "payment_days": d, "effective_date": e}  # noqa: E731
    CL_NOTICE = {"id": "doc:20260927-70230-P13", "text": "Your letter (doc:20260927-70230-P13) gives 35 days' notice; our contract (ctr:4600070230) requires 90 days.", "kind": "price"}
    CL_QUOTE = {"id": "quote:7200013", "text": "We hold a quote at EUR 17.87 (quote:7200013).", "kind": "price"}
    CL_SC = {"id": "sc:70230@2026Q3", "text": "Your on-time delivery was 82.1 % over the last 12 months (sc:70230@2026Q3).", "kind": "quality"}
    pool = [CL_NOTICE, CL_SC]
    subj = "Coupling hub - your letter of 27 September"
    r1 = {"kind": "send", "choose": 0, "claim_pool": pool, "target": T(16.55, 30, "2027-04-01"), "walk_away_c": 254500.0,
          "candidates": [
              {"id": "r1-a", "label": "Contract notice: hold 16.30", "sheets": [T(16.3, 30, "2027-01-01")],
               "claims": claims(CL_NOTICE, CL_SC), "rationale": "The letter breaks the 90-day notice: the increase cannot apply before 2027. Hold the price, ask him to withdraw."},
              {"id": "r1-b", "label": "Accept timing, fight price", "sheets": [T(16.6, 30, "2027-01-01")],
               "claims": claims(CL_NOTICE), "rationale": "Softer: +1.8 % from January."}],
          "reason": "r1-a. The notice argument is verified fact, not opinion; it costs him nothing to accept January. Our alternative (keep the contract to June, then fallback) is worth ~€254.5k, so I need to beat that.",
          "subject": subj,
          "body": mail("Dear Sir or Madam,",
                       "thank you for your letter. Your letter (doc:20260927-70230-P13) gives 35 days' notice; our contract (ctr:4600070230) requires 90 days. The increase cannot apply from 1 November.",
                       "Your on-time delivery was 82.1 % over the last 12 months (sc:70230@2026Q3). We see no basis for 7 %. We ask you to keep EUR 16.30 for 2027.", SIGN),
          "reply": {"status": "open", "terms": T(17.2, 30, "2027-01-01"),
                    "claim_results": [{"index": 0, "result": "verified", "ref": "doc:20260927-70230-P13"},
                                      {"index": 1, "result": "verified", "ref": "sc:70230@2026Q3"}],
                    "body": mail("Dear Ms Huber,",
                                 "you are right about the notice period; we move the date to 1 January 2027. Our wages rose 6 % in April - the price itself has to change.",
                                 "EUR 17.20, 30 days net, from 1 January 2027.",
                                 "Kind regards\nThomas Reindl, Managing Director Sales\nPräzisionsteile Lindlbauer KG")}}
    if agent == "A":
        rounds = [r1,
                  {"kind": "send", "choose": 0, "claim_pool": pool, "target": T(16.55, 30, "2027-04-01"), "walk_away_c": 254500.0,
                   "candidates": [{"id": "r2-a", "label": "Hold firm at 16.30", "sheets": [T(16.3, 30, "2027-04-01")], "claims": claims(CL_QUOTE),
                                   "rationale": "He conceded the date immediately: he is weaker than he looks. Repeat 0 %."},
                                  {"id": "r2-b", "label": "Move to 16.60", "sheets": [T(16.6, 30, "2027-04-01")], "claims": [],
                                   "rationale": "Shows movement; likely lands at ~16.90."}],
                   "reason": "r2-a. He gave the date at once, so the price has room too. Hold 16.30 and cite the rival quote to show we have options.",
                   "subject": subj,
                   "body": mail("Dear Mr Reindl,", "thank you for moving the date. We hold a quote at EUR 17.87 (quote:7200013), but we prefer to stay with you at EUR 16.30 from 1 April 2027.", SIGN),
                   "reply": {"status": "final_offer", "terms": T(16.95, 30, "2027-01-01"),
                             "claim_results": [{"index": 0, "result": "verified", "ref": "quote:7200013"}],
                             "body": mail("Dear Ms Huber,", "your quote is higher than our price - I am not sure it helps your case. EUR 16.95 from 1 January 2027 is my final offer. I cannot go further without my board.", "Kind regards\nThomas Reindl")}},
                  {"kind": "send", "choose": 0, "claim_pool": pool, "target": T(16.55, 30, "2027-04-01"), "walk_away_c": 254500.0,
                   "candidates": [{"id": "r3-a", "label": "One more push: 16.50", "sheets": [T(16.5, 30, "2027-04-01")], "claims": [],
                                   "rationale": "Final offers are often not final. Ask once more."},
                                  {"id": "r3-b", "label": "Accept 16.95", "sheets": [], "claims": [], "rationale": "Score ~0.55, beats the alternative."}],
                   "reason": "r3-a. 16.95 is still above my 16.85 floor estimate; one more ask at 16.50 with April. (Risk: he flagged the board.)",
                   "subject": subj,
                   "body": mail("Dear Mr Reindl,", "we are close. EUR 16.50 from 1 April 2027 and we sign today.", SIGN),
                   "reply": {"status": "walked_away", "terms": None,
                             "body": mail("Dear Ms Huber,", "I told you 16.95 was final. We will supply under the current contract until it ends and will not renew it.", "Kind regards\nThomas Reindl")}}]
        return {sid: {"opening": T(17.44, 30, "2026-11-01"), "subject": "Price adjustment from 01 November 2026",
                      "opening_body": mail("Dear Sir or Madam,", "following our letter of 27 September we confirm the new price for the coupling hub (part:320060): EUR 17.44 per pc from 1 November 2026.", "Kind regards\nPräzisionsteile Lindlbauer KG"),
                      "rounds": rounds}}
    rounds = [
        {**r1, "choose": None, "sheets": [T(16.3, 30, "2027-01-01")], "claims": claims(CL_NOTICE, CL_SC),
         "reason": "Letter gives 35 days' notice against 90 in the contract. Cite both, hold 16.30."},
        {"kind": "send", "sheets": [T(16.7, 30, "2027-04-01")], "claims": [], "reason": "Date conceded. Move to 16.70 and ask for April.",
         "subject": subj, "body": mail("Dear Mr Reindl,", "thank you. We can go to EUR 16.70 if the new price starts on 1 April 2027.", SIGN),
         "reply": {"status": "final_offer", "terms": T(16.9, 30, "2027-04-01"),
                   "body": mail("Dear Ms Huber,", "April is possible at EUR 16.90. That is my final offer.", "Kind regards\nThomas Reindl")}},
        {"kind": "accept", "reason": "Final offer 16.90 from April beats the alternative by ~€12k; the supplier flagged its limit. Accept."},
    ]
    return {sid: {"opening": T(17.44, 30, "2026-11-01"), "subject": "Price adjustment from 01 November 2026",
                  "opening_body": mail("Dear Sir or Madam,", "following our letter of 27 September we confirm the new price for the coupling hub (part:320060): EUR 17.44 per pc from 1 November 2026.", "Kind regards\nPräzisionsteile Lindlbauer KG"),
                  "rounds": rounds}}


def p20_threads(agent):
    T = lambda p, d, m, i: {"unit_price": p, "payment_days": d, "contract_months": m, "incoterm": i}  # noqa: E731
    subj = "RFQ 6000000306 - volute casing HX 80-200"
    CL_SC140 = {"id": "sc:70140@2026Q3", "text": "Your defect rate over the last 12 months was 2376 ppm (sc:70140@2026Q3).", "kind": "quality"}
    CL_SC120 = {"id": "sc:70120@2026Q3", "text": "Your on-time delivery over the last 12 months was 74.5 % (sc:70120@2026Q3).", "kind": "quality"}
    CL_IDX = {"id": "idx:PPI-C2451@2026-08", "text": "Iron casting prices rose 1.8 % from 2025-08 to 2026-08 (idx:PPI-C2451@2025-08, idx:PPI-C2451@2026-08).", "kind": "index"}
    CL_RIVAL_W = {"id": "offer:70130-1", "text": "We hold an offer at EUR 174.20 (offer:70130-1).", "kind": "price"}
    CL_RIVAL_V = {"id": "offer:70120-2", "text": "We hold an offer at EUR 176.90 (offer:70120-2).", "kind": "price"}

    v = {"opening": T(184.5, 45, 12, "FCA"), "subject": subj,
         "opening_body": mail("Dear Ms Huber,", "thank you for your enquiry. For the volute casing HX 80-200 in EN-GJS-500-7 we quote EUR 184.50 per pc FCA Velkenreith, 45 days net, tooling EUR 16,000, lead time 49 days. Our quote is attached.", "Mit freundlichen Grüßen\nEisengießerei Velkenreith GmbH")}
    wi = {"opening": T(179.8, 30, 12, "FCA"), "subject": subj,
          "opening_body": mail("Dear Ms Huber,", "many thanks for thinking of us for the new HX series. We quote EUR 179.80 per pc FCA, 30 days net, tooling EUR 18,500, 45 days lead time.", "We would be glad to become a long-term partner for the HX series.", "Herzliche Grüße\nGießerei Wimbacher GmbH")}
    k = {"opening": T(168.9, 60, 12, "FCA"), "subject": subj,
         "opening_body": mail("Dear Madam,", "we are pleased to quote EUR 168.90 per pc FCA Kalwisz, 60 days net, tooling EUR 12,000. Lead time 70 days from order.", "Best regards\nOdlewnia Kalwisz Sp. z o.o.")}

    if agent == "A":
        k["rounds"] = [
            {"kind": "send", "choose": 0, "claim_pool": [CL_SC140], "target": T(162.0, 90, 24, "DAP"), "walk_away_c": None,
             "candidates": [{"id": "k1-a", "label": "Quality discount + 90 days", "sheets": [T(161.5, 90, 24, "DAP")], "claims": claims(CL_SC140),
                             "rationale": "Its 2376 ppm and 70-day lead cost us ~€6.6k: price that in, ask for 90 days and DAP."}],
             "reason": "k1-a. Kalwisz is cheapest on paper but its quality and lead time cost us. Push hard: either it gets truly cheap or it drops out.",
             "subject": subj, "body": mail("Dear Sir or Madam,", "thank you for your quote. Your defect rate over the last 12 months was 2376 ppm (sc:70140@2026Q3) - for a pressure-bearing casing that is a risk we have to price in.", "We could consider EUR 161.50 DAP, 90 days net, for 24 months.", SIGN),
             "reply": {"status": "open", "terms": T(166.5, 60, 24, "FCA"),
                       "claim_results": [{"index": 0, "result": "verified", "ref": "sc:70140@2026Q3"}],
                       "body": mail("Dear Ms Huber,", "we have improved our process since the spring. For 24 months we can offer EUR 166.50 FCA, 60 days net. 90 days are not possible for us.", "Best regards\nOdlewnia Kalwisz")}},
            {"kind": "send", "choose": 0, "claim_pool": [], "target": T(162.0, 90, 24, "DAP"), "walk_away_c": None,
             "candidates": [{"id": "k2-a", "label": "Insist on 90 days DAP", "sheets": [T(163.0, 90, 24, "DAP")], "claims": [],
                             "rationale": "Its C needs to beat Wimbacher by > €8k to justify the quality risk."}],
             "reason": "k2-a. Kalwisz only wins at ~163 DAP with 90 days. Ask for it; if it walks, Wimbacher is the better partner anyway.",
             "subject": subj, "body": mail("Dear Sir or Madam,", "we need EUR 163.00 DAP with 90 days net to award you the HX casing.", SIGN),
             "reply": {"status": "walked_away", "terms": None, "delay_days": 1,
                       "body": mail("Dear Ms Huber,", "under our agreement with our banks we cannot accept 90-day terms or delivery at our cost at this price. We withdraw our quote.", "Best regards\nOdlewnia Kalwisz")}},
        ]
        wi["rounds"] = [
            {"kind": "send", "choose": 0, "claim_pool": [CL_IDX], "target": T(170.5, 60, 24, "DAP"), "walk_away_c": None,
             "candidates": [{"id": "w1-a", "label": "24 months for DAP + price", "sheets": [T(169.0, 60, 24, "DAP"), T(171.0, 60, 12, "FCA")], "claims": claims(CL_IDX),
                             "rationale": "Volume security is worth most to an owner who wants to sell: offer the full 2 years, ask for DAP and 60 days."}],
             "reason": "w1-a. The dossier says the 24-month book matters more than price to Wimbacher. Offer it as the headline, price DAP in.",
             "subject": subj, "body": mail("Dear Mr Wimbacher,", "thank you for your quote - we would like to build the HX series with a partner for the long run.", "Iron casting prices rose 1.8 % from 2025-08 to 2026-08 (idx:PPI-C2451@2025-08, idx:PPI-C2451@2026-08), so we expect prices close to today's HN level.", "Two options: EUR 169.00 DAP, 60 days, for 24 months - or EUR 171.00 FCA for 12 months.", SIGN),
             "reply": {"status": "open", "terms": T(174.2, 60, 24, "DAP"),
                       "claim_results": [{"index": 0, "result": "verified", "ref": "idx:PPI-C2451@2026-08"}],
                       "body": mail("Dear Ms Huber,", "a 24-month agreement is very welcome. We deliver to you with our own trucks anyway, so DAP is fine. EUR 174.20 DAP, 60 days, 24 months.", "Herzliche Grüße\nAnton Wimbacher")}},
            {"kind": "send", "choose": 0, "claim_pool": [CL_RIVAL_V], "target": T(171.0, 60, 24, "DAP"), "walk_away_c": None, "wait": 18,
             "candidates": [{"id": "w2-a", "label": "Cite Velkenreith", "sheets": [T(170.5, 60, 24, "DAP")], "claims": claims(CL_RIVAL_V),
                             "rationale": "Velkenreith is at 176.90 FCA. Showing it tells Wimbacher it leads but not by much."}],
             "reason": "w2-a. Wimbacher is leading. Cite the rival to keep pressure without threatening.",
             "subject": subj, "body": mail("Dear Mr Wimbacher,", "you are our preferred partner. We hold an offer at EUR 176.90 (offer:70120-2) - FCA, so close to yours. EUR 170.50 DAP and we award you the HX casing for 24 months.", SIGN),
             "reply": {"status": "open", "terms": T(172.4, 60, 24, "DAP"),
                       "claim_results": [{"index": 0, "result": "verified", "ref": "offer:70120-2"}],
                       "body": mail("Dear Ms Huber,", "thank you for your trust. EUR 172.40 DAP, 60 days, 24 months - and we hold that price for the whole term.", "Herzliche Grüße\nAnton Wimbacher")}},
            {"kind": "send", "choose": 0, "claim_pool": [], "target": T(171.5, 60, 24, "DAP"), "walk_away_c": None, "wait": 10,
             "candidates": [{"id": "w3-a", "label": "Ask for 90 days", "sheets": [T(172.4, 90, 24, "DAP")], "claims": [],
                             "rationale": "Price moves are getting small; payment days are cheap for a healthy foundry."}],
             "reason": "w3-a. Keep the price, ask for 90 days: worth ~€4.8k to us.",
             "subject": subj, "body": mail("Dear Mr Wimbacher,", "we accept EUR 172.40 if you can give us 90 days net.", SIGN),
             "reply": {"status": "final_offer", "terms": T(172.4, 60, 24, "DAP"),
                       "body": mail("Dear Ms Huber,", "90 days we cannot do - EUR 172.40 DAP, 60 days, 24 months is our best offer.", "Herzliche Grüße\nAnton Wimbacher")}},
            {"kind": "accept", "reason": "Accept Wimbacher 172.40 DAP / 60 d / 24 months: lowest C among the live offers (Velkenreith €68k dearer), green scorecard, final offer. Kalwisz is gone - in hindsight its 166.50 FCA was €17k cheaper."},
        ]
        v["rounds"] = [
            {"kind": "send", "choose": 0, "claim_pool": [CL_SC120], "target": T(172.0, 60, 24, "DAP"), "walk_away_c": None,
             "candidates": [{"id": "v1-a", "label": "24 months, ask DAP", "sheets": [T(171.0, 60, 24, "DAP")], "claims": claims(CL_SC120),
                             "rationale": "Velkenreith is solid but slow on delivery: use OTD 74.5 %."}],
             "reason": "v1-a. Keep Velkenreith in the race as the price benchmark for Wimbacher.",
             "subject": subj, "body": mail("Dear Sir or Madam,", "thank you for your quote. Your on-time delivery over the last 12 months was 74.5 % (sc:70120@2026Q3), which worries us for a new series.", "We would consider EUR 171.00 DAP, 60 days, for 24 months.", SIGN),
             "reply": {"status": "open", "terms": T(178.9, 60, 24, "FCA"),
                       "claim_results": [{"index": 0, "result": "verified", "ref": "sc:70120@2026Q3"}],
                       "body": mail("Dear Ms Huber,", "our delivery performance suffered from a furnace rebuild; it is back above 90 % since August. For 24 months: EUR 178.90 FCA, 60 days.", "Mit freundlichen Grüßen\nEisengießerei Velkenreith")}},
            {"kind": "send", "choose": 0, "claim_pool": [CL_RIVAL_W], "target": T(172.0, 60, 24, "DAP"), "walk_away_c": None,
             "candidates": [{"id": "v2-a", "label": "Cite Wimbacher", "sheets": [T(172.0, 60, 24, "DAP")], "claims": claims(CL_RIVAL_W),
                             "rationale": "Velkenreith moves on rival offers (dossier)."}],
             "reason": "v2-a. Cite Wimbacher's 174.20 DAP to get Velkenreith to DAP.",
             "subject": subj, "body": mail("Dear Sir or Madam,", "we hold an offer at EUR 174.20 (offer:70130-1), delivered. Can you match at EUR 172.00 DAP?", SIGN),
             "reply": {"status": "final_offer", "terms": T(176.9, 60, 24, "FCA"),
                       "claim_results": [{"index": 0, "result": "verified", "ref": "offer:70130-1"}],
                       "body": mail("Dear Ms Huber,", "we cannot follow that price. EUR 176.90 FCA, 60 days, 24 months is our final offer.", "Mit freundlichen Grüßen\nEisengießerei Velkenreith")}},
        ]
        return {"sup:70120": v, "sup:70130": wi, "sup:70140": k}

    # agent C: shorter threads, a timeout error, a better Wimbacher deal
    k["rounds"] = [
        {"kind": "send", "sheets": [T(162.0, 60, 24, "FCA")], "claims": [], "reason": "Kalwisz cheapest; ask 162 for 24 months.",
         "subject": subj, "body": mail("Dear Sir or Madam,", "we could award you 24 months at EUR 162.00 FCA, 60 days.", SIGN),
         "reply": {"status": "open", "terms": T(165.9, 60, 24, "FCA"),
                   "body": mail("Dear Ms Huber,", "for 24 months we offer EUR 165.90 FCA, 60 days.", "Best regards\nOdlewnia Kalwisz")}},
        {"kind": "walk_away", "reason": "Kalwisz's C (lead time + 2400 ppm) stays above Wimbacher's; close the thread."},
    ]
    wi["rounds"] = [
        {"kind": "send", "sheets": [T(168.0, 60, 24, "DAP")], "claims": claims(CL_IDX), "reason": "Long contract for DAP and price.",
         "subject": subj, "body": mail("Dear Mr Wimbacher,", "we would like a 24-month partnership. Iron casting prices rose 1.8 % from 2025-08 to 2026-08 (idx:PPI-C2451@2025-08, idx:PPI-C2451@2026-08). EUR 168.00 DAP, 60 days, 24 months?", SIGN),
         "errors": [{"status": 409, "detail": "the supplier has not answered your last message yet"}],
         "reply": {"status": "open", "terms": T(173.0, 60, 24, "DAP"), "latency": (20.0, 28.0),
                   "claim_results": [{"index": 0, "result": "verified", "ref": "idx:PPI-C2451@2026-08"}],
                   "body": mail("Dear Ms Huber,", "24 months - gladly. EUR 173.00 DAP, 60 days.", "Herzliche Grüße\nAnton Wimbacher")}},
        {"kind": "send", "sheets": [T(170.0, 60, 24, "DAP")], "claims": claims(CL_RIVAL_V), "reason": "Cite Velkenreith's 177.50 FCA.", "wait": 6,
         "subject": subj, "body": mail("Dear Mr Wimbacher,", "We hold an offer at EUR 177.50 (offer:70120-1). EUR 170.00 DAP and the HX casing is yours.", SIGN),
         "reply": {"status": "final_offer", "terms": T(171.2, 60, 24, "DAP"),
                   "claim_results": [{"index": 0, "result": "verified", "ref": "offer:70120-1"}],
                   "body": mail("Dear Ms Huber,", "EUR 171.20 DAP, 60 days, 24 months - our final offer.", "Herzliche Grüße\nAnton Wimbacher")}},
        {"kind": "accept", "reason": "Wimbacher final 171.20 DAP is the lowest C; accept."},
    ]
    v["rounds"] = [
        {"kind": "send", "sheets": [T(170.0, 60, 24, "DAP")], "claims": [], "reason": "Benchmark: ask Velkenreith for 170 DAP.",
         "subject": subj, "body": mail("Dear Sir or Madam,", "we could award 24 months at EUR 170.00 DAP, 60 days.", SIGN),
         "reply": {"status": "open", "terms": T(177.5, 60, 24, "FCA"),
                   "body": mail("Dear Ms Huber,", "EUR 177.50 FCA, 60 days, 24 months.", "Eisengießerei Velkenreith")}},
    ]
    return {"sup:70120": v, "sup:70130": wi, "sup:70140": k}


# --------------------------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------------------------

FLOORS = {"case:P01": {"sup:70110": 130.6}, "case:P13": {"sup:70230": 16.6},
          "case:P20": {"sup:70120": 172.0, "sup:70130": 167.0, "sup:70140": 163.0}}

OUTCOMES = {
    ("A", "case:P01"): {"supplier_id": "sup:70110", "end_reason": "accepted"},
    ("A", "case:P13"): {"supplier_id": None, "end_reason": "walked_away"},
    ("A", "case:P20"): {"supplier_id": "sup:70130", "end_reason": "accepted"},
    ("C", "case:P01"): {"supplier_id": "sup:70110", "end_reason": "accepted"},
    ("C", "case:P13"): {"supplier_id": "sup:70230", "end_reason": "accepted"},
    ("C", "case:P20"): {"supplier_id": "sup:70130", "end_reason": "accepted"},
    ("naive", "case:P01"): {"supplier_id": "sup:70110", "end_reason": "accepted"},
}

RUNS = [
    {"run_id": "20261024-101512-naive", "agent": "naive", "agent_version": "f54e549", "set": "sim",
     "notes": "Kit's naive agent, baseline (no dossier, specialists or plan)", "cases": ["case:P01"],
     "start": datetime(2026, 10, 24, 10, 15, 12)},
    {"run_id": "20261024-143005-A", "agent": "A", "agent_version": "a8e53f4", "set": "practice",
     "notes": "Approach A: specialists + LLM strategist. First full practice run.",
     "cases": ["case:P01", "case:P20", "case:P13"], "start": datetime(2026, 10, 24, 14, 30, 5)},
    {"run_id": "20261024-151744-C", "agent": "C", "agent_version": "b71c0de", "set": "practice",
     "notes": "Approach C: agentic LLM with cost tools.",
     "cases": ["case:P01", "case:P20", "case:P13"], "start": datetime(2026, 10, 24, 15, 17, 44)},
]

THREADS = {
    ("A", "case:P01"): p01_threads_A, ("C", "case:P01"): p01_threads_C, ("naive", "case:P01"): p01_threads_naive,
    ("A", "case:P13"): lambda: p13_threads("A"), ("C", "case:P13"): lambda: p13_threads("C"),
    ("A", "case:P20"): lambda: p20_threads("A"), ("C", "case:P20"): lambda: p20_threads("C"),
}
CASES = {"case:P01": P01, "case:P13": P13, "case:P20": P20}


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    for i, spec in enumerate(RUNS):
        folder = OUT / spec["run_id"]
        folder.mkdir(parents=True)
        meta = {k: spec[k] for k in ("run_id", "agent", "agent_version", "set", "cases", "notes")}
        meta["started_at"] = iso(spec["start"])
        t = spec["start"] + timedelta(seconds=1.5)
        end = t
        rich = spec["agent"] == "A"
        for j, cid in enumerate(spec["cases"]):
            # RFQ and price cases run in parallel in a real run; stagger the starts a little
            start = t + timedelta(seconds=0.7 * j)
            extras = []
            if (spec["agent"], cid) == ("A", "case:P01"):
                extras = [{"type": "heartbeat", "note": "unknown event type: readers must ignore it"}]
            w, res = play_case(spec, CASES[cid], start, seed=100 * i + j, threads=THREADS[(spec["agent"], cid)](),
                               outcome={**OUTCOMES[(spec["agent"], cid)], "floors": FLOORS[cid]}, rich=rich,
                               extras=extras)
            end = max(end, w.write(folder))
            print(f"{spec['run_id']:24} {cid:9} deal={res['deal']!s:5} score={res['score']:.3f} "
                  f"c_open={res['c_open']:,.0f} c_deal={res['c_deal'] or 0:,.0f} c_best={res['c_best']:,.0f} "
                  f"c_alt={res['c_alt'] or 0:,.0f}")
        meta["ended_at"] = iso(end + timedelta(seconds=2))
        meta = {"run_id": meta["run_id"], "agent": meta["agent"], "agent_version": meta["agent_version"],
                "set": meta["set"], "started_at": meta["started_at"], "ended_at": meta["ended_at"],
                "cases": meta["cases"], "notes": meta["notes"]}
        (folder / "run.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
