"""realsim: a supplier simulator CALIBRATED on 198 logged practice sessions (free, in-process, no quota).

`csee.localsim` gives the routed agents ~0.32 where practice gives ~0.78, so changes cannot be judged on it.
This module replaces its supplier model with personas fitted per practice supplier from the sessions in
`runs/sessions/*.json` (every move, the supplier's sheets and alternatives, its reasons, the result incl.
C_open/C_best), and generalises them to unseen suppliers with type priors plus a `--perturb` mode.

What the sessions show (and what a `Desk` reproduces):
  * the supplier prices every sheet at its OWN value: the arena's `supplier_value` (payment at its money rate,
    freight, early-start units at the old price, chargebacks at its real ppm) plus lead time, contract length,
    volume and an index clause at persona rates. Its alternative sheet is the same value at its standard term
    (P02 373.88 @ 90 d = 369.76 @ 30 d at 6.6 %; P18 5.60/5.50 at 11 %; P10 33.60 @ 42 d vs 31.70 @ 54 d).
  * two floors: the TRUE floor F (what C_best is built on) and the desk's stop D = F x (1 + desk_margin) where
    Sales stops and goes `final_offer` (P10 +15 %, P18 +14 %, P07 +7 %, P08 +5 %, P11 +4 %, P01/P04 < 1 %).
  * a first counter of a fixed size (first_cut x opening) that adopts our non-price terms, then steps of
    `share` x min(gap to D, gap to our best sheet), capped by a desk band (pricing-committee desks: ~2 %), on
    the supplier's price grid (P11 0.50, P18/P10/P01 0.10). Verified claims of the kinds it "takes into
    account" cut its ask once per kind; the others "hold but do not change our calculation".
  * holds when we do not move a tick, repeat a sheet or reverse a price; `final_offer` at its patience (reply
    2 Ravensteiner/Waelzlager, 3 Donautal, 4 Leitner, 5 Brandlhuber, 6 Selvbrunn) or after 2-4 holds; it
    agrees to our sheet the moment our sheet is worth at least its next ask (P01 132.22, P05 28.13, P18 5.30).
  * walks: Nordmark leaves after 4 replies with us still below its floor, and on any push below its final;
    Werdenfels on a push below its final; the others answer a small push (<= 1 %) with "agreed" when their last
    step was > 0, else repeat the final (P07 5.52 -> 5.48, P08 5.51 -> 5.48 agreed; P02/P18 walked).

Interface: `RealTable` = `csee.localsim.LocalTable` = `arena_kit.play.RemoteTable`, so `csee.runner.play_case`
runs on it unchanged. CLI: `uv run python -m csee.realsim --agents router router-x --seeds 5 [--cases ...]
[--perturb] [--validate]`. `csee sim` (the old simulator) is untouched.

Limits (honest): e-mail wording effects (a contradicted claim, an unanswered "which volume" question, the
model adding sheets) are not simulated; claims count by ID prefix, all taken as verified; the LLM's random
step sizes are replaced by their fitted means, so a persona reproduces the mean of a case, not its spread.
"""

import argparse
import itertools
import json
import math
import random
import statistics
from dataclasses import dataclass, field, replace
from pathlib import Path

from arena_kit.client import ArenaError
from arena_kit.cost import closing_terms, must_haves_ok, score, supplier_value, total_cost

from . import intel as intel_mod
from . import levers

CASES = Path(__file__).parent / "cases" / "practice.json"
FIELDS = (
    "payment_days",
    "lead_time_days",
    "volume_per_year",
    "contract_months",
    "effective_date",
    "index_clause",
    "incoterm",
    "tooling_eur",
    "ppm_commitment",
    "chargeback_eur_per_complaint",
)
# claim kinds by data-ID prefix, as the arena's "We checked the <kind> data you cited" sentences name them
KIND_OF_PREFIX = {
    "idx": "index",
    "cost": "should_cost",
    "fc": "forecast",
    "quote": "rival",
    "offer": "rival",
    "doc": "notice",
    "ctr": "notice",
    "sc": "delivery",
    "qn": "quality",
    "po": "history",
    "news": "news",
    "rfq": "rival",
}
KIND_TEXT = {
    "index": "index change",
    "should_cost": "should cost",
    "forecast": "volume change",
    "rival": "rival quote",
    "notice": "notice period",
    "delivery": "delivery record",
    "quality": "quality record",
    "history": "price history",
    "news": "news",
}
DEFAULT_MOVES_ON = frozenset({"index", "should_cost", "forecast", "rival", "notice", "news"})


@dataclass
class Persona:
    """One supplier's fitted behaviour. Prices and floors are in the case's price unit."""

    sid: str
    name: str = ""
    opening: dict = field(default_factory=dict)  # the terms of its opening sheet (exact for practice suppliers)
    missing: tuple = ()  # fields its opening sheet leaves out (the arena lists them as missing_fields)
    std: dict = field(default_factory=dict)  # its standard terms (the quote PDF's "Our standard terms")
    rate: float = 0.08  # its money rate per year: how it prices payment days (true = quoted)
    floor: float = 0.0  # TRUE floor: its value per unit at standard terms it will not go below (C_best)
    full_cost: float | None = None  # its full cost per unit for the arena's relationship charge (default: floor)
    desk_margin: float = 0.02  # Sales stops at floor x (1 + desk_margin) and declares its final offer
    first_cut: float = 0.03  # first counter: this share of the opening, in value terms
    share: float = 0.35  # later replies: this share of min(gap to its stop, gap to our best sheet)
    final_share: float = 0.5  # the share on its last (final) reply
    band: float = math.inf  # a step is never more than this share of the opening (committee desks ~0.02)
    tick: float = 0.01  # its price grid
    patience: int = 5  # reply number at which it goes final at the latest
    holds_to_final: int = 3  # holds (no step) before it goes final
    far_gap: float = 1.0  # our best sheet more than this share of the opening below its ask: final once at its stop
    moves_on: frozenset = DEFAULT_MOVES_ON  # claim kinds that change its calculation
    claim_pct: float = 0.003  # value cut per effective claim kind, once per kind
    max_claims: int = 3
    lead_quote_per_day: float = 0.005  # what it CHARGES per day of lead time below its standard (share of price)
    lead_cost_per_day: float = 0.0018  # what a day of lead time is really worth to it (C_best), both directions
    contract_pct_per_year: float = 0.005  # value of each contract year beyond its standard
    volume_pct: float = 0.03  # value per +100 % volume vs its standard
    ppm_tighten_cost: float = 0.0  # EUR per unit per 1,000 ppm of a tighter commitment than its standard
    real_ppm: int | None = None  # the defect rate it really has (chargebacks cost it ppm x chargeback)
    clause_flat: float = 0.005  # value of any index clause (share of price)
    clause_vol: float = 0.055  # plus material_share x max(0, clause_vol - 0.009 x deadband_pct)
    clause_true_factor: float = 1.0  # the clause's TRUE worth (C_best) as a share of what the desk credits
    needs_clause_months: int | None = None  # raw material: no fixed price for contracts this long or longer
    default_deadband: float = 0.0  # the deadband it writes when it adds the clause itself
    walk_on_push: bool = False  # a counter below its final offer makes it leave
    walk_below_floor_after: int | None = None  # from this reply on it leaves when we are still below its floor
    half_step_rival: bool = False  # owner-led job shops: "half the step now", the rest next reply
    agree_push_pct: float = 0.01  # non-walkers: a push this small below the final is agreed if it last moved
    phrases: tuple = ()  # formulaic sentences the agent's signal regexes read (cash, capacity, volume, index)
    opening_body: str = ""  # its opening e-mail (the real one for practice suppliers: it carries its index claims)
    subject: str = ""
    drivers: tuple = ()  # generated openings: "<series> rose x % in twelve months and is y % of our cost."
    insists: dict = field(default_factory=dict)  # non-price terms it keeps in its primary sheet
    signals: dict = field(default_factory=lambda: {"reply_delay_days": 2, "validity_days": 30})


