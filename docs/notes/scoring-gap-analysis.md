# Where our C loses against C_best (practice, Sun 25 Oct 08:30)

Source: `result` events in local `runs/*` (94 practice sessions with cost breakdowns), the team ledger
(`experiments/*.jsonl`, 198 practice rows), the public board (`/v1/live`), `arena_kit.cost`. Script output:
lever-by-lever decomposition of our best and latest deal per case (payment, lead time, Incoterm, ppm/chargeback,
index clause, effective date, volume/months set to the cheapest option we were allowed, price held).

## Standing (mean of best scores, 13 teams)

Clooless 0.830 · winsortf 0.824 · Hack It 0.810 · Janteiros 0.809 · **csee-base 0.806 (5th)** · RGV 0.803 · ...
Our router's *repeated* mean is lower: router runs n=44 mean 0.749, router-x 0.757 (ROUTES comments promise 0.796
from cherry-picked bests). Realistic final ≈ 0.76-0.78 per case ≈ 380-390 of 500 points.

| case | type | house | record (holder) | our best | router mean (n) | gap to C_best € (share of range) | lever waste € | price gap € | C_best implies |
|---|---|---|---|---|---|---|---|---|---|
| P01 | price_increase | 0.97 | 1.000 (Hack It) | 0.988 | 0.972 (8) | 2.6k (4 %) | 14k pay (traded for price: fine) | - | ~133.4 @ 90 d vs our 133.9 @ 30 d |
| P02 | price_increase | 0.74 | 0.875 (Janteiros) | 0.735 | 0.733 (6, sd 0) | 12.7k (27 %) | **17.7k index clause** | - | **no clause at ~366** vs our 362 + CU clause |
| P03 | renewal | 0.92 | 0.963 (Clooless) | 0.923 | 0.921 (6) | 26k (8 %) | 0 | 26k | 429.4 vs our 432.15 |
| P04 | renewal | 0.86 | 0.874 (Clooless) | 0.860 | 0.860 (6, sd 0) | 0.3k (14 %) | 0 | 0.3k | 4.93 vs our 4.94 (one cent) |
| P05 | rfq | 0.56 | 0.924 (AEIOU) | 0.854 | 0.776 (7, sd .04) | 15.6k (19 %) | 3k pay | 12k | 26.6 @ 90 d vs our 28.13 @ 30 d |
| P07 | bundling | 0.78 | 0.805 (certivity) | 0.766 | 0.740 (7) | 24k (26 %) | 0 | 24k | 5.02 vs our 5.42 |
| P08 | raw_material | 0.75 | 0.892 (Clooless) | 0.744 | 0.695 (8, sd .05) | 45k (26 %) | 9k index clause | 36k | 5.10 no clause vs our 5.29 + clause |
| P10 | capacity | 0.69 | 0.718 (winsortf) | 0.686 | 0.661 (7) | 189k (31 %) | 29-34k late delivery (54/56 d vs 42) | 160k | 28.1 vs our 31.5 |
| P11 | quality | 0.31 | 0.877 (RGV) | 0.877 | 0.61 (7, one 0 = laptop sleep) | 20k (21 %) | 2k chargeback 0 vs 500 | 17k | 43.9 vs our 45.0 |
| P18 | raw_material | 0.39 | 0.767 (winsortf) | 0.618 | 0.560 (8) | 32k (45 %) | 3k pay 30 d, 2k clause | 27k | 4.73 vs our 5.30 |

Where the record holders beat us by more than noise: P02 (-0.14), P08 (-0.15), P18 (-0.15), P05 (-0.07). All three
big ones are index-clause cases.

## Findings

1. **The arena's breakdown hides the relationship term.** `cost_breakdown.relationship` is 0.0 in current result
   payloads, but C includes it: P02 32.2k, P01 5-9k, P03 0.5-1k. Derive it as `c_deal - sum(other parts)`.
   On P02 the arena-implied full cost of Nordmark is ~366.7 €/u (`relationship_cost` fitted to 32.2k at rate 8 %):
   at 362 we pay it 2.7 margin points *below cost*, 3.2 points below the sustainable 0.5 %.
