"""Soft profile fields from the supplier's own words (LLM), checked against the data package."""

import json

from . import facts, llm, sources
from .common import SCHEMA
from .verify import Checker

PRESSURE_TYPES = [
    "cash",
    "capacity",
    "utilisation",
    "volume",
    "energy",
    "labour",
    "quality",
    "succession",
    "ownership",
    "competition",
    "other",
]
LEVERS = [
    "payment_days",
    "contract_months",
    "volume_per_year",
    "effective_date",
    "incoterm",
    "lead_time_days",
    "index_clause",
    "ppm_commitment",
    "chargeback_eur_per_complaint",
    "tooling_eur",
    "unit_price",
]

S = {"type": "string"}
IDS = {"type": "array", "items": S}


def obj(**props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def arr(item):
    return {"type": "array", "items": item}


PRESSURE = obj(type={"type": "string", "enum": PRESSURE_TYPES}, evidence=S, ids=IDS)
TRADEABLE = obj(lever={"type": "string", "enum": LEVERS}, give=S, get=S, why=S, ids=IDS)
ARG_LAND = obj(argument=S, ids=IDS, why=S)
ARG_AVOID = obj(argument=S, why=S)
QUOTE = obj(id=S, quote=S)
PERSONA = obj(who_writes=S, style=S, decision_making=S, relationship_notes=S)
SOFT_SCHEMA = obj(
    situation=S,
    pressures=arr(PRESSURE),
    what_it_values=arr(S),
    likely_tradeables=arr(TRADEABLE),
    arguments_that_should_land=arr(ARG_LAND),
    arguments_to_avoid=arr(ARG_AVOID),
    persona=PERSONA,
    noise=arr(S),
    key_quotes=arr(QUOTE),
    confidence={"type": "string", "enum": ["high", "medium", "low"]},
)

SYSTEM = """You are the procurement analyst of Hollerau Pumpenwerke (a pump maker, the buyer). You write the
negotiation profile of one supplier that our autonomous buyer agent reads before it negotiates by e-mail.

Rules:
- Use ONLY the material given. Never invent facts, numbers or IDs. Every factual claim points to IDs that
  appear verbatim in the material (doc:, news:, quote:, ctr:...#x.y, cost:, sc:, idx:, rfq:, part:, sup:).
- Some documents are noise (holiday shutdowns, certificates, trade fairs, apprentices, new directors without
  consequences): list them under `noise` and do not build pressures on them.
- The supplier's own words in letters, e-mails, call and meeting notes are the strongest evidence of what
  moves it. Name the lever it would trade (payment days, contract length, volume, effective date, ...).
- Negotiation-history event IDs (EV-...) are NOT citable: use past asks/settlements to judge the supplier
  (situation, tradeables), not as arguments.
- Arguments that should land must be checkable data arguments (figure + IDs). Arguments to avoid are those
  that would backfire (e.g. index moves that support the supplier's ask, empty threats to move volume).
- key_quotes: short quotes copied CHARACTER FOR CHARACTER from one document (no paraphrase, no ellipsis),
  with that document's ID.
- Be concise and concrete: situation 3-5 sentences; 2-5 pressures; 2-4 tradeables; 2-4 arguments each.
- confidence: high if the supplier's own documents clearly show what it wants, medium if partly, low if
  there is little supplier-specific evidence."""


def market_items(pkg, exclude=()):
    refs = [r for r in pkg.ids("news:") if r not in exclude and not sources.item_supplier(pkg, r)]
    return [(r, sources.item_meta(pkg, r), sources.item_text(pkg, r)) for r in refs]


def prompt(pkg, supplier, hard, exclude=()):
    items = sources.supplier_items(pkg, supplier, exclude)
    known = [r for r, _, _ in items]
    parts = [
        "Profile schema for reference:\n" + SCHEMA.read_text(encoding="utf-8"),
        "HARD FACTS (computed from the ERP, already correct; do not repeat them, use them):\n"
        + json.dumps(hard, ensure_ascii=False),
        "CITABLE FACTS (ID: value):\n" + "\n".join(sources.citable(pkg, supplier, hard)),
        "ALTERNATIVE SUPPLIERS ON ITS PARTS: " + json.dumps(sources.rivals(pkg, hard), ensure_ascii=False),
        "SUPPLIER DOCUMENTS AND NEWS (oldest first):\n" + sources.render_items(items),
        "MARKET NEWS (not supplier-specific):\n" + sources.render_items(market_items(pkg, exclude)),
        "Write the soft fields of the profile as one JSON object.",
    ]
    return "\n\n".join(parts), known


def check(pkg, soft, known):
    c = Checker(pkg, known)
    out = dict(soft)
    out["situation"] = c.text(soft.get("situation", ""), "situation")
    out["pressures"] = c.entries(soft.get("pressures"), "pressures")
    out["likely_tradeables"] = c.entries(soft.get("likely_tradeables"), "likely_tradeables", need_ids=False)
    out["arguments_that_should_land"] = c.entries(soft.get("arguments_that_should_land"), "arguments_that_should_land")
    out["arguments_to_avoid"] = [
        {k: c.text(v, "arguments_to_avoid") for k, v in a.items()} for a in soft.get("arguments_to_avoid") or []
    ]
    out["what_it_values"] = [c.text(v, "what_it_values") for v in soft.get("what_it_values") or []]
    out["noise"] = [c.text(v, "noise") for v in soft.get("noise") or []]
    out["persona"] = {k: c.text(v, f"persona.{k}") for k, v in (soft.get("persona") or {}).items()}
    out["key_quotes"] = c.quotes(soft.get("key_quotes"))
    return out, c.log


def build(pkg, supplier, model, exclude=()):
    """(full profile = hard + checked soft, log, cost row)."""
    hard = facts.build(pkg, supplier)
    user, known = prompt(pkg, supplier, hard, exclude)
    soft, row = llm.call_json(SYSTEM, user, SOFT_SCHEMA, model, label=f"soft {supplier}")
    soft, log = check(pkg, soft, known)
    return {**hard, **soft}, log, row