# ---------------------------------------------------------------------------------------------------------------
# Personas fitted on the 198 practice sessions (10 cases, 12 suppliers). Floors are fitted so that the
# simulator's C_best reproduces the arena's (see `fit_floor`); the rest is read off the logged trajectories.
# ---------------------------------------------------------------------------------------------------------------
PERSONAS = {
    "sup:70110": Persona(  # P01 Giesserei Brandlhuber: family foundry, cash-short, patient, no committee
        sid="sup:70110",
        name="Giesserei Brandlhuber GmbH & Co. KG",
        opening={"unit_price": 138.55, "effective_date": "2026-11-01"},
        missing=("payment_days",),
        std={"payment_days": 30, "ppm_commitment": 900, "chargeback_eur_per_complaint": 0.0, "lead_time_days": 42,
             "volume_per_year": 8150, "contract_months": 12, "index_clause": None, "incoterm": "FCA",
             "tooling_eur": 0.0},
        rate=0.10,
        floor=130.2,
        full_cost=130.0,
        desk_margin=0.004,
        first_cut=0.041,
        share=0.38,
        final_share=0.5,
        tick=0.10,
        patience=5,
        holds_to_final=2,
        moves_on=frozenset({"index", "should_cost", "forecast", "notice", "quality", "news"}),
        claim_pct=0.003,
        real_ppm=712,
        phrases=("Faster payment helps our cash flow; that is reflected in the price.",
                 "A binding higher volume would help us and can improve the price. Which volume can you commit to?"),
    ),
    "sup:70510": Persona(  # P02 Antriebstechnik Nordmark AG: group KAM, 2 % committee, copper clause, walks
        sid="sup:70510",
        name="Antriebstechnik Nordmark AG",
        opening={"unit_price": 370.96, "payment_days": 30, "index_clause": None},
        std={"payment_days": 30, "ppm_commitment": 250, "chargeback_eur_per_complaint": 0.0, "lead_time_days": 35,
             "volume_per_year": 6110, "contract_months": 12, "effective_date": "2027-01-01", "index_clause": None,
             "incoterm": "DAP", "tooling_eur": 0.0},
        rate=0.066,
        floor=361.8,
        full_cost=367.6,
        desk_margin=0.0175,
        first_cut=0.0032,
        share=0.17,
        final_share=0.3,
        band=0.0027,
        tick=0.05,
        patience=4,
        holds_to_final=2,
        moves_on=frozenset({"index", "should_cost", "forecast", "notice", "news"}),
        claim_pct=0.002,
        real_ppm=250,
        clause_flat=0.035,
        clause_vol=0.0,
        clause_true_factor=0.2,
        default_deadband=5.0,
        walk_on_push=True,
        walk_below_floor_after=4,
        phrases=("Our calculation is our property; we do not share a breakdown.",
                 "A binding higher volume would help us and can improve the price. Which volume can you commit to?"),
    ),
    "sup:70530": Persona(  # P03 Selvbrunn Drive Systems: group, "price reductions frozen", trades payment only
        sid="sup:70530",
        name="Selvbrunn Drive Systems GmbH",
        opening={"unit_price": 438.21, "payment_days": 30, "contract_months": 12, "volume_per_year": 4580},
        std={"payment_days": 30, "ppm_commitment": 350, "chargeback_eur_per_complaint": 0.0, "lead_time_days": 49,
             "volume_per_year": 4580, "contract_months": 12, "effective_date": "2027-01-01", "index_clause": None,
             "incoterm": "DAP", "tooling_eur": 0.0},
        rate=0.041,
        floor=428.5,
        full_cost=397.4,
        desk_margin=0.0065,
        first_cut=0.0126,
        share=0.0,
        final_share=0.0,
        band=0.0,
        tick=0.01,
        patience=6,
        holds_to_final=4,
        moves_on=frozenset({"should_cost", "forecast", "notice", "index", "news"}),
        claim_pct=0.0,
        real_ppm=350,
        contract_pct_per_year=0.004,
        phrases=("Our management has frozen all price reductions until December. We can talk about the terms "
                 "instead - payment and call-offs.",),
    ),
    "sup:70620": Persona(  # P04 Waelzlager-Zentrum Sued: list-price distributor, floor at reply 1, final at 2
        sid="sup:70620",
        name="Waelzlager-Zentrum Sued GmbH",
        opening={"unit_price": 4.96, "payment_days": 30, "contract_months": 12},
        std={"payment_days": 30, "ppm_commitment": 150, "chargeback_eur_per_complaint": 0.0, "lead_time_days": 7,
             "volume_per_year": 20000, "contract_months": 12, "effective_date": "2027-01-01", "index_clause": None,
             "incoterm": "DAP", "tooling_eur": 0.0},
        rate=0.08,
        floor=4.87,
        desk_margin=0.002,
        first_cut=0.0165,
        share=0.0,
        final_share=0.0,
        band=0.0,
        tick=0.01,
        patience=2,
        holds_to_final=1,
        moves_on=frozenset(),
        claim_pct=0.0,
        real_ppm=302,
        contract_pct_per_year=0.0,
        phrases=("Material accounts for about half of our cost; more detail we do not share.",),
    ),
    "sup:70210": Persona(  # P05 Zerspanung Dralveck: owner-led job shop, idle capacity, half step on a rival quote
        sid="sup:70210",
        name="Zerspanung Dralveck GmbH",
        opening={"unit_price": 36.0},
        missing=("payment_days", "lead_time_days"),
        std={"payment_days": 30, "lead_time_days": 28, "ppm_commitment": 1200, "chargeback_eur_per_complaint": 0.0,
             "volume_per_year": 4200, "contract_months": 24, "effective_date": "2027-01-01", "index_clause": None,
             "incoterm": "DAP", "tooling_eur": 0.0},
        rate=0.13,
        floor=26.83,
        desk_margin=0.04,
        first_cut=0.153,
        share=0.5,
        final_share=0.5,
        tick=0.5,
        patience=5,
        holds_to_final=3,
        moves_on=frozenset({"index", "rival", "delivery", "news", "should_cost", "forecast", "notice"}),
        claim_pct=0.003,
        real_ppm=1200,
        half_step_rival=True,
        phrases=("We need to clarify this internally - we will come back to you on price.",
                 "We have free capacity for your parts.", "With overtime we can deliver in 28 days, at a premium."),
    ),
    "sup:70240": Persona(  # P05 Strojirna Hrvelec: fully booked, 35 days means overtime, cash-short
        sid="sup:70240",
        name="Strojirna Hrvelec s.r.o.",
        opening={"unit_price": 31.5, "lead_time_days": 52},
        missing=("payment_days",),
        std={"payment_days": 45, "lead_time_days": 52, "ppm_commitment": 1400, "chargeback_eur_per_complaint": 0.0,
             "volume_per_year": 4200, "contract_months": 24, "effective_date": "2027-01-01", "index_clause": None,
             "incoterm": "DAP", "tooling_eur": 0.0},
        rate=0.20,
        floor=26.5,
        desk_margin=0.10,
        first_cut=0.016,
        share=0.4,
        final_share=0.4,
        tick=0.5,
        patience=4,
        holds_to_final=2,
        moves_on=frozenset({"index", "rival", "quality", "delivery"}),
        claim_pct=0.005,
        real_ppm=1400,
        lead_quote_per_day=0.0055,
        lead_cost_per_day=0.003,
        phrases=("We are fully booked; a shorter lead time means overtime, which is priced in.",),
    ),
    "sup:70250": Persona(  # P05 Drehteile Fuchsreiter: owner-led, free machines, wants to be paid fast
        sid="sup:70250",
        name="Drehteile Fuchsreiter GmbH",
        opening={"unit_price": 38.5},
        missing=("payment_days", "lead_time_days"),
        std={"payment_days": 30, "lead_time_days": 28, "ppm_commitment": 600, "chargeback_eur_per_complaint": 0.0,
             "volume_per_year": 4200, "contract_months": 24, "effective_date": "2027-01-01", "index_clause": None,
             "incoterm": "DAP", "tooling_eur": 0.0},
        rate=0.14,
        floor=26.92,
        desk_margin=0.045,
        first_cut=0.205,
        share=0.5,
        final_share=0.5,
        tick=0.5,
        patience=5,
        holds_to_final=3,
        moves_on=frozenset({"rival", "news", "index", "should_cost", "forecast"}),
        claim_pct=0.003,
        real_ppm=600,
        half_step_rival=True,
        phrases=("We need to clarify this internally - we will come back to you on price.",
                 "We have free capacity for your parts. Faster payment is welcome; we can reflect it in the price."),
    ),
    "sup:70610": Persona(  # P07 Schraubenhandel Leitner & Sohn: distributor, 2 % pricing committee, final at 4
        sid="sup:70610",
        name="Schraubenhandel Leitner & Sohn GmbH",
        opening={"unit_price": 5.74, "payment_days": 30, "contract_months": 12},
        std={"payment_days": 30, "ppm_commitment": 80, "chargeback_eur_per_complaint": 0.0, "lead_time_days": 5,
             "volume_per_year": 30000, "contract_months": 12, "effective_date": "2027-01-01", "index_clause": None,
             "incoterm": "DAP", "tooling_eur": 0.0},
        rate=0.075,
        floor=5.088,
        desk_margin=0.069,
        first_cut=0.011,
        share=0.47,
        final_share=0.8,
        band=0.02,
        tick=0.01,
        patience=4,
        holds_to_final=2,
        moves_on=frozenset({"forecast", "should_cost", "notice", "rival"}),
        claim_pct=0.003,
        real_ppm=80,
        contract_pct_per_year=0.013,
        phrases=("A binding higher volume would help us and can improve the price. Which volume can you commit to?",
                 "Material accounts for about half of our cost; more detail we do not share."),
    ),
    "sup:70710": Persona(  # P08 Edelstahl-Service Donautal: nickel hedged until March, clause needed from 24 m
        sid="sup:70710",
        name="Edelstahl-Service Donautal GmbH",
        opening={"unit_price": 6.05, "payment_days": 30, "index_clause": None, "contract_months": 12},
        std={"payment_days": 30, "ppm_commitment": 50, "chargeback_eur_per_complaint": 0.0, "lead_time_days": 10,
             "volume_per_year": 94800, "contract_months": 12, "effective_date": "2027-01-01", "index_clause": None,
             "incoterm": "DAP", "tooling_eur": 0.0},
        rate=0.07,
        floor=5.09,
        desk_margin=0.043,
        first_cut=0.08,
        share=0.8,
        final_share=1.0,
        band=0.035,
        tick=0.01,
        patience=3,
        holds_to_final=2,
        moves_on=frozenset({"index", "forecast", "rival", "should_cost", "notice"}),
        claim_pct=0.008,
        real_ppm=50,
        needs_clause_months=24,
        default_deadband=0.0,
        clause_flat=0.005,
        clause_vol=0.055,
        phrases=("We can offer a Preisgleitklausel on AS-14404.",
                 "Our AS-14404 is covered at fixed prices until March, so recent market drops do not reach our cost.",
                 "Material accounts for about 70 % of our cost; more detail we do not share."),
    ),
    "sup:70410": Persona(  # P10 Dichtungswerk Ravensteiner: group segment desk, 2 replies, lead time is its lever
        sid="sup:70410",
        name="Dichtungswerk Ravensteiner GmbH",
        opening={"unit_price": 32.2, "lead_time_days": 54, "volume_per_year": 19890, "contract_months": 12},
        std={"ppm_commitment": 300, "chargeback_eur_per_complaint": 0.0, "payment_days": 30, "lead_time_days": 54,
             "volume_per_year": 19890, "contract_months": 12, "effective_date": "2027-01-01", "index_clause": None,
             "incoterm": "DAP", "tooling_eur": 0.0},
        rate=0.08,
        floor=27.93,
        full_cost=23.8,
        desk_margin=0.146,
        first_cut=0.0,
        share=0.5,
        final_share=1.0,
        band=0.0063,
        tick=0.1,
        patience=2,
        holds_to_final=1,
        far_gap=0.06,
        moves_on=frozenset({"should_cost"}),
        claim_pct=0.0,
        real_ppm=300,
        lead_quote_per_day=0.005,
        lead_cost_per_day=0.0018,
        volume_pct=0.09,
        contract_pct_per_year=0.0,
        phrases=("Due to our high capacity utilization, a shorter lead time is not feasible.",
                 "Our calculation is our property; we do not share a breakdown."),
    ),
    "sup:70140": Persona(  # P11 Odlewnia Kalwisz: cash-short Polish foundry, 0.50 ticks, holds for faster payment
        sid="sup:70140",
        name="Odlewnia Kalwisz Sp. z o.o.",
        opening={"unit_price": 47.0, "ppm_commitment": 6400},
        missing=("chargeback_eur_per_complaint",),
        std={"chargeback_eur_per_complaint": 0.0, "payment_days": 60, "lead_time_days": 56, "volume_per_year": 15900,
             "contract_months": 12, "effective_date": "2027-01-01", "index_clause": None, "incoterm": "FCA",
             "tooling_eur": 0.0, "ppm_commitment": 6400},
        rate=0.14,
        floor=43.77,
        desk_margin=0.0395,
        first_cut=0.0106,
        share=0.5,
        final_share=0.5,
        band=0.0107,
        tick=0.5,
        patience=7,
        holds_to_final=3,
        far_gap=0.10,
        moves_on=frozenset({"index", "delivery", "quality", "forecast", "should_cost"}),
        claim_pct=0.0,
        real_ppm=2376,
        ppm_tighten_cost=0.0,
        phrases=("We see your figures, but we cannot give up margin right now. Faster payment would help us more "
                 "than anything.", "Our standard Zahlungsziel is 60 days net. Faster payment is welcome; we can "
                 "reflect it in the price.", "Which volume can you commit to?"),
    ),
    "sup:70740": Persona(  # P18 Blankstahl Werdenfels: rigid 10 ct steps (2 % committee), clause from 24 m, walks
        sid="sup:70740",
        name="Blankstahl Werdenfels GmbH",
        opening={"unit_price": 6.1, "payment_days": 30, "index_clause": None, "contract_months": 12},
        std={"payment_days": 30, "ppm_commitment": 70, "chargeback_eur_per_complaint": 0.0, "lead_time_days": 14,
             "volume_per_year": 23700, "contract_months": 12, "effective_date": "2027-01-01", "index_clause": None,
             "incoterm": "DAP", "tooling_eur": 0.0},
        rate=0.11,
        floor=4.718,
        desk_margin=0.140,
        first_cut=0.086,
        share=0.5,
        final_share=1.0,
        band=0.02,
        tick=0.1,
        patience=3,
        holds_to_final=2,
        moves_on=frozenset({"index", "forecast", "rival", "should_cost", "notice"}),
        claim_pct=0.004,
        real_ppm=70,
        needs_clause_months=24,
        default_deadband=5.0,
        walk_on_push=True,
        phrases=("We can offer a Preisgleitklausel on AS-14404.", "Our standard Zahlungsziel is 30 days net.",
                 "Material accounts for about 70 % of our cost; more detail we do not share."),
    ),
}

