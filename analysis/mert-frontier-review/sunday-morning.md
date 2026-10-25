# Sunday morning experiments, 25 October 2026

This is an experiment record, not a final-router promotion. User authorized remaining practice runs at our discretion; all runs used the csee ledger and retained the 30-session reserve.

## Position

At 06:56 CET: seventh, 79.2, leader Clooless 83.0; 192 sessions left.
After the first RFQ win: sixth, 79.6, leader still 83.0.
End of batch: 13 completed, logged practice sessions; 179 left. No practice process remains running.
The practice ranking is not the final ranking: hidden suppliers and one-shot reliability matter for the final.

## Measured results

All experiments below use template writing (`--no-llm`). Each score is one session unless indicated.

| Experiment | P05 | P08 | P18 | Decision |
|---|---:|---:|---:|---|
| Contemporary control: base/v7a for RFQ, current router for raw | .810376 | .657028 | .618181 | P18 new team best, previously .606097 |
| mert-rfq-anchor/v7a | .830636 twice | — | — | Keep isolated candidate; repeatable improvement |
| mert-rfq-lead-menu/v7a | .830636 | — | — | No incremental gain; prefer simpler anchor candidate |
| mert-raw-focused/v16 | — | .520306 | .532473 | Reject; also differs from router in parent policy, so not a single-variable test |
| router-c | — | .602909 | .618181 | No evidence to promote claim ordering on raw |
| mert-raw-long/v16a, first implementation | — | .657028 | .618181 | P08 accepted 36 months but gave no additional price concession; P18 sent unchanged terms, so it is a control |
| mert-raw-long/v16a, corrected package-stage extension | — | — | .551798 | Reject: 36 months accepted, price 5.30 versus control 5.20 |

RFQ lower anchor: 28% below own opening and 15% below rival opening, instead of 22%/8%. Other concessions and closing rules remain unchanged. Both repeat runs closed supplier 70250 at EUR 28, 30-day payment, 35-day lead. The control closed supplier 70210 at EUR 28.13; the winning supplier also has lower fixed quality cost. This is a modest gain, not enough to close the team leaderboard gap.

Repeat limitation: the first anchor session took 276.4 seconds and the second only 1.8 seconds. The fast repeat may reflect server caching; it verifies reproducibility on this path, not independent sampling of supplier variability. Do not treat two equal scores as proof of generalization.

P18 control and router-c both closed EUR 5.20, 30-day payment, 24 months, AS-14404 45% share / 5% deadband. This alone does not establish that a code change improved P18: the new best came from the existing router.

## Additional structural screens

`mert-rfq-lead-menu` adds a feasible longer-delivery cash alternative, pricing the delay penalty into the required price reduction. It preserves the established first two packages. A 56-day offer is excluded by P05's must-have.
Supplier 70240 reduced its quote on the 42-day structure, but it remained uncompetitive; the eventual winning package and score matched the simpler anchor candidate.

`mert-raw-long` extends a clause-bearing package to the longest offered contract only if modeled buyer cost does not increase. The first implementation changed P08 from round two, but the parent's sheet construction replaced the P18 change. The corrected version applies the guard after sheet construction too. Do not count the first P18 run as evidence for longer contracts.

## Implications

1. Preserve the RFQ anchor candidate. Two matching scores are better evidence than a single high score, but hidden-supplier robustness has not been established. Final router remains unchanged by this review.
2. Stop spending on the rejected raw-focused and claim-order variants. Neither beat the contemporary control. Softer raw anchors and narrower deadbands also already have negative/neutral historical evidence; do not restart those searches without a new mechanism.
3. The next major source of information is the Sunday release, scheduled by `/v1/data` for 07:00 UTC / 08:00 CET and still non-public at this check. Review new letters and market facts for changed supplier constraints, then test affected policies. `docs/SUNDAY_RELEASE.md` documents the existing ingestion path.
4. Do not mistake best-of-practice scores for expected final performance. Repeated gains and robust closing are the promotion criteria. One RFQ replay showed a supplier timeout while other bids were pending, though the best surviving offer closed successfully; no runner change was made here.
5. A wholesale switch to the team's `unified` LLM strategy is not supported by recorded experiments: P05 scores .487/.566/.540/.635, P18 .419/.567/.362/.552, P02 .588. These span different revisions and are not controlled comparisons, but none beat the current corresponding team best.

## Verification and provenance

97 targeted local checks passed before the structural screens; after the package-stage correction, all 36 focused candidate/agent checks and the two selected current-candidate smoke parametrizations passed. No shared numeric policy, final route, or curated profile was changed.

Exact session IDs, source patch snapshots and results: `experiments/2026-10-25-mert-codex.jsonl`. Full sent messages and supplier replies: the corresponding `runs/20261025-*` directories.

