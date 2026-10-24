"""Named agent variants: parameter presets, versioned in git, so every experiment is reproducible.

Add a variant here (never by editing defaults locally), run it with `--variant NAME`, compare with
`python -m csee board`. Promote a winner by moving its values into `Params` defaults on main.
"""

from dataclasses import asdict, fields

from .agent import Params

VARIANTS = {
    "base": {},  # Params defaults: the current champion on main
    # D02 lessons: stop fighting held terms, cite only lower rivals, always offer cash, concede slower
    "v2": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "follow_share": 0.5,
        "hold_above_floor": 0.4,
        "anchor_below_open": 0.18,
    },
    # replay lessons: weigh every offered sheet, cheapest clause when insisted, should-cost x0.95
    # v1 behaviour before `fix` was promoted into base (kept to reproduce the baseline)
    "v1": {"all_sheets": False, "clause_when_insisted": False, "fullcost_discount": 1.0},
    "v3": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "follow_share": 0.5,
        "hold_above_floor": 0.4,
        "anchor_below_open": 0.18,
        "all_sheets": True,
        "clause_when_insisted": True,
        "fullcost_discount": 0.95,
    },
    "v4": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "floor_guard": True,
        "rfq_beat_leader": True,
    },
    "v5": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "follow_share": 0.5,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "hold_on_internal": True,
    },
    "v6": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "hold_on_internal": True,
    },
    "v7": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
    },
    "v8": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "generic_trades": True,
        "text_signals": True,
    },
    "v9": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "sticky_terms": True,
    },
    "v10": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "sticky_terms": True,
        "push_after_final": 1,
    },
    "v11": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "sticky_terms": True,
        "final_push": 0.005,
    },
    "v12": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "sticky_terms": True,
        "sticky_fields": ("ppm_commitment", "chargeback_eur_per_complaint"),
        "value_neutral_terms": True,
        "contract_at_horizon": True,
    },
    "v13": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "sticky_terms": True,
        "sticky_max_cost": 0.008,
        "value_neutral_terms": True,
        "contract_at_horizon": True,
    },
    "v14": {
        "adopt_insisted": True,
        "rival_only_lower": True,
        "cash_trade_always": True,
        "anchor_leverage": 0.22,
        "rfq_anchor_vs_leader": 0.08,
        "adopt_revealed": True,
        "sticky_terms": True,
        "sticky_max_cost": 0.008,
        "value_neutral_terms": True,
        "contract_at_horizon": True,
        "rel_anchor": True,
        "trade_no_rel": True,
        "close_room": 0.1,
    },
}
VARIANTS["v15"] = {**VARIANTS["v14"], "final_push": 0.008}
VARIANTS["v16"] = {**VARIANTS["v14"], "history_claims": True}
VARIANTS["v18"] = {**VARIANTS["v14"], "anchor_leverage": 0.12}
VARIANTS["v14a"] = {**VARIANTS["v14"], "alt_quote_claim": True}
VARIANTS["v16a"] = {**VARIANTS["v16"], "alt_quote_claim": True}
VARIANTS["v7a"] = {**VARIANTS["v7"], "alt_quote_claim": True}
VARIANTS["basea"] = {"rival_only_lower": True, "alt_quote_claim": True}
VARIANTS["v7c"] = {**VARIANTS["v7a"], "concede_early": 0.35}  # hold study: front-load concessions (sandbox A/B)
VARIANTS["v14c"] = {**VARIANTS["v14a"], "concede_early": 0.35}
VARIANTS["v14r"] = {**VARIANTS["v14a"], "rel_full": 0.965}
VARIANTS["v14s"] = {**VARIANTS["v14a"], "anchor_below_open": 0.04}
VARIANTS["v17"] = {**VARIANTS["v16"], "rel_anchor": False, "close_gap": 0.001, "close_room": 0.05}