# The practice suppliers' real opening e-mails (subject, body): they carry the index claims our intel reads and the
# wording our signal regexes and lever agents react to, so the engines see what they saw on the arena.
OPENING_MAILS = {
    'sup:70110': (
        'Quote from Gießerei Brandlhuber GmbH & Co. KG: Brandlhuber announces +9.5 % on HN volute casings',
        'Guten Tag,\n'
        '\n'
        'Thank you for your enquiry. Please find our Angebot below. For many years, our family foundry has '
        'taken great pride in supplying your respected company with high-quality castings from our region, '
        'and we value our long standing relationship very much.\n'
        '\n'
        'Our team has prepared our offer carefully. We can offer you a price of €138.55 per unit, valid from '
        '1 November 2026. This Angebot remains valid for 30 days.\n'
        '\n'
        'To remain transparent about our situation, LCI-C rose 2.7 % in twelve months and is 30 % of our '
        'cost. Furthermore, PPI-C241 rose 6.5 % in twelve months and is 24 % of our cost. We trust that you '
        'understand the necessity of these figures for our ongoing operation and quality standards.\n'
        '\n'
        'Viele Grüße aus der Gießerei\n'
        'Thomas Brandlhuber\n'
        'Owner, Gießerei Brandlhuber GmbH & Co. KG',
    ),
    'sup:70140': (
        'Quote from Odlewnia Kalwisz Sp. z o.o.: Kalwisz: bearing brackets in red',
        'Hello,\n'
        '\n'
        'Thank you for your enquiry. Please find our Angebot below. We are very eager to work with you and to '
        'prove ourselves as a great long-term partner for your business!\n'
        '\n'
        'We are happy to present our offer for a price of €47.00 per unit, along with a quality commitment of '
        '6400 ppm.\n'
        '\n'
        'Please note that this offer stays valid for 30 days. We remain flexible and look forward to hearing '
        'from you soon so we can start building a strong partnership together.\n'
        '\n'
        'Kind regards\n'
        'Marek Lis\n'
        'Export Manager, Odlewnia Kalwisz Sp. z o.o.',
    ),
    'sup:70210': (
        'Quote from Zerspanung Dralveck GmbH: RFQ: pump shaft for the new HX series',
        'Hallo,\n'
        '\n'
        'Thank you for your enquiry. Please find our Angebot below.\n'
        '\n'
        'It is good to hear from you again. For this work, we can offer a price of €36.00 per unit. We have '
        'our CNC machines ready and look forward to putting this job onto the shop floor for you.\n'
        '\n'
        'Let me know if this works for you so we can get started soon.\n'
        '\n'
        'Gruß\n'
        'Andreas Dralveck\n'
        'Owner, Zerspanung Dralveck GmbH',
    ),
    'sup:70240': (
        'Quote from Strojírna Hrvelec s.r.o.: RFQ: pump shaft for the new HX series',
        'Hello,\n'
        '\n'
        'Thank you for your enquiry. Please find our Angebot below. We are very eager to work together with '
        'you and to prove ourselves as a reliable, long-term partner for your business!\n'
        '\n'
        'We are happy to offer you a price of €31.50 per unit, Lieferzeit 52 days.\n'
        '\n'
        'Please note that this offer stays valid for 30 days. We really look forward to hearing from you soon '
        'and hope we can start a great cooperation!\n'
        '\n'
        'Kind regards\n'
        'Jana Procházková\n'
        'Export Manager, Strojírna Hrvelec s.r.o.',
    ),
    'sup:70250': (
        'Quote from Drehteile Fuchsreiter GmbH: RFQ: pump shaft for the new HX series',
        'Hallo,\n'
        'here is our price.\n'
        'Our terms: a price of €38.50 per unit.\n'
        'Just write if something is unclear.\n'
        'Gruß\n'
        'Claudia Fuchsreiter\n'
        'Owner, Drehteile Fuchsreiter GmbH',
    ),
    'sup:70410': (
        'Quote from Dichtungswerk Ravensteiner GmbH: Ravensteiner cuts the seal allocation',
        'Dear Sir or Madam,\n'
        '\n'
        'Thank you for your enquiry. Please find our Angebot below.\n'
        '\n'
        'We offer a price of €32.20 per unit for a volume of 19890 pcs per year. Our Lieferzeit is 54 days, '
        'and the contract term is 12 months.\n'
        '\n'
        'Please note that this offer remains valid for 30 days. All deliveries and services are strictly '
        'subject to our standard procedure and standard conditions.\n'
        '\n'
        'Mit freundlichen Grüßen\n'
        'Monika Zellner\n'
        'Segment Manager, Dichtungswerk Ravensteiner GmbH',
    ),
    'sup:70510': (
        'Quote from Antriebstechnik Nordmark AG: Nordmark passes on copper for the 7.5 kW motor',
        'Dear Sir or Madam,\n'
        '\n'
        'Thank you for your enquiry. Please find our Angebot below.\n'
        '\n'
        'We offer a price of €370.96 per unit, Zahlungsziel 30 days net, no Preisgleitklausel.\n'
        '\n'
        'Regarding our cost structure, CU-NOTATION rose 47.7 % in twelve months and is 20 % of our cost. '
        'Furthermore, LCI-C rose 2.7 % in twelve months and is 20 % of our cost. Additionally, PPI-C241 rose '
        '6.5 % in twelve months and is 14 % of our cost.\n'
        '\n'
        'Please note that this offer remains valid for 30 days.\n'
        '\n'
        'Mit freundlichen Grüßen\n'
        'Petra Lechner\n'
        'Key Account Manager, Antriebstechnik Nordmark AG',
    ),
    'sup:70530': (
        'Quote from Selvbrunn Drive Systems GmbH: Frame agreement renewal for the 7.5 kW frequency converter',
        'Dear Sir or Madam,\n'
        '\n'
        'Thank you for your enquiry. Please find our Angebot below.\n'
        '\n'
        'We offer a price of €438.21 per unit, a volume of 4580 pcs per year, a contract term of 12 months, '
        'and a Zahlungsziel 30 days net. This offer remains valid for 30 days.\n'
        '\n'
        'Regarding our cost structure, CU-NOTATION rose 47.7 % in twelve months and is 5 % of our cost. LCI-C '
        'rose 2.7 % in twelve months and is 16 % of our cost. Furthermore, PPI-C2611 rose 13.5 % in twelve '
        'months and is 42 % of our cost.\n'
        '\n'
        'Mit freundlichen Grüßen\n'
        'Birgit Mayrhofer\n'
        'Key Account Manager, Selvbrunn Drive Systems GmbH',
    ),
    'sup:70610': (
        'Quote from Schraubenhandel Leitner & Sohn GmbH: Bundle the fastener kit with one distributor',
        'Dear customer,\n'
        '\n'
        'Thank you for your enquiry. Please find our Angebot below.\n'
        '\n'
        'We are delighted to submit our offer for your consideration. We can offer you a price of €5.74 per '
        'unit, with a Zahlungsziel 30 days net, and a contract term of 12 months.\n'
        '\n'
        'As a valued partner, we always strive to support your operations with our extensive inventory and '
        'reliable delivery service. Please note that this offer remains valid for 30 days.\n'
        '\n'
        'We look forward to continuing our successful business relationship and standing by as your trusted '
        'partner for all your supply needs.\n'
        '\n'
        'Mit freundlichen Grüßen\n'
        'Franz Stadler\n'
        'Inside Sales, Schraubenhandel Leitner & Sohn GmbH',
    ),
    'sup:70620': (
        'Quote from Wälzlager-Zentrum Süd GmbH: Renewal of the ball bearing 6306 agreement',
        'Dear customer,\n'
        '\n'
        'Thank you for your enquiry. Please find our Angebot below. We are pleased to present our current '
        'offer for your requirements, maintaining our commitment to supporting your business with top-quality '
        'service and our extensive product range.\n'
        '\n'
        'For this offer, we quote a price of €4.96 per unit, with a Zahlungsziel 30 days net and a contract '
        'term of 12 months. Please note that this offer remains valid for 30 days.\n'
        '\n'
        'To provide some background on our pricing calculations, LCI-C rose 2.7 % in twelve months and is 10 '
        '% of our cost. Furthermore, PPI-C2815 rose 0.8 % in twelve months and is 65 % of our cost.\n'
        '\n'
        'Mit freundlichen Grüßen\n'
        'Florian Gruber\n'
        'Inside Sales, Wälzlager-Zentrum Süd GmbH',
    ),
    'sup:70710': (
        'Quote from Edelstahl-Service Donautal GmbH: Alloy surcharge and base price for 1.4404 bar',
        'Dear customer,\n'
        '\n'
        'Thank you for your enquiry. Please find our Angebot below.\n'
        '\n'
        'We are pleased to submit our offer at a price of €6.05 per unit, with a Zahlungsziel 30 days net, a '
        'contract term of 12 months, and no Preisgleitklausel. Please note that this offer remains valid for '
        '30 days.\n'
        '\n'
        'To give you some insight into our cost environment: AS-14404 rose 5.9 % in twelve months and is 45 % '
        'of our cost. Furthermore, LCI-C rose 2.7 % in twelve months and is 5 % of our cost, while PPI-C2431 '
        'rose 12.3 % in twelve months and is 38 % of our cost.\n'
        '\n'
        'Mit freundlichen Grüßen\n'
        'Georg Aigner\n'
        'Inside Sales, Edelstahl-Service Donautal GmbH',
    ),
    'sup:70740': (
        'Quote from Blankstahl Werdenfels GmbH: Alloy surcharge and base price for 1.4404 bar (Werdenfels)',
        'Dear customer,\n'
        '\n'
        'Thank you for your enquiry. Please find our Angebot below.\n'
        '\n'
        'We are delighted to present our competitive quote for your requirements. Our price is €6.10 per '
        'unit, with a Zahlungsziel of 30 days net, a contract term of 12 months, and no Preisgleitklausel. '
        'Please note that AS-14404 rose 5.9 % in twelve months and is 45 % of our cost. Furthermore, LCI-C '
        'rose 2.7 % in twelve months and is 5 % of our cost, while PPI-C2431 rose 12.3 % in twelve months and '
        'is 38 % of our cost. This offer remains valid for 30 days.\n'
        '\n'
        'Mit freundlichen Grüßen\n'
        'Franz Seidl\n'
        'Inside Sales, Blankstahl Werdenfels GmbH',
    ),
}