## Follow-up from 07:14 CET

The board and data release were unchanged. Tested two new mechanisms rather than repeating rejected variants:

- **Cash-first main sheet:** preserve the raw-material clause, place fastest payment first, and price the financing cost into the offer. Keep the original main as an alternative; do not retract previous prices. P18 finished .539481 (5.30 / 14 days / 24 months / 5% deadband), below .618181. Reject for raw materials. RFQ screen is logged separately as `mert-rfq-cash-first`.
- **Quality reciprocity:** infer the smallest positive price concession from the last four distinct supplier asks, and offer up to twice that increment per round. Stay at least one increment below the supplier's ask for this additional step, retain the normal main proposal if already higher, check must-haves, and retain normal final-offer closing. Implemented as isolated `mert-quality-reciprocal/v14a`.

40 focused tests passed, plus the selected RFQ, raw and quality candidate smoke parametrizations. No final-router changes.

**Confirmed improvement:** `mert-quality-reciprocal/v14a` closed P11 at EUR 44.50 / 300 ppm / no chargeback, score **.877127**, versus previous best .793512. Standing quote path: 47 -> 46.50 -> 46 -> 45.50 -> 45 -> 44.50 final. The case closed normally after six messages. The leaderboard moved from sixth / 79.6 to **fifth / 80.4**, leader 83.0. Supplier-specific acceptance has been measured once; hidden-case generalization remains unverified. Candidate keeps the existing final-offer stop rule.

RFQ cash-first closed .820453 (28 / 14-day payment), below the .830636 simpler anchor candidate. Reject; runner recovered from one stale-standing-offer 422 while closing. The raw cash-first and RFQ cash-first ideas are not recommended for promotion.

Quality mechanism ablation: `mert-quality-reciprocal-single/v14a` kept the reciprocal price policy but sent only the main quality sheet. Result **.709896**, EUR 45.50, versus .877127 with the menu. This is one run per arm, not a definitive causal estimate, but it argues against removing the menu or assuming larger buyer steps alone explain the gain.

Combined isolated candidate: `mert-sunday-router` inherits the current router and overrides only RFQ (`mert-rfq-anchor/v7a`) and quality (`mert-quality-reciprocal/v14a`). All other routes and fallback remain inherited. It is not selected by the final router. Broader offline paired evaluation: 19 local cases x five seeds x two routers = 190 simulated sessions; no practice quota. Targeted checks should not be represented as a live all-supplier sweep.

### Transfer check and correction

The full local sweep was slightly negative: current router mean .313349, combined candidate .308977. These simulator scores are not calibrated to hosted practice. P05 changed -.006063 on average; P11 -.038321; P12 -.038671. All other case means matched. Quality had no paired wins in either local case. **Do not promote the unconditional reciprocal rule as a general quality improvement based solely on its P11 live record.** Full paired summary: `sunday-router-simulation.json`.

Added `mert-quality-measured`: activate the larger steps only after two similar positive concessions, each 0.5-2% of the supplier's current price. Otherwise use the established quality-menu behavior. No supplier IDs or fixed price targets. This guarded policy matched the existing router exactly in all ten paired quality simulations (P11/P12, five seeds each), avoiding the unconditional rule's regressions. That does not prove performance on unseen suppliers; a fresh live P11 check tests whether the benefit survives the gate. `mert-measured-router` combines the guarded quality slot with the RFQ anchor candidate, leaving other routes inherited. 44 focused checks and three combined-router smoke parametrizations passed.

**Gate confirmed live:** `mert-quality-measured/v14a` scored **.877127** at EUR 44.50 / 300 ppm, retaining the earlier improvement. Its source uses observed increments rather than a fixed practice-case price. `mert-quality-router` is a conservative quality-only integration candidate; `mert-measured-router` includes both quality and RFQ improvements.

**RFQ transfer check, hosted sandbox D02 (free):** current router .735850, combined candidate .786399. Both closed DEMO-J1 at 14-day payment / 35-day lead / DAP; price improved from 14.14 to 13.90. This is an improvement on a second hosted RFQ scenario, supporting transfer beyond P05, though still only one comparison on D02 and the local RFQ average was slightly negative. Sandbox sessions do not affect practice leaderboard or quota.

End of follow-up: fifth, 80.4, versus leader 83.0. Five additional practice sessions (cash-first P18/P05, reciprocal quality, single-sheet quality ablation, guarded quality confirmation), two free hosted sandbox sessions, and 200 local simulated sessions. Practice quota expected 174 remaining, refreshed before final report. Final ROUTES remains unchanged. Recommended review candidate: `mert-measured-router`; use `mert-quality-router` if prioritizing the narrower change. Do not use the unconditional reciprocal router or rejected cash-first/long-contract candidates.
