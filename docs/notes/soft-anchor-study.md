# Soft-anchor and real-cost study (Sat 24 Oct, 21:00-22:00, 7 practice sessions, Mert's session)

Question: three bots end our negotiations early (Werdenfels P18 final at reply 3, Ravensteiner P10 final at
reply 1, Nordmark P02 agrees at reply 1). Is our first ask the cause, and is there money in moving it?

| Case | Arm | Result | vs. before |
| --- | --- | --- | --- |
| P18 | planner, raw anchor 12 % (default gaps) | 0.480: the bot "agreed" to our own 90-day MESO sheet at 5.48 | 0.552 at 22 % |
| P18 | raw anchor 15 % + tight gap budget (8/5/3 %) | 0.467: agreed to our 5.50 @ 90 d | |
| P18 | raw anchor 18 % + tight gap budget | 0.546: agreed to our 5.38 @ 90 d | |
| P10 | planner, 4 % anchor (mert-plan-softrel) | 0.601: bot "open" 33.60 @ 42 d, then final 33.20 @ 42 d | 0.57 / 0.671 at 12 % |
| P10 | planner-dossier, 6 % anchor (mert-plan-soft) | 0.601: same path | |
| P10 | base/v14s (4 % anchor) | **0.679**: bot "open" 33.60 @ 42 d; we switched to 56 d, final 31.50 @ 56 d | best P10 so far |
| P02 | relationship sheets at should-cost x 0.965 (v14r) | 0.730: 360.38 @ 90 d + CU clause agreed at reply 1 | 0.733 at 362 |

## What it means

- **P18: the 22 % raw anchor is at the optimum.** Softer asks make Werdenfels give less in reply 1 (5.70 instead
  of 5.60) and then *agree to our own sheet* before it reaches the 5.30 it ends at against a deep ask. mert-anchor's
  30 % (15:36) was also worse (0.49). The 0.688 record (Hack It, ~5.10-5.20) is not reachable through the price path;
  it has to be structural (payment days / deadband; see `PlanMesoRaw` docstring). Stop tuning the P18 anchor.
- **P10: lead time is the lever, not the anchor.** Ravensteiner charges ~EUR 2.00/unit for 42 instead of 54-56 days;
  14 late days cost us EUR 2,400/day = 0.71/unit. A 4-6 % anchor keeps it "open" for one reply, but the planner then
  insists on 42 days and takes a final 33.20. base's `adopt_revealed` switched to its 56-day sheet and closed 31.50.
  Router: `capacity -> base-d/v14s`. Realistic ceiling here is ~0.69 (record 0.694); nobody has beaten the bot's floor.
- **P02: Nordmark's real cost is at or above should-cost x 0.98.** A 1.6 EUR lower clause sheet was accepted just the
  same, and the arena's relationship charge grew by exactly the saving (C_deal 2,248,294 vs 2,248,166). The record
  0.854 (C ~2,242k) is 5.7k below us: with the clause we pay index_risk 17.7k; a no-clause deal ~1 % dearer in price
  would avoid it, but every no-clause run so far ended 0.44-0.47 (the bot settles ~369 without the clause offer).
  Do not route v14r. Candidate for Sunday if quota allows: offer the clause sheet only as the third option and a
  no-clause sheet at ~365-366 @ 90 d first.

## Noise floor (for every slot decision)

The identical agent scored 0.81 and 0.748 on P05 in the two router A/B runs (20:43) and 0.70-0.754 over four P08
runs. Treat single-run differences under ~0.08 as ties; prefer the mechanism argument (why it should generalise to a
supplier we have not met) over the score.

## Cross-supplier patterns in all of Saturday's practice logs (296 supplier replies, 22:50)

**Which arguments move a price.** Parsed from the bots' own wording ("it holds and we took it into account" vs
"it holds, but it does not change our calculation"):

| Claim kind | cited | moved the price |
| --- | --- | --- |
| should-cost (`cost:`) | 11 | 11 (100 %) |
| notice period (`doc:` + `ctr:`) | 6 | 6 (100 %) |
| rival quote / alternative quote | 5 | 5 (100 %) |
| index change (`idx:` pair) | 44 | 41 (93 %) |
| demand forecast (`fc:`) | 26 | 23 (88 %) |
| quality record (`qn:` complaints) | 12 | 9 (75 %) |
| delivery record (`sc:` on-time %) | 37 | 14 (38 %) |
| **order history (`po:` prices)** | **26** | **0 (0 %)** |
| earlier-quarter delivery | - | always "duplicate" (12 of the 13 duplicates) |

No citation came back `contradicted` or `irrelevant`. We led round 1 with a delivery claim 49 times and spent
29 round-2/3 slots on order history. `Params.claim_evidence` (on in every routed variant: v14a, v16a, v7a,
basea, v14s) drops order history and the earlier-quarter delivery claim, floors index at 1.8 and forecast at
1.5, and scales the delivery record by 0.4, so index / forecast / should-cost / notice go first and the
delivery record is a filler. Mixins that reorder afterwards (dossier: hedged index last) keep the last word.

**When concessions are wasted.** After we moved, the supplier gave nothing in 33 % of replies, rising with the
reply number: reply 2: 17 %, 3: 20 %, 4: 43 %, 5: 67 %, 6: 80 %. Steps under 0.5 % of the price were held 40 %
of the time, steps of 2 % or more 22 %. Median mirror: the supplier gives 0.41 of our step. The mode of the
final offer is reply 3 (20 of 62), with a median gap of 6 % between its price and our ask at that moment.
Lesson for every slot: be within closing distance by reply 4, never dribble sub-tick steps late, and stop
after two holds (the planner's `frozen_after` rule). v7c / v14c (concede_early 0.35) are a sandbox A/B of
front-loading for the base slots.

**Instant agreements.** Five "agreed" at our first message, all P02 (the clause sheet). Other agreed-at-reply-2+
cases landed our ask 2-6 % below the supplier's previous price (P05, P10, P18 soft arms): the supplier would have
moved at least that far anyway, so those asks were at or above its next step.

**Round confound check** (2b's objection: order history is a round-2+ argument, where suppliers hold anyway).
Within the same reply number the ranking holds: round 1 delivery record 16/37 (43 %) vs index 36/39 (92 %),
should-cost 11/11, forecast 23/26, quality record 9/11; round 2 index 8/8 vs price history 0/9; round 3 price
history 0/12. The wording is the bot's own per-claim verdict, not whether it moved in that reply.

**Status (Sat 23:10):** `claim_evidence` lives only in the c-variants (v14c, v16c, v7c, basec, v14sc); ROUTES stay
on the confirmed variants (0.772). Plan: Sunday morning, same hour, confirmed router vs a router on the
c-variants; switch only above the +0.06 noise. The concede_early 0.35 sandbox A/B was inconclusive
(D01 +0.05/+0.01, D02 -0.04/+0.02) and was dropped.