# Priors for suppliers without a fitted persona (the other practice.json cases, the Live Final): by case type,
# as (floor / opening, the persona template). Floors from the C_best back-outs above: price increases and
# renewals sit 2.5-5.5 % under the opening, RFQ job shops 20-30 %, raw material 17-24 %, capacity 15 %.
TYPE_PRIORS = {
    "price_increase": dict(floor_ratio=0.955, desk_margin=0.01, first_cut=0.02, share=0.3, final_share=0.4,
                           band=0.02, patience=5, holds_to_final=2, open_ratio=(1.06, 1.10)),
    "renewal": dict(floor_ratio=0.975, desk_margin=0.006, first_cut=0.018, share=0.1, final_share=0.1, band=0.01,
                    patience=4, holds_to_final=2, open_ratio=(1.06, 1.13)),
    "rfq": dict(floor_ratio=0.75, desk_margin=0.06, first_cut=0.15, share=0.5, final_share=0.5, band=math.inf,
                patience=5, holds_to_final=3, open_ratio=(0.87, 1.06), half_step_rival=True),
    "bundling": dict(floor_ratio=0.865, desk_margin=0.07, first_cut=0.013, share=0.47, final_share=0.8, band=0.02,
                     patience=4, holds_to_final=2, open_ratio=(0.88, 0.95), contract_pct_per_year=0.013),
    "raw_material": dict(floor_ratio=0.79, desk_margin=0.10, first_cut=0.085, share=0.65, final_share=1.0,
                         band=0.025, patience=3, holds_to_final=2, open_ratio=(1.04, 1.12), needs_clause_months=24,
                         default_deadband=5.0, walk_on_push=True),
    "capacity": dict(floor_ratio=0.85, desk_margin=0.14, first_cut=0.0, share=0.5, final_share=1.0, band=0.0065,
                     patience=2, holds_to_final=1, far_gap=0.06, open_ratio=(1.05, 1.10), volume_pct=0.09,
                     contract_pct_per_year=0.0, moves_on=frozenset({"should_cost", "index"})),
    "quality": dict(floor_ratio=0.93, desk_margin=0.039, first_cut=0.011, share=0.5, final_share=0.5, band=0.011,
                    patience=7, holds_to_final=3, far_gap=0.10, open_ratio=(1.02, 1.06),
                    moves_on=frozenset({"index", "delivery", "quality", "forecast", "should_cost"})),
}
GENERIC_PRIOR = dict(floor_ratio=0.9, desk_margin=0.03, first_cut=0.03, share=0.35, final_share=0.4, band=0.02,
                     patience=4, holds_to_final=2, open_ratio=(1.0, 1.08))


def kind_of(ref):
    return KIND_OF_PREFIX.get(str(ref).split(":")[0], "other")


def tick_for(price):
    """A price grid prior: cents under EUR 10, else 10 cents (practice desks used 0.01-0.5; --perturb varies it)."""
    return 0.01 if price < 10 else 0.1


def persona_for(case, sid, pkg, rng, perturb=False):
    """The fitted persona for a practice supplier, else one built from the case file, the data package and the
    type prior (opening around the current/fallback price, floor from the type ratio and the should-cost)."""
    base = PERSONAS.get(sid)
    if base is None:
        base = _derived_persona(case, sid, pkg, rng)
    elif sid in OPENING_MAILS and not base.opening_body:
        subject, body = OPENING_MAILS[sid]
        base = replace(base, subject=subject, opening_body=body)
    if perturb:
        base = perturbed(base, rng)
    return base


