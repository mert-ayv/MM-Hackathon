# Supplier profile schema (one JSON file per supplier: `<supplier digits>.json`, e.g. `70110.json`)

Built offline from the data package (as of 2026-09-30). Read by the csee buyer agent before a session opens.
Every factual statement must point to IDs that exist in the data package. No invented facts.

```json
{
  "supplier_id": "sup:70110",
  "name": "...", "category": "...", "country": "DE",
  "owner_type": "family|group|founder|private|...", "group_parent": null, "staff": 185, "turnover_eur": 25800000,
  "our_spend_fy2026_eur": 0, "our_share_of_their_turnover_pct": 0.0,
  "parts": [{"part_id": "part:...", "name": "...", "current_price": 0.0, "price_unit": 1, "quota_pct": 100,
             "qualified_alternatives": ["sup:..."], "should_cost_id": "cost:...", "should_cost_unit": 0.0}],
  "contract": {"id": "ctr:...", "valid_to": "...", "payment_days": 30, "incoterm": "FCA", "notice_days": 90,
               "index_clauses": [{"id": "ctr:...#x.y", "series": "...", "material_share": 0.0, "deadband_pct": 0.0}]},
  "standard_terms_hint": {"payment_days": 30, "incoterm": "FCA", "lead_time_days": 42, "skonto": null},
  "quality": {"latest_scorecard_id": "sc:...@2026Q3", "otd_pct": 0.0, "ppm": 0, "colour": "green", "trend": "...", "open_8d_overdue": 0},
  "payment_behaviour": {"avg_days_late_by_us": 0.0, "note": "..."},
  "financial_health": {"equity_ratio_pct": 0.0, "credit_index": 0, "credit_index_12m_ago": 0, "signal": "..."},
  "negotiation_history": {"events": 0, "avg_asked_pct": 0.0, "avg_settled_pct": 0.0, "settle_to_ask_ratio": 0.0, "notes": ["..."]},
  "situation": "3-5 sentences: what is going on with this supplier right now",
  "pressures": [{"type": "cash|capacity|utilisation|volume|energy|labour|quality|succession|ownership|competition|other",
                 "evidence": "...", "ids": ["doc:...", "news:..."]}],
  "what_it_values": ["ordered list, most important first, e.g. faster payment, volume security, long contract"],
  "likely_tradeables": [{"lever": "payment_days|contract_months|volume_per_year|effective_date|incoterm|lead_time_days|index_clause|ppm_commitment|chargeback_eur_per_complaint|tooling_eur|unit_price",
                         "give": "what we could give", "get": "what we could get", "why": "...", "ids": ["..."]}],
  "arguments_that_should_land": [{"argument": "...", "ids": ["..."], "why": "..."}],
  "arguments_to_avoid": [{"argument": "...", "why": "..."}],
  "persona": {"who_writes": "...", "style": "...", "decision_making": "...", "relationship_notes": "..."},
  "noise": ["documents or facts that look relevant but are not"],
  "key_quotes": [{"id": "doc:...", "quote": "short verbatim quote"}],
  "confidence": "high|medium|low"
}
```
