# Run log format (contract between agent and dashboard)

Every run writes one folder: `runs/<run_id>/`

```
runs/<run_id>/
  run.json              run metadata (written at start, updated at the end)
  <case_id>.jsonl       one JSON object per line, one file per case session (":" in IDs becomes "_")
```

A run that plays the same case more than once (e.g. a bench playing `case:D01` three times) writes one file per
play: `case_D01.jsonl`, then `case_D01~2.jsonl`, `case_D01~3.jsonl`, ... The events inside keep the real `case_id`;
readers key a case by its file name, so the n-th play of a case lines up across runs.

`run_id` = `YYYYMMDD-HHMMSS-<agent>` (e.g. `20261024-153012-A`). `runs/` is git-ignored.

## `run.json`

```json
{"run_id": "20261024-153012-A", "agent": "A", "agent_version": "<git sha>", "set": "practice|sandbox|final|sim",
 "started_at": "2026-10-24T15:30:12+02:00", "ended_at": null, "cases": ["case:P01", "case:P02"],
 "notes": "free text"}
```

## Events (`<case_id>.jsonl`)

Every line carries the common fields, then the fields of its `type`:

```json
{"ts": "2026-10-24T15:30:14.512+02:00", "seq": 0, "run_id": "…", "agent": "A",
 "case_id": "case:P01", "session_id": "…", "type": "case_opened", …}
```

`seq` counts up per file. `ts` is real time, so a replay can reproduce the pacing.

**`Terms`** below is a term sheet: `{"unit_price": 129.9, "payment_days": 60, …}`.
**`Priced`** is `{"terms": Terms, "c": 332800.0, "breakdown": {"price": …, "uncovered_need": …, "fallback_risk": …,
"payment_terms": …, "freight": …, "late_delivery": …, "quality": …, "tooling": …, "index_clause": …, "index_risk": …,
"relationship": …}}`. The breakdown keys are exactly those of `arena_kit.cost.cost_breakdown`. Always price with the
supplier's `standard_terms` (from its quote PDF), or C will not match the arena's; the relationship term uses our
supplier estimate from the dossier (absent: 0).

| `type` | Fields | When |
|---|---|---|
| `case_opened` | `case` (full case file), `opening`: `{supplier_id: {"offer_id", "supplier_name", "priced": Priced, "standard_terms": Terms, "body"}}`, `c_alt` (C of our alternative or null) | after `POST /sessions` |
| `dossier` | `supplier_id`, `supplier_name`, `summary` (2-4 sentences), `persona` (`{"owner_type", "style", "pressures": [..], "what_moves_it": [..], "avoid": [..]}`), `floor_estimate` (€/unit), `floor_source`, `facts` (`[{"id", "text"}]`) | once per supplier, after opening |
| `specialists` | `round`, `supplier_id`, `outputs`: `{name: {"lever", "value_for_us_eur", "value_for_supplier_eur", "proposal", "claim", "note"}}` - names: `price`, `cash`, `logistics`, `quality`, `volume`, `index`, `relationship` | before each of our moves |
| `plan` | `round`, `supplier_id`, `target`: Priced, `walk_away_c`, `candidates`: `[{"id", "label", "sheets": [Priced], "claims": [{"id", "text"}], "rationale"}]` | before each of our moves |
| `decision` | `round`, `supplier_id`, `kind` (`send` / `accept` / `walk_away`), `candidate_id` (or null), `reason` (the strategist's words), `decided_in_s` | each move |
| `message_sent` | `round`, `supplier_id`, `subject`, `body`, `sheets`: [Priced], `refs`, `claims`: `[{"id", "text"}]` in the order the arena indexes them | after a send |
| `reply` | `round`, `supplier_id`, `from`, `status`, `subject`, `body`, `standing`: `{"offer_id", "priced": Priced}`, `claim_results` (`[{"index", "result", "ref"?}]`), `missing_fields`, `signals`, `attachments` (`[{"attachment_id", "name", "type"}]`), `latency_s` | each supplier reply |
| `error` | `supplier_id` (or null), `status` (HTTP), `detail` | 409 / timeout / exceptions |
| `result` | (`end_reason` is not in the accept reply: fetch it from `GET /sessions/{sid}`) `deal`, `supplier_id`, `offer_id`, `terms`, `c_open`, `c_deal`, `c_alt`, `c_best`, `score`, `cost_breakdown`, `end_reason`, `replay_url`, `must_haves_ok` | case end |
| `trace` | `trace` (the arena's list, as returned) | after the end, when available |
| `backoffice` | `messages` (as returned) | after the end, when available |

`round` = the number of our messages already sent in that thread + 1; an accept or walk-away gets the round it happens in
and no `message_sent`. `supplier_name` is the company name, not the `from` role. `agent` may contain dashes.

Unknown `type`s must be ignored by readers. New fields may be added; existing ones don't change meaning.