def _derived_persona(case, sid, pkg, rng):
    b = case["buyer"]
    prior = {**GENERIC_PRIOR, **TYPE_PRIORS.get(case.get("type"), {})}
    row = {}
    if pkg is not None:
        try:
            rows = pkg.query("SELECT * FROM suppliers WHERE id = ?", (sid,))
            row = rows[0] if rows else {}
        except Exception:  # a data package without the table: the case file is enough
            row = {}
    profile = intel_mod.load_profile(sid)
    plan = closing_terms(case, {"unit_price": None})
    std = {
        "payment_days": row.get("payment_days") or 30,
        "incoterm": row.get("incoterm") or plan["incoterm"],
        "lead_time_days": row.get("standard_lead_time_days") or plan["lead_time_days"],
        "volume_per_year": plan["volume_per_year"],
        "contract_months": 12 if "contract_months" in case["negotiable"] else plan["contract_months"],
        "effective_date": case.get("fixed_terms", {}).get("effective_date")
        or (case.get("term_options", {}).get("effective_date") or [None])[0],
        "index_clause": None,
        "tooling_eur": 0.0,
        "ppm_commitment": (profile.get("quality") or {}).get("ppm") or 500,
        "chargeback_eur_per_complaint": 0.0,
    }
    current = b.get("current_unit_price") or b["fallback_unit_price"]
    lo, hi = prior["open_ratio"]
    p0 = round(current * rng.uniform(lo, hi), 2)
    # the opening sheet: price plus the negotiable terms the supplier states (its standard ones)
    opening = {"unit_price": p0}
    for f in case["negotiable"]:
        if f in ("unit_price", "payment_days"):
            continue
        if f in std and std[f] is not None:
            opening[f] = std[f]
    if "payment_days" in case["negotiable"] and rng.random() < 0.7:
        opening["payment_days"] = std["payment_days"]
    missing = tuple(f for f in case["negotiable"] if f not in opening)
    floor = prior["floor_ratio"] * p0 * rng.uniform(0.97, 1.03)
    country = row.get("country") or profile.get("country") or "DE"
    full, src = intel_mod.estimate_full_cost(case, pkg, sid, country)
    if full and "its own plant" in (src or ""):
        floor = max(floor, full * 0.98)  # the supplier's own plant costed: it will not sell below ~its cost
    pressures = " ".join(p.get("type", "") for p in profile.get("pressures", []))
    rate = 0.12 if "cash" in pressures or row.get("skonto_pct") else 0.08
    fields_ = {k: v for k, v in prior.items() if k not in ("floor_ratio", "open_ratio")}
    drivers = []
    for clause in case.get("term_options", {}).get("index_clause") or []:
        if not clause or not pkg:
            continue
        try:
            sql = "SELECT month, value FROM index_values WHERE series_id = ? ORDER BY month DESC LIMIT 13"
            vals = pkg.query(sql, (clause["series"],))
        except Exception:
            vals = []
        if len(vals) >= 13 and vals[-1].get("value"):
            change = (vals[0]["value"] / vals[-1]["value"] - 1) * 100
            drivers.append(f"{clause['series']} rose {change:.1f} % in twelve months and is "
                           f"{round(clause.get('material_share', 0.3) * 100)} % of our cost.")
        break
    phrases = []
    if "cash" in pressures:
        phrases.append("Faster payment is welcome; we can reflect it in the price.")
    if "capacity" in pressures:
        phrases.append("We are fully booked; a shorter lead time means overtime, which is priced in.")
    return Persona(
        sid=sid,
        name=row.get("name") or profile.get("name") or sid,
        opening=opening,
        missing=missing,
        std=std,
        rate=rate,
        floor=floor,
        tick=tick_for(p0),
        real_ppm=(profile.get("quality") or {}).get("ppm") or std["ppm_commitment"],
        phrases=tuple(phrases),
        drivers=tuple(drivers),
        **fields_,
    )


def perturbed(p, rng):
    """Sample a persona around a fitted one: floors, ticks, patience, term values, claim sensitivities. Robustness
    to the Live Final's new suppliers, not memorisation of the practice bots."""
    ln = rng.lognormvariate
    kinds = set(p.moves_on)
    pool = set(KIND_TEXT) - kinds
    if kinds and rng.random() < 0.3:
        kinds.discard(rng.choice(sorted(kinds)))
    if pool and rng.random() < 0.3:
        kinds.add(rng.choice(sorted(pool)))
    ticks = [p.tick, p.tick * 2, p.tick / 2]
    return replace(
        p,
        rate=min(0.25, max(0.03, p.rate * ln(0, 0.25))),
        floor=p.floor * ln(0, 0.025),
        desk_margin=p.desk_margin * ln(0, 0.4),
        first_cut=p.first_cut * ln(0, 0.3),
        share=min(0.9, p.share * ln(0, 0.3)),
        final_share=min(0.9, p.final_share * ln(0, 0.3)),
        band=p.band * ln(0, 0.3) if math.isfinite(p.band) else p.band,
        tick=rng.choice(ticks),
        patience=max(2, p.patience + rng.choice([-1, 0, 0, 1])),
        holds_to_final=max(1, p.holds_to_final + rng.choice([-1, 0, 0, 1])),
        moves_on=frozenset(kinds),
        claim_pct=p.claim_pct * ln(0, 0.5),
        lead_quote_per_day=p.lead_quote_per_day * ln(0, 0.3),
        lead_cost_per_day=p.lead_cost_per_day * ln(0, 0.3),
        contract_pct_per_year=p.contract_pct_per_year * ln(0, 0.4),
        volume_pct=p.volume_pct * ln(0, 0.4),
        clause_flat=p.clause_flat * ln(0, 0.4),
        walk_on_push=p.walk_on_push if rng.random() < 0.8 else not p.walk_on_push,
    )