2. **P02: the copper clause is the whole gap.** What-if at the same supplier estimate (90 d): no clause at 362-364
   scores 1.0, 366 → 0.99, 368 → 0.87, 370 → 0.70. Keeping the clause: 362 → 0.733 (our deal), every other price
   worse. C_best ≈ "no clause at the supplier's sustainable-margin price" - a sheet Nordmark should accept.
   Our round-1 mail offered 358.48/no clause, **362/clause** (planner: "index_clause -> 362.0 acceptable (p_ind
   360.38)"), 351.61/30 d; the bot took the clause sheet at once ("we can accept your terms"). 1 round of 10 used,
   identical 0.733 in 6 runs. Fix: price the clause sheet at the no-clause price *minus* the clause's cost to us
   (17.7k/6110 = 2.9 €/u), never above it; open the no-clause sheet near the estimated full cost + sustainable
   margin (not below full cost: the relationship term makes paying 4 € more almost free here).
3. **Our ask sets the deal.** Bots accept our own sheets when those are at/above their reservation: P02 round 1,
   P05 round 2 (Dralveck "clarified internally and can move further" - then agreed to our 28.13 trade sheet; its
   floor is ~26.6), P04/P08/P10 close after 2 messages. Round limit is 10 everywhere; our p90 session time is
   257 s of ~390 s usable in a wave. We leave the ask-to-floor distance on the table whenever the second offer is
   already acceptable.
4. **Final offers are taken at face value** (`push_after_final = 0`). P07: Leitner stepped 5.74 → 5.58 → 5.49 →
   5.45 → 5.42 "final" at round 4 while its floor is 5.02 and our own offers (5.05-5.26) were all above that
   floor. P08: "final" at reply 2 (5.29, floor ~5.10). P18: "final" at reply 3 (5.40/5.30, floor ~4.7). The
   bot's step mirrors ours; a smaller/slower step or a hold costs a round, not the deal. Only the P02 v15 push
   caused a walk - on a bot that had *already agreed*. Test a guarded single push (`final_push` 0.5-1 %) on
   bots that are still above their previous quote / the should-cost.
5. **Raw material (P08/P18): price, not levers.** Both bots insist on the clause for 24 months ("cannot offer a
   fixed price over 24 months"), so C_best probably keeps it; the 36k/27k gaps are price. Verified index claims
   moved them one step each (AS-14404 -5.5 %, PPI-C2431 -2.1 %); PO history did nothing ("does not change our
   calculation"). No should-cost exists for these parts (profile `should_cost_unit: null`) so the agent has no
   floor and accepts the first "final". Records: 0.892 / 0.767 → someone gets ~5.13 / ~5.0.
6. **P10: the desk moves 2 % at a time.** Price gap 160k (31.5 vs ~28.1), lead-time penalty 29-34k is the
   cheaper choice (42 d costs ~94k in price). Every run ends after 2 messages at a final offer. The escalation
   path (committee pacing, `xc_pace` in feat/xplan-decide) is the only route to the record (0.718 ≈ 31.0 @ 56 d).
7. **P04: `close_gap = 0.004` of C swallows a third of the range.** The whole P04 range is 2.3k (1.2 % of C);
   0.4 % of C = 787 € tolerance, deal ends one cent (323 €) short of C_best. Scale the tolerance to the room
   (`close_room`, v17 has 0.001/0.05) on routine renewals with a tiny range.
8. **P11 chargeback.** 500 € chargeback ≥ cost_per_defect 450 zeroes the quality term (2.1k); we closed with 0.
   Small, but it is a free lever if the bot's price does not move with it.
9. Fine as they are: P01 (early payment traded for price, 0.93-0.99), P03 (0.92, price only), P11 at 0.877.

## Robustness

One 0 in 198 rows from a 3163 s session (laptop sleep, fixed with caffeinate). No run over 390 s otherwise
(p90 257 s, P05 three threads up to 353 s). 7 zero/no-deal rows total, all on retired agents.
