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