class Desk:
    """One supplier's sales desk in one session: its value function, its ask and its replies."""

    def __init__(self, case, persona, rng):
        self.case, self.p, self.rng = case, persona, rng
        self.sid = persona.sid
        self.std = dict(persona.std)
        for f in FIELDS:  # a complete standard set for the arena's supplier_value
            if self.std.get(f) is None and f != "index_clause":
                self.std[f] = closing_terms(case, persona.opening, self.std).get(f)
        self.std_full = closing_terms(case, persona.opening, self.std)
        self.p0 = persona.opening["unit_price"]
        self.n, self.round = 0, 0
        self.ask = self.value(self.opening_terms())  # its current ask, in value terms (at standard terms)
        # Sales stops at floor x (1 + desk_margin), but a desk always has at least its first cut in it (a derived
        # persona whose floor sits just under its opening would otherwise never move)
        self.stop = min(persona.floor * (1 + persona.desk_margin), self.ask * (1 - max(persona.first_cut, 0.005)))
        self.stop = max(self.stop, persona.floor)
        self.ask = max(self.ask, self.stop)
        self.used_kinds, self.claim_cut = set(), 0.0
        self.prev_bv, self.holds, self.last_step = None, 0, None
        self.pending = 0.0  # "half the step now": the rest comes with the next reply
        self.final, self.ended, self.walked = False, False, False
        self.offered, self.standing, self.standing_id = {}, None, None
        self.seen_sheets = []

    # ---------- value ----------
    def opening_terms(self):
        return self.fill(self.p.opening)

    def std_for_sheet(self):
        return {k: v for k, v in self.std.items() if k in self.case["negotiable"]}

    def value(self, terms, quoted=True):
        """What a sheet is worth to it per unit, cash, at its standard terms (arena supplier_value plus the
        terms the arena does not price: lead time, contract length, volume, an index clause)."""
        t = closing_terms(self.case, terms, self.std)
        if t.get("unit_price") is None:
            return -math.inf
        sup = {"standard": self.std_full, "interest_rate": self.p.rate, "ppm": self.p.real_ppm or 0}
        try:
            v = supplier_value(self.case, t, sup)
        except Exception:
            v = t["unit_price"]
        p = t["unit_price"]
        s = self.std_full
        d = (s.get("lead_time_days") or 0) - (t.get("lead_time_days") or 0)
        if d > 0:  # a shorter lead time than its standard costs it (overtime); the desk charges more than it costs
            v -= d * (self.p.lead_quote_per_day if quoted else self.p.lead_cost_per_day) * p
        elif d < 0 and not quoted:
            v += -d * self.p.lead_cost_per_day * p
        extra_years = ((t.get("contract_months") or 12) - (s.get("contract_months") or 12)) / 12
        v += max(-1.0, extra_years) * self.p.contract_pct_per_year * p
        if s.get("volume_per_year"):
            v += ((t.get("volume_per_year") or s["volume_per_year"]) / s["volume_per_year"] - 1) * self.p.volume_pct * p
        tighter = (s.get("ppm_commitment") or 0) - (t.get("ppm_commitment") or 0)
        if tighter > 0:
            v -= tighter / 1000 * self.p.ppm_tighten_cost
        clause = t.get("index_clause")
        if clause:
            worth = (self.p.clause_flat + clause.get("material_share", 0)
                     * max(0.0, self.p.clause_vol - 0.009 * float(clause.get("deadband_pct") or 0))) * p
            v += worth if quoted else worth * self.p.clause_true_factor
        return v

    def estimate(self):
        """The arena's supplier estimate for the relationship charge in C (stabilise / secure_supply cases)."""
        return {"full_cost": self.p.full_cost or self.p.floor, "interest_rate": self.p.rate, "standard": self.std_full}

    def cost(self, terms):
        """C of a sheet for us, as the arena scores it: with the relationship charge where the goal has one."""
        return total_cost(self.case, terms, self.std, self.estimate())

    def price_for_value(self, terms, target, quoted=True, snap=True):
        """The price at which `terms` are worth `target` to it; on its price grid unless `snap` is False."""
        lo, hi = 0.0, max(self.p0 * 3, 1.0)
        for _ in range(60):
            mid = (lo + hi) / 2
            if self.value({**terms, "unit_price": mid}, quoted) < target:
                lo = mid
            else:
                hi = mid
        return self.snap_price(hi) if snap else round(hi, 2)

    def snap_price(self, price):
        tick = self.p.tick
        return round(round(price / tick) * tick, 2)

    def fill(self, terms):
        """A sheet with every negotiable field: ours or its standard for the rest - NOT snapped to the case's
        options (the arena took its 54-day lead time and our 54-day answer as they were)."""
        plan = closing_terms(self.case, {"unit_price": None})
        std = self.std_for_sheet()
        out = {}
        for f in self.case["negotiable"]:
            v = terms.get(f, std.get(f, plan.get(f)))
            if v is None and f != "index_clause":
                v = plan.get(f)
            out[f] = round(v, 2) if f == "unit_price" and v is not None else v
        return out

    def refuses_fixed(self, terms):
        m = self.p.needs_clause_months
        return bool(m and "index_clause" in self.case["negotiable"] and (terms.get("contract_months") or 0) >= m
                    and not terms.get("index_clause"))

    def clause_for(self, sheets):
        """The clause it writes into a fixed-price sheet: the one we offered elsewhere, else its own deadband."""
        for s in sheets:
            if s.get("index_clause"):
                return s["index_clause"]
        options = [c for c in self.case.get("term_options", {}).get("index_clause", []) if c]
        if not options:
            return None
        return min(options, key=lambda c: abs(float(c.get("deadband_pct") or 0) - self.p.default_deadband))

    def true_floor_cost(self):
        """C_best for this supplier: our cheapest valid term set at the price where its TRUE value is its floor."""
        case = self.case
        opts = case.get("term_options", {})
        fields_ = [f for f in case["negotiable"] if f != "unit_price"]
        choices = []
        for f in fields_:
            if opts.get(f):
                choices.append(list(opts[f]))
            elif f == "volume_per_year":
                choices.append([case["buyer"]["need_per_year"]])
            elif f == "contract_months":
                choices.append([round(12 * case["buyer"]["horizon_years"])])
            else:
                choices.append([self.std_full.get(f)])
        best = math.inf
        for combo in itertools.product(*choices) if choices else [()]:
            terms = dict(zip(fields_, combo, strict=True))
            if self.refuses_fixed(closing_terms(case, terms, self.std)):
                continue
            terms["unit_price"] = self.price_for_value(terms, self.p.floor, quoted=False, snap=False)
            if not must_haves_ok(case, terms, self.std):
                continue
            best = min(best, self.cost(terms))
        return best

    # ---------- replies ----------
    def opening(self):
        terms = dict(self.p.opening)
        msg = self.reply("open", [terms], self.opening_body(), missing=list(self.p.missing), attach_quote=True)
        return msg

    def respond(self, msg):
        p = self.p
        self.n += 1
        raw = [s.get("terms", s) for s in msg.get("term_sheets") or []]
        sheets = [self.fill(s) for s in raw]
        if self.ended:
            return self.reply("walked_away", [], "We have withdrawn from this negotiation.")
        if not sheets:
            text = "Without movement from your side we cannot move either."
            status = "final_offer" if self.final else "open"
            return self.reply(status, [self.standing] if self.standing else [], text)
        # our sheet word for word: agreed
        offered = list(self.offered.values())
        for sh in sheets:
            if sh in offered:
                return self.reply("agreed", [sh], "Agreed, as offered. We look forward to the order confirmation.")
        # claims: by ID prefix; a kind cited again is a duplicate; kinds it moves on cut its ask once
        kinds, results, lines = [], [], []
        for i, ref in enumerate(msg.get("refs") or []):
            k = kind_of(ref)
            if k in kinds or k in self.used_kinds:
                results.append({"index": i, "result": "duplicate"})
                lines.append(f"The {KIND_TEXT.get(k, k)} data you cited was already factored into our previous "
                             "concession.")
                continue
            kinds.append(k)
            results.append({"index": i, "result": "verified"})
            if k in p.moves_on:
                lines.append(f"We checked the {KIND_TEXT.get(k, k)} data you cited; it holds and we took it into "
                             "account.")
            else:
                lines.append(f"We checked the {KIND_TEXT.get(k, k)} data you cited; it holds, but it does not change "
                             "our calculation.")
        effective = [k for k in kinds if k in p.moves_on][: p.max_claims]
        self.used_kinds.update(kinds)
        cut = len(effective) * p.claim_pct * self.p0
        rival = "rival" in kinds
        best = max(sheets, key=self.value)
        bv = self.value(best)
        # the structure it answers with: ours, except what it refuses or insists on
        structure = dict(best)
        if self.refuses_fixed(closing_terms(self.case, structure, self.std)):
            structure["index_clause"] = self.clause_for(sheets)
            lines.append("We cannot offer a fixed price for a contract of this length, so we must include the "
                         "index clause.")
        for f, v in p.insists.items():
            if f in self.case["negotiable"]:
                structure[f] = v
        moved = self.prev_bv is None or bv >= self.prev_bv + p.tick * 0.99
        reversed_ = self.prev_bv is not None and bv < self.prev_bv - p.tick
        self.prev_bv = max(bv, self.prev_bv or -math.inf)
        after_final = self.final
        if after_final:
            return self.after_final(best, bv, structure, lines)
        # the step
        gap_stop = self.ask - self.stop
        gap_buyer = self.ask - bv
        far = gap_buyer > p.far_gap * self.p0
        step = 0.0
        if self.n == 1:
            step = p.first_cut * self.p0
            if p.half_step_rival and rival:
                self.pending = step * 0.45
                lines.append("The buyer shows a much lower rival quote; we give half the step now and check the rest.")
                lines.append("We need to clarify this internally - we will come back to you on price.")
        elif self.pending:
            step, self.pending = self.pending, 0.0
            lines.append("We have clarified this internally and can move further on the price.")
        elif reversed_:
            lines.append("We note with surprise that your proposal has fallen below your previous one; we must "
                         "maintain our offer.")
        elif not moved:
            lines.append("Your proposal is unchanged; without movement from your side we cannot move either.")
        else:
            share = p.final_share if self.n >= p.patience else p.share
            step = share * max(0.0, min(gap_stop, gap_buyer))
            step = min(step, p.band * self.p0) if math.isfinite(p.band) else step
            step = int(step / p.tick + 0.6) * p.tick if p.tick else step  # its grid; 0.4 of a tick rounds up
        step += cut
        step = min(step, max(gap_stop, 0.0))
        if self.n >= 2 and step <= 1e-9:
            self.holds += 1
        self.last_step = step
        before = self.ask
        self.ask = max(self.stop, self.ask - step)
        at_stop = self.ask <= self.stop + p.tick / 2
        # agreed to our sheet when it is worth at least its new ask
        if bv >= self.ask - 1e-9 and best in sheets:
            self.ask = bv
            return self.reply("agreed", [best], " ".join(lines + ["We accept your proposal as stated."]))
        self.final = (
            self.n >= p.patience
            or self.holds >= p.holds_to_final
            or (at_stop and far and self.n >= 4)
        )
        if p.walk_below_floor_after and self.n >= p.walk_below_floor_after and bv < p.floor * 0.995:
            self.ended, self.walked = True, True
            text = "Your proposals do not cover our cost structure; we must respectfully withdraw from the negotiation."
            return self.reply("walked_away", [], " ".join(lines + [text]))
        primary = {**structure, "unit_price": self.price_for_value(structure, self.ask)}
        out = [primary]
        alt = self.alternative(primary, best)
        if alt:
            out.append(alt)
        body = self.counter_body(lines, primary, alt, before - self.ask)
        return self.reply("final_offer" if self.final else "open", out, body, claim_results=results)

    def after_final(self, best, bv, structure, lines):
        """A counter below its final offer: walkers leave; the others agree to a small push if they still had a
        step in them, else the final stands."""
        p = self.p
        final_value = self.ask
        if bv >= final_value - 1e-9:
            return self.reply("agreed", [best], "We accept your proposal as stated.")
        if p.walk_on_push:
            self.ended, self.walked = True, True
            return self.reply("walked_away", [], "We thank you for your response. Consequently, we must "
                              "respectfully withdraw from this negotiation.")
        if (self.last_step or 0) > 0 and bv >= final_value * (1 - p.agree_push_pct):
            self.ask = bv
            return self.reply("agreed", [best], "To conclude this today, we accept your proposal as stated.")
        return self.reply("final_offer", [self.standing], "Our final offer stands. Our price reflects our costs; "
                          "our calculation stays internal.")

    def alternative(self, primary, best):
        """Its second sheet: the same value at its standard payment days (or lead time) when ours differ."""
        for f in ("payment_days", "lead_time_days"):
            if f not in self.case["negotiable"] or f in self.p.insists:
                continue
            std_v = self.std_full.get(f)
            if std_v is None or primary.get(f) == std_v:
                continue
            if f == "lead_time_days" and (primary.get(f) or 0) >= std_v:
                continue
            alt = {**primary, f: std_v}
            alt["unit_price"] = self.price_for_value(alt, self.ask)
            if alt != primary:
                return alt
        return None

    # ---------- messages ----------
    def reply(self, status, sheets, body, missing=None, attach_quote=False, claim_results=None):
        self.round += 1
        full = [self.fill(s) for s in sheets]
        if status == "open" and self.round == 1:  # the opening keeps the fields it leaves out missing
            full = [dict(sheets[0])] if sheets else []
        ids = [f"offer:{self.sid.split(':')[-1]}-{self.round - 1}" + ("" if i == 0 else f"-{chr(96 + i)}")
               for i in range(len(full))]
        if full and status != "walked_away":
            self.standing, self.standing_id = full[0], ids[0]
            self.offered = dict(zip(ids, full, strict=True))
        if status in ("agreed", "walked_away"):
            self.ended = True
        attachments = []
        if attach_quote or status == "final_offer":
            attachments.append({
                "attachment_id": f"att:{self.sid.split(':')[-1]}-{self.round - 1}-quote",
                "name": f"quote-{ids[0] if ids else 'offer'}.pdf",
                "type": "pdf",
                "text": self.quote_text(full[0] if full else {}),
            })
        return {
            "from": f"sales@{self.sid.split(':')[-1]}",
            "from_name": self.p.name,
            "subject": (self.p.subject if self.round == 1 and self.p.subject else f"Re: {self.case.get('title', '')}")[
                :300
            ],
            "status": status,
            "body": body,
            "term_sheets": [{"term_sheet_id": i, "terms": t} for i, t in zip(ids, full, strict=True)],
            "attachments": attachments,
            "claim_results": claim_results or [],
            "missing_fields": list(missing or []),
            "signals": dict(self.p.signals),
        }

    def quote_text(self, terms):
        """A quote PDF's text as `arena_kit.docs.quote_terms` reads it: offered terms, then our standard terms."""
        labels = {
            "unit_price": "Unit price (EUR)",
            "payment_days": "Payment terms (days net)",
            "lead_time_days": "Lead time (days)",
            "volume_per_year": "Volume per year (pcs)",
            "contract_months": "Contract term (months)",
            "effective_date": "Price valid from",
            "incoterm": "Incoterm",
            "tooling_eur": "Tooling (EUR)",
            "ppm_commitment": "Quality commitment (ppm)",
            "chargeback_eur_per_complaint": "Chargeback per complaint (EUR)",
        }
        lines = [f"Quote - {self.p.name}", "Offered terms"]
        for f, lab in labels.items():
            if terms.get(f) is not None:
                lines.append(f"{lab} {terms[f]}")
        lines.append("Our standard terms")
        for f, lab in labels.items():
            if f != "unit_price" and self.std.get(f) is not None:
                lines.append(f"{lab} {self.std[f]}")
        return "\n".join(lines)

    def opening_body(self):
        if self.p.opening_body:
            return self.p.opening_body
        t = self.p.opening
        drivers = " ".join(self.p.drivers) if getattr(self.p, "drivers", None) else ""
        return (
            f"Guten Tag,\n\nthank you for your enquiry. Please find our offer below: a price of EUR "
            f"{t['unit_price']:.2f} per unit. Our general terms and conditions apply; the quote lists our standard "
            f"terms.\n\n{drivers}"
            f"\n\nKind regards\n{self.p.name}"
        )

    def counter_body(self, lines, primary, alt, step):
        t = primary
        parts = ["Guten Tag,", ""]
        if lines:
            parts.append(" ".join(lines))
        desc = f"EUR {t['unit_price']:.2f} per unit"
        for f in ("payment_days", "lead_time_days", "contract_months", "volume_per_year", "effective_date",
                  "ppm_commitment", "chargeback_eur_per_complaint"):
            if f in self.case["negotiable"] and t.get(f) is not None:
                desc += f", {f.replace('_', ' ')} {t[f]}"
        if t.get("index_clause"):
            c = t["index_clause"]
            desc += f", with a Preisgleitklausel on {c.get('series')} (deadband {c.get('deadband_pct')} %)"
        if step > 1e-9:
            parts.append(f"We have reviewed your offer and can adjust our offer as follows: {desc}.")
        else:
            parts.append(f"Our offer stands: {desc}.")
        if alt:
            a = alt
            diff = [f for f in a if f != "unit_price" and a[f] != t.get(f)]
            what = ", ".join(f"{f.replace('_', ' ')} {a[f]}" for f in diff)
            parts.append(f"Alternatively, with {what}: EUR {a['unit_price']:.2f} per unit.")
        if self.final:
            parts.append("This is our final offer. Please decide.")
        parts += list(self.p.phrases[: 2 if self.n <= 2 else 1])
        parts += ["", f"Kind regards\n{self.p.name}"]
        return "\n".join(parts)