# What each variant tests, in words - stored with every ledger row (keep it one or two sentences).
DESCRIPTIONS = {
    "base": "Champion on main (v1 + fix): lever engine, verified claims, parallel threads; anchors 12% below "
    "the opening, concedes 25%/50% of the gap; weighs every offered sheet, cheapest clause when insisted, "
    "should-cost x0.95.",
    "v1": "The first baseline: like base but takes only the supplier's first sheet, no clause rule, should-cost x1.",
    "v2": "base + D02 sandbox lessons: adopt terms the supplier held twice, cite a rival only if lower, "
    "always offer a faster-payment sheet, concede at most half the supplier's step, anchor 18% below.",
    "v3": "v2 + the replay fixes (now in base) = base + v2's concession tactics.",
    "v5": "Fable review bets: anchor 22% below outside relationship goals with no floor; RFQ first ask <= 92% "
    "of the cheapest rival; keep terms the supplier's own alternative sheets show are cheaper for us; hold "
    "price while it asks its boss; v2's held-terms, lower-rival, cash sheet; concede at most half its step.",
    "v6": "v5 with base's concession speed (follow_share 1.1): keep the RFQ gain without the D01 patience loss.",
    "v7": "v6 without holding the price while the supplier asks its boss.",
    "v8": "v7 + trade sheets over every term (lead time, ppm, chargeback, incoterm, clause...), one step toward "
    "the supplier, liked terms first, then cheapest for us; + pressures read from the supplier's own e-mails.",
    "v9": "v7 + sticky terms: after our first ask keep the non-price terms of the supplier's cheapest-for-us "
    "sheet and negotiate price (P11 flipped quality terms 3x and accepted the dearest set).",
    "v10": "v9 + push once more after the supplier's final offer (0 walk-aways in ~630 real supplier moves).",
    "v11": "v9 + after a final offer one small push (0.5 % below it, same terms), only with the leading bidder "
    "(sandbox: D01 agreed 49.80 -> 49.55; a far-off push made DEMO-C1 walk away).",
    "v12": "v9 fixed by the coverage review: sticky only for quality terms (v9 locked in must-have-breaking "
    "volume/lead time, P01 dates); chargeback/ppm/payment chosen at the price that keeps the supplier's value "
    "equal (it pays chargebacks at its real ppm); no contract beyond the horizon when a rising index clause looms.",
    "v13": "v9 with sticky terms only where keeping the supplier's value costs us <= 0.8 % of C (D01 payment "
    "sticks; P01's early date does not) + v12's value-neutral quality terms and contract cap.",
    "v18": "v14 with base's 12 % anchor instead of 22 % (engine model: P11 stays open to reply 6, 44.5 vs 45.0; "
    "deep asks > ~8-10 % below the floor make suppliers go final 1-2 replies earlier).",
    "v17": "v16 with v13's anchor for relationship goals (P02: 369 kept the supplier open at reply 4, 358 drew "
    "a final offer at reply 4 in all three runs) and patience: close only within 0.1 % of C / 5 % of the room.",
    "v16": "v14 + more checked arguments for rounds 2+: our order history with the supplier (its cheapest "
    "recent orders), mean ppm of its quality notifications, delivery over earlier quarters, and case refs we "
    "hold no figures for, cited without one (D01/D02 had no arguments at all).",
    "v15": "v14 + after a final offer one push 0.8 % below it, leading bidder only (sandbox logs: 10 of 11 "
    "pushes <= 2 % improved the deal, none walked; 9.6 % and 15.7 % pushes walked).",
    "v14r": "v14a with the real full cost at should-cost x 0.965 instead of 0.98 (P02: the bot accepted our "
    "relationship-optimal clause sheet at reply 1 in every run; C_best is 27 % of the room below it).",
    "v14s": "v14a with a 4 % anchor instead of 12 % (P10: a 12 %-below ask draws a final offer at reply 1 from a "
    "capacity-full supplier whose desk may move 2 %; soft-anchor study).",
    "v14a": "v14 + cite the case's alternative quote (verified) once per supplier when it is below the ask; never a pricier one.",
    "v16a": "v16 + the v14a alternative-quote argument.",
    "v7a": "v7 + the v14a alternative-quote argument.",
    "basea": "base + cite only rivals below this supplier's price (base cites the best rival even when it is higher: "
    "'the rival offer is still higher than our price', P05) + the v14a alternative-quote argument.",
    "v14": "v13 + price-increase review: relationship goals anchor at the relationship-optimal price at the "
    "supplier's real cost (should-cost x0.98), not the should-cost floor (P02 369 -> 358); trade sheets priced "
    "without the relationship term (they were all dropped); close only when the gap <= 10 % of the room.",
    "v4": "base tactics (12% anchor, steady concessions keep the supplier conceding: D01) + v2's adopt-held-terms, "
    "lower-rival-only, cash sheet + floor guard (P05 anchored 0.5% below the opening) + RFQ: beat the leader.",
}


def params(name):
    if name not in VARIANTS:
        raise SystemExit(f"unknown variant {name!r}; known: {', '.join(VARIANTS)}")
    known = {f.name for f in fields(Params)}
    bad = set(VARIANTS[name]) - known
    if bad:
        raise SystemExit(f"variant {name!r} sets unknown params: {bad}")
    return Params(**VARIANTS[name])


def describe(name):
    return asdict(params(name))


def description(name):
    return DESCRIPTIONS.get(name, "")
