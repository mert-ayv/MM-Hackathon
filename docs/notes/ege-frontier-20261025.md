# Sunday frontier review, Ege, 25 October 2026

All times CET. At 11:29 the evidence-only `ege-raw-forecast/v16c` is selected
for the raw slot, subject to the full regression gate below. Every other
candidate remains unrouted. Its price, package, planning and closing policy
are exactly the previous raw route; only modest positive current demand is
new evidence. Three paired screens helped P08 and tied P18. This does not
set a new historical best or establish first place.
Initial findings, candidates, ledger snapshots and Sunday data were pushed to main
in `f2e40b5` (integrated with team dashboard work in `289b9e4`).

At 10:44 the official practice board had csee-base fifth at 80.6, behind
Clooless at 83.7 (83.1 at 10:10). At 11:16 we remained fifth at 80.6;
the leader had reached 84.1, and 265 practice sessions remained. Best case scores: P01 .9876, P02 .7354, P03 .9228,
P04 .8604, P05 .8543, P07 .7665, P08 .7544, P10 .6865, P11 .8771,
P18 .6182. The practice board uses historical bests; the Live Final is a
single attempt on unseen cases. First place on the practice board does not
win the hackathon.

At 12:00 the public practice board puts csee-base **sixth at 80.6**, behind
Clooless at **84.5** (3.9 leaderboard points). RGV has moved above us at 80.7.
The latest experiments have not changed our historical bests. The user's
deadline for this release to reach `main` is **12:10 CET**; no further strategy
experiments are being added to the release.

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

At 11:00 `ege-raw-dual-evidence` tested one index plus forecast in the opening,
then one remaining claim per turn. Both evidence families were acknowledged in
the same opening response; the older two-index test did not establish a universal
one-argument limit. Outcomes .7328 P08 / .5518 P18 tied the reciprocal forecast
agent. No reason to front-load on these results. The next screen tests larger
early steps (same opening) and, separately, the existing scoped writer so it can
answer requests using the actual fixed annual quantity.

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
the 30-session reserve. Existing scores are preserved; only the forecast evidence
route described above is promoted.

## Headroom and final preparation

The public records around 11:00 show the largest remaining gaps in P08
(.7544 vs .958, worth 2.04 leaderboard points), P18 (.6182 vs .767, 1.49
points), and P02 (.7354 vs .875, 1.40 points). These are attainable results
by other teams, not evidence that our present policy can achieve them. P02's
current clause package is already at its modeled optimum: an improvement
requires winning a better package, not merely asking for a lower price.

Latest teammate findings on `origin/main` at 12:00 do not supply another
promotion: Annika's P03 history-evidence run scored .9211 and its softer 4%
anchor scored .9228 (baseline .9228). Emre's department-question router averaged
.702 versus the existing router's .773, including P08 .5921 and P18 .4854.
Their experiment rows and the team's dashboard/video work are integrated with
this release; none changes the agent source tested by the release gate.

The 11:09 raw pacing screen tied the historical P08 best (.7544), but its
first supplier reply was already better before any pacing difference could
act, so this cannot yet be attributed to the 45% concession setting. P18
was .5518. The scoped-writer screen scored .7328/.5518, tying the ordinary
reciprocal forecast policy. No new route from either screen.

Source notes explicitly invite an owner cost review for both raw suppliers.
`ege-raw-owner-review` makes that request once on its opening packages, only
when the actual supplier document contains the invitation. It does not
invent an approval threshold or promise a concession. Both sessions failed
with connection timeouts during send and re-read, ending at zero. These are
infrastructure failures, not evidence against the dialogue hypothesis. A
subsequent public GET succeeded; no promotion or immediate quota retry.

## Connection recovery fix

The observed connection failures exposed a runtime problem: the final configured
six retries on top of the initial request, with the kit's uniform 180-second
timeout. That can keep a failed connection inside the HTTP client longer than a
wave, before the runner can re-read the session or try closing it.

`runtime_client()` now uses a 5-second connect/pool timeout, 15-second write
timeout, and two retries. It keeps the 180-second read allowance because a valid
supplier response may be queued behind another thread. The kit's same-move-ID
retries remain intact; the existing runner still handles recovery and deadlines.
This is a connection-recovery fix, not a solution for a sustained total outage.
Mock transport and runner checks passed (17 tests), including unchanged move IDs,
identical request bodies, recovery after two failed connections, and bounded
attempts on a persistent connect failure.

The full working-directory suite could not collect two pre-existing untracked
tests (`test_economic_policy.py`, `test_general_negotiation_policy.py`): they
import missing `standing_costs` and `competitive_reply_pending` runner helpers.
Those files and their unfinished modules are preserved, not staged. The release
gate runs the exact staged source in a clean temporary checkout. Initial result:
2,986 passed, one skipped (the optional hosted-arena integration test is not
configured). A final ordering guard keeps should-cost, notice and rival evidence
ahead of the modest forecast; the hosted raw cases have no such cost estimate,
so their tested behavior is unchanged. Its focused regression passed. The full
clean suite on the final staged source passed: **2,987 passed, one skipped in
651.69 seconds**. The only skip is `tests/test_sim.py:48`, the optional hosted
integration test requiring `ARENA_TEST_URL` and `ARENA_TEST_KEY`. Every tracked
file under `starter-kit/` was hash-compared with the clean test checkout: no
differences. The new source and tests pass Ruff; source/document whitespace
checks pass. Existing unfinished local files remain outside this release.

## Release rehearsals

- Free hosted sandbox on the new client: D01 .9346, D02 .7443; both deals.
- Ten-case practice dress rehearsal `20261025-114036-router-practice`: **10/10
  deals, mean .7684**, versus .773 in the earlier team single-shot. This does
  not establish an aggregate gain: P08 improved relative to the earlier .581
  result, while unchanged P05/P11 routes scored lower in this sample. No new
  historical team best. Three writer timeouts fell back to templates; no
  connection failure occurred in this batch.
- P01 .9776, P02 .7328, P03 .9228, P04 .8604, P05 .7688, P07 .7405,
  P08 .7328, P10 .6863, P11 .7099, P18 .5518. All completed within the
  390-second final estimate, slowest P05 at 371 seconds. The timing estimator
  retains the same scores at 390 seconds; this is an estimate, not a final run.
- Local mechanics rehearsal: pre-wave 403, resume of an already-open session,
  two waves, all six simulated cases closed, four deals and two walks, no
  runner error. Synthetic scores are not calibrated to the hosted game.
  Reproduction script and JSON: `analysis/ege-final-rehearsal-20261025/`.