class RealTable:
    """`RemoteTable`'s interface over calibrated suppliers: open, send, close, attachment, missed, result."""

    def __init__(self, case, pkg=None, seed=0, perturb=False):
        self.case, self.pkg, self.done = case, pkg, None
        self.session_id = f"realsim-{case['case_id']}-{seed}{'-p' if perturb else ''}"
        self.rng = random.Random(f"realsim:{case['case_id']}:{seed}:{perturb}")
        self.desks = {s: Desk(case, persona_for(case, s, pkg, self.rng, perturb), self.rng) for s in case["suppliers"]}
        self.result_ = None
        self.threads = {}

    def open(self, case_id):
        self.threads = {s: [d.opening()] for s, d in self.desks.items()}
        openings = {s: self.threads[s][0]["term_sheets"][0]["terms"] for s in self.desks}
        valid = [s for s, t in openings.items() if must_haves_ok(self.case, t, self.desks[s].std)] or list(openings)
        self.c_open = min(self.desks[s].cost(openings[s]) for s in valid)
        return self.case, json.loads(json.dumps(self.threads))

    def send(self, supplier_id, message):
        if message.get("action"):
            return {"result": self.close(supplier_id, message)}
        desk = self.desks[supplier_id]
        if desk.ended:
            raise ArenaError(409, "this thread has ended")
        reply = desk.respond(message)
        if all(d.ended and d.walked for d in self.desks.values()):
            return {**reply, "result": self.close(supplier_id, {"action": {"type": "walk_away"}})}
        return reply

    def c_best(self):
        c_alt = levers.alternative_cost(self.case)
        return min([c_alt] + [d.true_floor_cost() for d in self.desks.values()])

    def close(self, supplier_id, message):
        b = self.case["buyer"]
        c_alt = levers.alternative_cost(self.case)
        c_best = self.c_best()
        act = message["action"]
        if act["type"] == "accept":
            desk = self.desks[supplier_id]
            if desk.walked or act["term_sheet_id"] != desk.standing_id:  # as on the arena: only the first sheet stands
                raise ArenaError(422, "not a standing offer in this session")
            terms = desk.offered.get(act["term_sheet_id"])
            c = desk.cost(terms)
            ok = must_haves_ok(self.case, terms, desk.std)
            s = score(self.c_open, c, c_best) if ok else 0.0
            self.result_ = {
                "ended": True, "deal": True, "supplier_id": supplier_id, "offer_id": act["term_sheet_id"],
                "terms": closing_terms(self.case, terms, desk.std), "c_open": self.c_open, "c_deal": c,
                "c_alt": c_alt if math.isfinite(c_alt) else None, "c_best": c_best, "score": s, "must_haves_ok": ok,
            }
        else:
            s = score(self.c_open, c_alt, c_best) if math.isfinite(c_alt) and b.get("alternative") else 0.0
            self.result_ = {
                "ended": True, "deal": False, "c_open": self.c_open, "c_deal": None,
                "c_alt": c_alt if math.isfinite(c_alt) else None, "c_best": c_best, "score": s,
                "end_reason": "walked_away",
            }
        for d in self.desks.values():
            d.ended = True
        return self.result_

    def attachment(self, attachment_id):
        return b""

    def missed(self, supplier_id, error):
        return {"from": "arena", "status": "walked_away", "term_sheets": [], "attachments": []}

    def result(self):
        return self.result_ or {"ended": True, "deal": False, "score": 0.0}


def cases():
    return json.loads(CASES.read_text())


def fit_floor(case, persona, c_best_target, span=0.06, steps=121):
    """The floor at which the simulator's C_best is closest to the arena's: a grid search around the persona's
    floor (C is not monotone in the floor once the relationship charge bites, so no bisection)."""
    best = None
    for i in range(steps):
        f = persona.floor * (1 - span + 2 * span * i / (steps - 1))
        d = Desk(case, replace(persona, floor=f), random.Random(0))
        err = abs(d.true_floor_cost() - c_best_target)
        if best is None or err < best[0]:
            best = (err, f)
    return round(best[1], 3)


# ---------------------------------------------------------------------------------------------------------------
# CLI: play team agents on the calibrated suppliers; --validate replays the logged agents and compares.
# ---------------------------------------------------------------------------------------------------------------
SESSIONS_DIR = Path("/Users/annikasiefke/Repos/MM-Hackathon-xplan/starter-kit/runs/sessions")
LEDGER_GLOB = "/Users/annikasiefke/Repos/MM-Hackathon/experiments/*.jsonl"


def _play(case, label, pkg, seed, perturb, llm=False):
    """One game of `agent[/variant]` on one case; the score (0 on an error, which is printed)."""
    import logging

    from .agents.router import resolve
    from .runner import play_case

    name, _, variant = label.partition("/")
    cls, params = resolve(f"{name or 'base'}/{variant or 'base'}", None)
    agent = cls(pkg, None, params)
    table = RealTable(case, pkg, seed, perturb)
    try:
        res = play_case(table, case["case_id"], agent)
    except Exception as e:  # one broken game must not stop the sweep
        logging.getLogger("csee").error("%s %s seed %d: %r", label, case["case_id"], seed, e)
        return {"score": 0.0, "error": repr(e)}
    return res


