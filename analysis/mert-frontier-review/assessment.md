# Winning assessment — 24 October, evening

Read-only arena refresh: csee-base rank 4, mean 0.783; Janteiros 0.806, Hack It 0.800,
Clooless 0.787. Team practice use 145/400, 255 left at the snapshot. No practice
sessions launched by this review. No router or agent changes.

## Decision

Keep the hybrid architecture. Stop broad anchor sweeps and concentrate on package
structures that have enough mathematical headroom. Do not infer final strength
from the mean of historical bests: the final gives one attempt per case and new
suppliers. Evaluate a frozen router on repeatability, worst cases and deadline closure.

## P02: the current package has a score ceiling

Completed results e12ba8b1ded8b5f0 and 62b13173901fbf62 allow inversion of the
published relationship-cost function. Assuming the published standard 30-day
terms and the same supplier economics across these results, inferred full cost is
367.60 EUR/unit and money rate is 6.6%. An independent result,
73187498592c7c94, is reproduced within one cent of total cost. Two further fixed-price
results (e0596aadc1480451, 8c79a11bc3f797f3) also matched to rounding in the review.

At 90-day payment and the CU-NOTATION clause (20% share, 5% deadband), the optimal
price is approximately 361.33 and the maximum modeled score is 0.7354. Current best
0.7328 is essentially at that ceiling. Lowering price to 360.38 increased the
relationship penalty enough to erase the purchase saving. Earlier payment makes
this package worse: the supplier's inferred 6.6% money rate is below our 8%.

The promising target is a FIXED price: 368.00 at 90 days scores approximately
0.8654. Acceptance is unknown. Fixed-price bargaining was tried previously, so the
new experiment is a calibrated, less aggressive fixed-price target and deliberate
choice between fixed/indexed packages, rather than immediately supplying a clause
alternative the supplier can accept at our 0.733 ceiling. Preserve the clause
fallback while the supplier is open; do not push a final offer. Do not hard-code
this supplier's inferred parameters into unseen final suppliers.

## P11: offer quality commitment alternatives

In the local practice sent-message logs inspected, all 36 P11 sheets specify
300 ppm and zero chargeback. The case allows 300, 800 and 1500 ppm under its
must-have; 2500 would fail. Payment and volume are fixed, despite repeated supplier
requests to change them. The writer also sometimes declines to state volume even
though the case supplies the fixed quantity; this is a context defect, not evidence
that a payment promise will improve the score.

Compare these valid packages (zero chargeback, fixed remaining terms):

| Price | ppm | Score if accepted |
| --- | ---: | ---: |
| 45.50 | 300 | 0.7099 |
| 45.00 | 300 | 0.7935 |
| 44.77 | 800 | 0.7943 |
| 44.46 | 1500 | 0.7935 |

Offer a small, explicit menu of quality/price tradeoffs. This targets the supplier's
complaint about a strict quality promise while preserving buyer value. Our local
supplier-value model prices actual defects, not the promise, so it cannot validate
the bot's willingness to trade a weaker commitment. Acceptance remains unproven.

## P18: search the joint payment/clause/contract space

Our new best, session 5973647fae7d659a, is 5.30 at 90 days, 24 months, AS-14404
45% share/5% deadband, scoring 0.5980. Earlier 5.30 at 30 days scored 0.5518.
The new best is therefore a meaningful package improvement, not just a price cut.

Local sent-message logs show mostly 14/30/90-day payment and 5% deadband. Audit all
allowed combinations, including 45/60 days and a 3% deadband, then offer diverse
competitive packages. A different clause is not inherently better: at 5.10,
45 days/3% deadband scores 0.6657, whereas 90 days/5% scores 0.7290. Require the
supplier's price discount to pay for every added index/payment cost. A 12-month
contract leaves unmet need and is not a free concession.

## Experiment order and stopping rules

1. Build isolated package candidates and score every proposed sheet offline.
   Validate must-haves, fixed terms, coverage and concession continuity. Keep the
   final router unchanged. Start with P11's quality menu, then P02's calibrated
   fixed-price branch; P18 needs a broader package frontier.
2. Use sandbox D01/D02 only for integration, multi-sheet handling and closure.
   Neither is a substitute for acceptance evidence on P11 or P18. Do not interpret
   a fitted local simulator's score as confirmation of a large live gain.
3. When a candidate is concrete, request approval for a single targeted practice
   screen. No approval is assumed here. Replicate a successful result before
   promotion. Reject a candidate that achieves gains by ignoring fixed terms,
   accumulating relationship cost or risking final-offer walks.
4. Rehearse the final runner locally with concurrent cases, waits, resume and caps.
   Rebuild and check dossiers after Sunday's release. Favor a repeatable policy
   on unseen suppliers over supplier-specific practice constants.

Matching current records on P02/P11/P18 alone would move the mean to about 0.812.
That would beat the observed 0.806 leader, but competitor scores can move and none
of these acceptance gains is guaranteed. Practice does not determine final rank:
https://arena.tacto.ai/faq

`offline_frontier.py` reproduces the key score calculations without network access.
