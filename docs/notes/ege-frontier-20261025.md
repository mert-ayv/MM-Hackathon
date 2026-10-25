# Sunday frontier review, Ege, 25 October 2026

All times CET. Ongoing experiment record; no new candidate below is promoted.

At 10:44 the official practice board had csee-base fifth at 80.6, behind
Clooless at 83.7 (83.1 at 10:10). Best case scores: P01 .9876, P02 .7354, P03 .9228,
P04 .8604, P05 .8543, P07 .7665, P08 .7544, P10 .6865, P11 .8771,
P18 .6182. The practice board uses historical bests; the Live Final is a
single attempt on unseen cases. First place on the practice board does not
win the hackathon.

## Repository and runtime

- Pulled main from `1e66829` to `57a6633`, then to `abb2355` after the first
  experiments completed, then to `23ee3e8` (video work and experiment ledger).
  Preserved existing local raw-policy/economic work.
- The second pull contains the team's raw-route promotion from v16a to v16c,
  the defensive standard-terms parser, dashboard work and new experiment rows.
- Found that this machine's configured `data/package` path did not exist;
  the agent correctly fell back to the checked-in `data/` package, but **no
  Sunday release was loaded**. Downloaded the official release and installed
  it at `data/release-sunday/`: 10 new facts, 10,366 merged facts. Verified
  the 2027 steel hedge and new cash requests through the dossier loader.
- The final runner remains assigned to Mert's MacBook by `docs/RUNBOOK.md`.
  This machine has not started a second final runner.

## Measurements

| Candidate | Change | Case | Score | Session | Decision |
|---|---|---|---:|---|---|
| ege-raw-final/v16a | One 2% final counter after >=2% observed supplier concession | P08 | .0000 | 3df1ea986a3c8718 | Reject: supplier walked |
| ege-raw-final/v16a | Same | P18 | .5200 | a6b1013832471720 | Reject |
| ege-raw-deadband/v16a | Narrower positive index deadband before planner pricing | P08 | .5502 | a9058c635bbd8a14 | Reject |
| ege-raw-deadband/v16a | Same | P18 | .6061 | a4c66840ec3cb644 | No improvement; supplier chose a 5% clause |
| ege-rfq-deep/v7a | RFQ anchor 35% below own / 22% below rival opening | D02, free | .4494 | See sandbox ledger | Reject |
| router | Contemporary RFQ control | D02, free | .7653 | See sandbox ledger | Retain |
| ege-raw-index-menu/v16c | Same-cost index-only menu, unchanged routed main | P08 | .5155 | See practice ledger | Reject |
| ege-raw-index-menu/v16c | Same | P18 | .5206 | See practice ledger | Reject |
| ege-renewal-staged/v14a | One independent claim per message | P03 | .9228 | b2f07ba2ebab1821 | Ties baseline, no promotion |
| ege-raw-forecast/v16c | Current positive forecast below 3%, AI writer | P08 | .6895 | cfdd35146c7e5f30 | Control .5813; writer timeout confound |
| ege-raw-forecast/v16c | Same, AI writer | P18 | .5518 | 4dfc15db3a6456f7 | Ties contemporary control |
| ege-raw-forecast/v16c | Same, template replication | P08 | .6570 | c40050c7b7961804 | Control .6029; gain repeats |
| ege-raw-forecast/v16c | Same, template replication | P18 | .6182 | 237ffc9aa62fa6ff | Ties contemporary control |

The final-counter result repeats a risk already documented for mert-gatedpush
in `docs/ARCHITECTURE.md` (P18 `afada094`); the older rejection was located
during this screen. Do not run further final-push variants on this evidence.

The narrower-deadband experiment also changed the inherited payment menu:
its main clause was set before sheet generation, so alternatives retained it.
It therefore does not isolate the value of index protection. The following candidate,
`ege-raw-index-menu`, keeps the routed main sheet and offers narrower clauses
at equal buyer cost with identical payment and contract duration. Compare it
against the current v16c router in the same time window. Its screen also failed.

`ege-renewal-staged` tests one argument per turn on P03. Completed replays show
the supplier freezing price after the opening, where the current policy sends
both should-cost and forecast evidence. This is an evidence-timing experiment,
not a different target price or a post-final counter.

The index-menu controls were refused at session creation (HTTP 429, 10 open
sessions per key), not failed negotiations. Do not score those as zero deals or
retry while teammates occupy the cap. A subsequent read-only check found one
open practice session and no sandbox sessions. The index menu did not improve
either case, so no additional controls are needed for that rejected candidate.

At 10:38 a more concrete evidence omission was found: the latest raw-part
forecast is +1.9% (`fc:370010@2026-09`), but the shared generator requires >=3%.
`ege-raw-forecast` admits positive current forecasts below 3% after the leading
useful index claims. It changes no price, package, concession or close rule.
Offline inspection confirms P08 uses index, forecast, delivery; P18 uses two
indices then forecast. The claim states the actual growth and does not promise
more volume than the case allows. Both suppliers explicitly verified the forecast
and said they took it into account. In two paired screens, P08 improved by .1082
(AI writer) and .0541 (templates), P18 tied both times. The AI control had two
writer timeouts, so the template replication was essential. This is still a small
sample, below the historical P08 best, and does not establish hidden-case gain.

At 10:49 `ege-raw-reciprocal` tested the same evidence on the earlier reciprocal
price policy (`mert-skiphedge-d/v16c` control). The older raw best held a wider
price gap than today's planner. Both candidates preserve ordinary closing and
never counter a final offer. P08 scored .7328 versus .7220 for its paired
control; P18 tied at .5518. Across three paired comparisons, the forecast
helped P08 and tied P18 every time, but none set a new historical team best.

## Validation and limits

The initial router with the Sunday release passed 181 smoke parametrizations.
Each candidate passed its 30 agent/variant smoke parametrizations before its
live screen. Focused checks verify final/agreed status guards, one-push limits,
coverage, complete packages, and buyer-cost limits on the index menu. New code
passes Ruff. After the second pull, standard-terms and frontier/feedback tests
passed (33 tests).
After the latest parser/runner changes, 199 runner, standard-terms and router
checks passed. The forecast candidate passed 38 focused/smoke checks and Ruff.

The local simulator's raw scores (~.25) are not calibrated to hosted scores
(~.55-.75), and it cannot validate the supplier's valuation of index insurance.
Offline package validity and equal cost are construction checks, not predictions
of supplier acceptance. All practice sessions use the csee ledger CLI and retain
the 30-session reserve. Existing scores and the production router are preserved.