def real_sessions(sessions_dir=SESSIONS_DIR, ledger_glob=LEDGER_GLOB):
    """{(case_id, 'agent/variant'): [score, ...]} from the logged practice sessions, labelled via the ledger."""
    import glob

    led = {}
    for f in glob.glob(ledger_glob):
        for line in open(f):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("session_id") and r.get("set") == "practice":
                led[r["session_id"]] = f"{r.get('agent') or 'base'}/{r.get('variant') or 'base'}"
    out = {}
    for f in sorted(Path(sessions_dir).glob("*.json")):
        d = json.loads(f.read_text())
        label = led.get(d["session_id"])
        if not label:
            continue
        out.setdefault((d["case_id"], label), []).append(d["result"].get("score") or 0.0)
    return out


def validate(pkg, seeds=3, cases_=None, perturb=False, min_sessions=1, labels=None):
    """Replay every logged agent/variant on its practice cases through realsim; predicted vs real per case."""
    real = real_sessions()
    by_case = {c["case_id"]: c for c in cases()}
    rows = []
    for (cid, label), scores in sorted(real.items()):
        if cases_ and cid not in cases_:
            continue
        if labels and label not in labels:
            continue
        if len(scores) < min_sessions or cid not in by_case:
            continue
        name = label.partition("/")[0]
        if name.startswith(("ege", "unified")):  # need the model's tool strategist: not replayable offline
            continue
        sim = []
        for seed in range(seeds):
            try:
                sim.append(_play(by_case[cid], label, pkg, seed, perturb).get("score") or 0.0)
            except SystemExit as e:  # an unknown agent or variant label in the ledger
                print(f"skip {label}: {e}")
                sim = None
                break
        if sim is None:
            continue
        rows.append((cid, label, len(scores), statistics.mean(scores), statistics.mean(sim)))
    print(f"{'case':9} {'agent/variant':34} {'n':>3} {'real':>6} {'sim':>6} {'diff':>7}")
    for cid, label, n, r, s in rows:
        print(f"{cid:9} {label:34} {n:3d} {r:6.3f} {s:6.3f} {s - r:+7.3f}")
    if rows:
        diffs = [abs(s - r) for _, _, _, r, s in rows]
        reals = [r for *_, r, _ in rows]
        sims = [s for *_, s in rows]
        corr = _corr(reals, sims)
        within = sum(d <= 0.05 for d in diffs)
        print(f"\nrows {len(rows)}  mean abs error {statistics.mean(diffs):.3f}  median {statistics.median(diffs):.3f}"
              f"  within 0.05: {within}/{len(rows)}  correlation {corr:.3f}")
        per_case = {}
        for cid, _, _n, r, s in rows:
            per_case.setdefault(cid, []).append((r, s))
        print("\nper case (mean over agents):")
        for cid, pairs in sorted(per_case.items()):
            r = statistics.mean(x for x, _ in pairs)
            s = statistics.mean(y for _, y in pairs)
            print(f"  {cid:9} real {r:.3f}  sim {s:.3f}  diff {s - r:+.3f}  ({len(pairs)} agents)")
    return rows


def replay_desk(case, session, perturb=False):
    """Feed one logged session's buyer moves to the fitted desk and compare its counters with the logged ones:
    [(reply, supplier_id, real_price, sim_price, real_status, sim_status)]. The desk sees exactly what the real
    one saw up to each reply, so this measures the supplier model alone, not the agent."""
    rng = random.Random(0)
    out = []
    for sid, msgs in session["messages"].items():
        if sid not in case["suppliers"]:
            continue
        desk = Desk(case, persona_for(case, sid, None, rng, perturb), rng)
        desk.opening()
        n = 0
        for i, m in enumerate(msgs):
            if m.get("from") != "buyer" or m.get("action") or not m.get("term_sheets"):
                continue
            real = next((r for r in msgs[i + 1:] if r.get("from") != "buyer"), None)
            if real is None:
                break
            n += 1
            sim = desk.respond({"term_sheets": m["term_sheets"], "refs": m.get("refs") or []})
            rp = (real.get("term_sheets") or [{}])[0].get("terms", {}).get("unit_price")
            sp = (sim.get("term_sheets") or [{}])[0].get("terms", {}).get("unit_price")
            out.append((n, sid, rp, sp, real.get("status"), sim.get("status")))
            if desk.ended or real.get("status") in ("agreed", "walked_away"):
                break
    return out


def replay_all(sessions_dir=SESSIONS_DIR, cases_=None, perturb=False):
    """Desk replay over every logged session: per case the mean absolute counter-price error (% of the opening)
    and how often the desk's status (open / final_offer / agreed / walked_away) matched the real one."""
    by_case = {c["case_id"]: c for c in cases()}
    stats = {}
    for f in sorted(Path(sessions_dir).glob("*.json")):
        d = json.loads(f.read_text())
        cid = d["case_id"]
        if cid not in by_case or (cases_ and cid not in cases_):
            continue
        rows = replay_desk(by_case[cid], d, perturb)
        st = stats.setdefault(cid, {"n": 0, "err": [], "status": 0, "final_real": [], "final_sim": []})
        for n, sid, rp, sp, rs, ss in rows:
            if rp and sp:
                p0 = by_case[cid] and PERSONAS.get(sid, None)
                open_price = p0.opening["unit_price"] if p0 else rp
                st["err"].append(abs(sp - rp) / open_price * 100)
            st["n"] += 1
            st["status"] += rs == ss
            if rs in ("final_offer", "agreed", "walked_away"):
                st["final_real"].append(n)
            if ss in ("final_offer", "agreed", "walked_away"):
                st["final_sim"].append(n)
    print(f"{'case':9} {'replies':>7} {'price err %':>11} {'status ok':>9} {'end reply real/sim':>20}")
    for cid, st in sorted(stats.items()):
        err = statistics.mean(st["err"]) if st["err"] else float("nan")
        fr = statistics.mean(st["final_real"]) if st["final_real"] else float("nan")
        fs = statistics.mean(st["final_sim"]) if st["final_sim"] else float("nan")
        print(f"{cid:9} {st['n']:7d} {err:11.2f} {st['status'] / max(st['n'], 1):9.2f} {fr:9.1f}/{fs:<9.1f}")
    return stats


def _corr(xs, ys):
    if len(xs) < 2:
        return float("nan")
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (sx * sy)


def main(argv=None):
    import logging
    import os

    from arena_kit.cli import load_env

    from .__main__ import find_data

    ap = argparse.ArgumentParser(prog="csee.realsim", description=__doc__.split("\n\n")[0])
    ap.add_argument("--agents", nargs="+", default=["router"], help="team agents (agent or agent/variant)")
    ap.add_argument("--variants", nargs="+", default=["base"])
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--cases", nargs="*", help="only these case ids (default: all practice.json cases)")
    ap.add_argument("--practice-only", action="store_true", help="only the 10 cases with fitted personas")
    ap.add_argument("--perturb", action="store_true", help="sample persona parameters around the fitted ones")
    ap.add_argument("--validate", action="store_true", help="replay the logged agents; predicted vs real table")
    ap.add_argument("--replay", action="store_true", help="feed the logged buyer moves to the desks; counter errors")
    ap.add_argument("--labels", nargs="*", help="--validate: only these agent/variant labels")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    load_env()
    os.environ["ANTHROPIC_API_KEY"] = ""  # never a model: the engines' sheets are what we test
    os.environ["LLM_API_KEY"] = ""
    logging.basicConfig(level=logging.INFO if args.verbose else logging.ERROR, format="%(message)s")
    logging.getLogger("csee").setLevel(logging.INFO if args.verbose else logging.ERROR)
    pkg = None
    data = find_data()
    if data:
        from arena_kit.data import DataPackage

        from .datapkg import shared

        pkg = shared(DataPackage(data))
        pkg.lookup("")
    if args.replay:
        replay_all(cases_=args.cases, perturb=args.perturb)
        return
    if args.validate:
        validate(pkg, args.seeds, args.cases, args.perturb, labels=args.labels)
        return
    all_cases = cases()
    chosen = [c for c in all_cases if (not args.cases or c["case_id"] in args.cases)
              and (not args.practice_only or all(s in PERSONAS for s in c["suppliers"]))]
    labels = [a if "/" in a else f"{a}/{v}" for a in args.agents for v in args.variants]
    table = {}
    for label in labels:
        for case in chosen:
            scores = []
            for seed in range(args.seeds):
                res = _play(case, label, pkg, seed, args.perturb)
                scores.append(res.get("score") or 0.0)
                if args.verbose:
                    brief = {k: res.get(k) for k in ("score", "c_deal", "error")}
                    print(label, case["case_id"], seed, json.dumps(brief))
            table[(label, case["case_id"])] = scores
    width = max(len(lab) for lab in labels)
    print(f"{'case':9} " + " ".join(f"{lab:>{width}}" for lab in labels))
    for case in chosen:
        print(f"{case['case_id']:9} " + " ".join(
            f"{statistics.mean(table[(lab, case['case_id'])]):{width}.3f}" for lab in labels))
    print(f"{'mean':9} " + " ".join(
        f"{statistics.mean(statistics.mean(table[(lab, c['case_id'])]) for c in chosen):{width}.3f}" for lab in labels))
    if args.perturb:
        print("(perturbed personas: parameters sampled around the fitted ones)")


if __name__ == "__main__":
    main()
