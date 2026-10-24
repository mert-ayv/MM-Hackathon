# csee-base buyer agent: architecture

How our agent negotiates, and how each architecture version is tracked. Code: [`starter-kit/csee/`](../starter-kit/csee/). Built on Tacto's `arena_kit` (client, cost function, document readers), which we don't modify.

## Principle

**Code decides every number; language only explains it.** Supplier prices come from their cost data, so our score is won by offering the right *package*, using every term, not by eloquence. A model, when enabled, only words the e-mail. Every figure, term sheet, data argument and accept/walk decision comes from code.

That principle describes **base**. Ege's optional strategist separates interpretation/strategy (model)
from calculation, evidence-backed numeric assertions and contract validation (code), as described below.

## Pipeline per case

### Ege: evidence-driven strategy

`csee/agents/ege.py` uses one bounded SDK tool-runner turn per supplier reply for price increases,
RFQs and bundles. Its plan records a goal, an optional total-cost target, confidence-labelled
hypotheses with source IDs, unknowns and a next probe. Plan changes require a revision reason; invalid
or timed-out turns do not commit plans or claim use. Baseline advice does not override a valid move.
The strategist can concede, change packages, ask qualitative questions, continue bargaining, accept,
or stop. The unchanged base agent remains the no-model/error fallback.

`csee/agents/strategy_support.py` provides deterministic tools: cash/estimated total cost and breakdown,
explicit supplier-cost sensitivity scenarios, evidence search, document paging, read-only SQL and
checked claim construction. Case-local facts override package facts. Attached source text is available
by evidence ID; text from suppliers/documents is treated as untrusted evidence. SQL uses a separate
read-only connection with a query budget, so a slow query cannot monopolise the runner's connection.

Validation checks actual executable moves before acknowledging `submit_move`; errors return to the
model for correction in the same turn. Code enforces negotiable fields, valid options or supplier
standard values, finite values, must-haves, unused evidence and the first-standing-offer accept rule.
It prices acceptance against the actual alternative using the disclosed estimate. Full supplier cost
and acceptance probability remain unknown. These checks do not impose base's price, concession pace
or stopping policy. Email packages/figures come from the validated sheets and source-built claims.

Run-log additions: `agent_move` records the proposal, `strategy_applied` the actual action and sheets,
`strategy_tool` retrieval/calculation/validation calls, `strategy_usage` token counts, and
`move_rejected` / `strategy_fallback` the reason for corrections/fallbacks. A turn has at most 35 seconds,
shortened near the wave cap; late tools cannot commit state and busy model workers fall back promptly.

`sim --llm` explicitly enables the actual model path against local suppliers (LLM credits, no arena
quota); plain `sim` stays offline. Scripted HTTP tests exercise the actual SDK tool loop and a full
negotiation with an unfamiliar supplier, without network/model calls. Hosted score comparisons remain
necessary to establish performance; existing runs predate this implementation.

### Base pipeline

```
 before the session opens (no clock)            per supplier thread, in parallel          one coordinator
 ─────────────────────────────────────          ──────────────────────────────────         ────────────────
 case file ─┐                                    supplier reply                             all threads ready
 profiles/  ├─► intel.build()                    │                                          or wave cap near
 (46 JSON)  │    • full-cost floor estimate      ├─ their_sheet(): cheapest offered sheet   │
 data pkg ──┘      (should-cost × country, or    │   for us (all sheets, must-haves kept)   ├─ close(): accept the
                    the cost-breakdown XLSX)     ├─ next_terms():                           │   cheapest valid sheet
                 • verified claims, strongest    │   • levers.best_terms(): every term at   │   across all threads,
                   first: index changes, should- │     its cheapest value for us; ties →    │   if it beats the
                   cost, notice period vs        │     what the supplier prefers            │   alternative
                   contract, weak scorecard,     │   • price: anchor near the floor, then   │ └─ else walk away
                   news, rival offers (RFQ)      │     concede a share of the gap, slower   │
                                                 │     than the supplier moves              │
                                                 ├─ sheets(): main sheet + up to 2 trades   │
                                                 │   (faster payment, longer contract,      │
                                                 │   earlier date, more volume) priced so    │
                                                 │   each saves us ≥ 0.6 % of C              │
                                                 ├─ pick_claims(): ≤ 2 arguments, never     │
                                                 │   reused, profile's "avoid" list          │
                                                 └─ writer: template or LLM, claim          │
                                                     sentences kept verbatim                │
```

| Module | Responsibility |
| --- | --- |
| `levers.py` | Pure arithmetic over the published cost function: best value per term, € value of each lever, price for a target cost, the relationship-optimal price (for `stabilise`/`secure_supply`). |
| `intel.py` | Cost-floor estimate, claim generation (the figure and its IDs in one sentence, as the arena checks them), profile loading, cost-breakdown parsing. |
| `profiles/*.json` | One profile per detailed supplier (46): situation, pressures, what it values, likely trades, arguments that land or backfire, persona. Built offline from the notes, letters, news, history and SQL; every cited ID is verified. |
| `agent.py` | `CseeAgent`: per-thread moves, trade sheets, claim selection, accept/walk coordinator. Behaviour switches live in `Params`. This is `base`, the champion. |
| `agents/` | One competing agent per teammate (`ege`, `mert`, `annika`, `emre`), each a `CseeAgent` subclass, picked with `--agent`. The ledger records `agent` on every row, and the board labels non-base rows `agent/variant@commit`. |
| `runner.py` | Plays every thread of a case in parallel (the 60 s clock is per thread); decisions and LLM calls run outside the case lock on a snapshot (contract for agent authors: `agents/__init__.py`); closes before the wave cap, falls back to the kit's closing move on any error, runs the Live Final waves. |
| `runlog.py` | The run log for the dashboard: `runs/<YYYYMMDD-HHMMSS>-<agent>-<set>/`, one JSONL per case session, format in [`run-log.md`](run-log.md). On for every command that plays; `--no-runlog` turns it off. |
| `writer.py` | E-mail wording: templates (no model), or an LLM in the supplier's register with the template as fallback. |
| `variants.py` | Named parameter presets plus a one-line description of each. |
| `ledger.py`, `evaluate.py`, `localsim.py` | Experiment ledger, replay/back-office fetcher, local supplier simulator. |

## Safety rails (in code, every variant)

- Every term sheet holds exactly the case's negotiable fields, snapped to the allowed options.
- Unknown data IDs are never cited; each ID is cited once per case; at most 2 claims per message.
- No accept that breaks a must-have or costs more than our alternative. The cost is computed on the terms the deal would really close on (supplier's standard terms for anything left out).
- Volume and contract length cover the full need over the horizon unless the case forbids it.
- Any crash in a thread or in the close step falls back to a safe closing move, so a session is never left open.

## How architecture versions are tracked

| Where | What |
| --- | --- |
| `experiments/<date>-<author>.jsonl` | Every run: who (`author`, `host`), `agent`, `variant`, `variant_desc` (in words), `commit`, `patch`, `on_origin`, full `params`, score, session. |
| `experiments/patches/<hash>.diff` | Uncommitted agent edits a run used. The row's commit reads `<commit>+<hash>`. Reproduce with `git checkout <commit> && git apply experiments/patches/<hash>.diff`. |
| `starter-kit/csee/variants.py` | The behaviour switches of each variant, plus `DESCRIPTIONS`. |
| git history | The exact code of any run: `git show <commit>:starter-kit/csee/agent.py`. |
| This file, changelog below | What changed between architecture versions and why (the evidence). |

## Changelog

| Version | Commit | Change | Evidence |
| --- | --- | --- | --- |
| v1 `base` | `50b3e04` | First agent: lever engine, verified claims, parallel threads, template writer. | Practice baseline 0.481 mean over 10 cases (P02 and P03 crashed: fixed in `f1ab65d`). Simulator 0.83 vs naive 0.57. |
| v2 | `0ef9f9a` | Sandbox D02 lessons: adopt held terms, rival only if lower, cash sheet, slower concessions. | Sandbox: D02 0.54→0.66, D01 0.90→0.77 (draw). |
| `fix` / v3 | `e2917d6` | Practice-replay lessons: weigh every offered sheet (P05, P10), cheapest clause when insisted (P08), should-cost ×0.95 (P01 stopped early). | Counterfactual on recorded games: about +0.05 upper bound. Local sim: base 0.735, fix 0.793, v3 0.874. Sandbox: fix = base (sandbox bots send one sheet), v3 0.711. |
| v1.1 `base` | `d6529be` | **`fix` promoted into `base`** (`v1` keeps the old behaviour). `v2` tactics stay a variant: mixed evidence (helps RFQ D02, hurts price-increase D01). | As above: a bug fix, neutral where it can't trigger and positive where it can. |
| v1.2 `base` | `6de43c5` | **Fable review bug fixes:** terms optimised at our asking price, not the supplier's (P08 opening €1.06M → €1.00M); cite only *falling* indices (rising ones "confirm their case", 5×); the AI writer runs outside the case lock with a 15 s cap and template fallback; scrub IDs the model invents; retry a failed accept (stale sheet) up to 3×; cost-breakdown sanity cap; resumed cases continue from earlier asks; Sunday-release news reach the claims; the simulator no longer walks away (0 of ~350 real messages did). | Smoke 25/25; sim v1 0.708 → base 0.775. |
| v1.3 `base` | `43665e0` | **Bug: only a reply's first sheet is acceptable** (arena 422 "not a standing offer"; caught on the free sandbox, 4 D01 runs scored 0). A better alternative sheet is now proposed back word for word (the supplier agrees, then we accept); accept retries fall back to the thread's standing offer. The simulator enforces the same rule. | Sandbox repro; sim: no failed accepts on 19×3 cases. |
| v1.4 `base` | `2d5e642` | **Regression fix (sandbox D01 0.90 → 0.63 in v1.3):** (a) a better alternative sheet is proposed back only when we would close the thread anyway, not mid-negotiation (D01 closed after 2 rounds instead of 6); (b) terms are chosen at the expected deal price (halfway between the asks), not at our anchor (an anchor below today's price picked the earliest start date for a deal that ends above it). | P08 still opens at 36 months; sandbox re-run pending. |
| v1.5 `base` | `7071d59` | **Data-review fixes (claims):** index windows 3–12 months, cite the most favourable *fall* (P08/P18: alloy surcharge −5.5 % over three months, the driver the supplier blamed); series labels without digits; series the supplier names in its opening e-mail and case `refs` count as drivers; news only when it helps us (Hrvelec's "fully booked" had helped *them*); quality cases lead with ppm; forecast-growth claims; notice from any letter of the supplier; hidden-case facts (sc/ctr/doc/news/cost/fc) used; profile "avoid" filter by keyword (it blocked all index claims and missed should-cost); first message up to 3 claims; LLM writer strips claim IDs outside the verbatim claim sentences. | 75 generated claims over 19 cases independently re-checked against facts.json: 0 problems. All 174 claims cited so far came back `verified`. |
| runner: LLM-safe concurrency + run log | `7893a63` | `thread_move` (strategy, LLM writer) runs outside the case lock on a snapshot of `threads`, so a 10–30 s decision no longer stalls the other RFQ threads' 60 s clocks; `close()` stays under the lock; a message decided after closing started is dropped; close at `max(CLOSE_BEFORE_CAP_S, slowest round + 15 s)` before the cap. Cited IDs are claimed under `CseeAgent.shared_lock`. The router now passes `log` and `cap_at` to the routed agent (time-aware pace was off under `--agent router`). Run log (`csee/runlog.py`, `docs/run-log.md`): runner events + agent `plan`/`decision`, after-the-end `end_reason`/trace/back office. | `tests/test_runner.py`: 3 threads × 2 s decisions finish round 1 in ≈2 s (old runner 6.0 s); late messages dropped at the cap; log shape; dashboard reads the runs. Local sim with the data package (`ARENA_DATA`), `base`, 19 cases × 3 seeds, 3 runs each: 55/57 case-seeds identical to `origin/main` and deterministic; P06 seeds 1–2 (2-supplier RFQ) vary between runs on main as well (thread interleaving; the sim shares one RNG per case) and every value after the change is one main also produces. Mean main 0.2792–0.2795, after 0.2792. With the log on only the RFQs move, for the same reason (file I/O shifts interleaving; computing the log without writing changes nothing). Verified over HTTP on `arena-sim` incl. a 2-wave final rehearsal. |
| v1.6 `base`: lever engine math fixes | `21b995e` | **(1) `best_terms` quality tie-break:** every (ppm, chargeback) pair with chargeback ≥ `cost_per_defect` costs us €0, and the "supplier likes" tie-break picked (1,500 ppm, €500), a chargeback that costs the supplier its *real* ppm × chargeback × units. Quality terms are now compared at the price that keeps `supplier_value` equal, with chargebacks at its real ppm (max of opening/standard, scorecard, profile `quality.ppm`). Ties go to the cheapest for the supplier, then the lowest ppm. Result: lowest ppm, chargeback at standard unless it pays for itself. localsim keeps its old C_best yardstick (`supplier_cost_aware=False`). **(2) `price_for` assumed C rises with price:** with the relationship term (stabilise/secure_supply) C rises again below the C-minimal price, so bisection from 0 converged to 0.00 even for *reachable* targets and `sheets` silently dropped every trade sheet. Now: find p_min (scan + golden section), bisect on [p_min, hi], return `None` below min C. Callers handle `None`. | P11 Kalwisz charged €2.00–2.50/unit for €500 → €150 chargeback, worth €0.11–0.45/unit to us (2,376 ppm × €500 = €1.19/unit to it vs 300 ppm × €450 = €0.135/unit to us). P10 trade target C×(1−0.6 %): old 0.00, new €29.71 (p_min €26.31). P09: old 0.00, new €15.78 (p_min €15.74). `tests/test_levers.py`. Local sim (base on `f9ca31d`, 3 seeds, no LLM) 0.2792 → 0.2917: P01 +0.086, P17 +0.093, P09 +0.054, P06 +0.008–0.011 (timing-noisy RFQ) - trade sheets now survive; P11 −0.003, P12 −0.002 (expected: the sim prices a chargeback at €0.0005 per €, not at real ppm, and so does not reward giving up the €500 chargeback); the other 13 cases identical. |

## Experiment log (free tools: sandbox D01/D02 are deterministic real bots; sim = calibrated local simulator)

| Variant | Idea | Sandbox D01 / D02 / mean | Sim | Practice | Verdict |
| --- | --- | --- | --- | --- | --- |
| `base` v1.4 | all bug fixes | 0.90 / 0.54 / 0.721 | 0.354 | (v1: P-mean 0.48) | champion until v9 is confirmed |
| v5 | Fable bets, slow concessions | 0.82 / 0.60 / 0.707 | 0.383 | – | slow concessions hurt D01 |
| v6 | v5 at base speed | 0.86 / 0.65 / 0.753 | 0.373 | – | – |
| v7 | v6 without hold-on-internal | 0.84 / 0.74 / 0.790 | 0.373 | P05 **0.81** (was 0.35, house 0.56), P08 0.52 (0.44), P11 0.06 (0.23) | RFQ win; P11 flipped terms |
| v8 | v7 + generic trades + text signals | – | 0.374 | – | untested on real bots |
| **v9** | v7 + **sticky terms** | **0.95** / 0.72 / **0.835** | **0.385** | – | **best; next practice candidate** |
| v10 | v9 + push after final offer | 0.99 / 0.72 / 0.855 | 0.272* | – | D01 agreed lower; **DEMO-C1 walked away** when pushed far |
| v11 | v9 + small 0.5 % push, leader only | 0.97 / 0.72 / 0.846 | – | – | safe, no gain this time |

\* sim recalibrated to 626 real supplier moves before this row (final offer around reply 4, 3 personalities), so sim numbers above and below that line are not comparable.

**Lessons so far:** suppliers converge on our anchor; they turn final around their 4th reply, so the anchor and first moves decide; steady visible concessions buy more rounds than stubbornness; changing terms lets them re-price (13 % of real moves went *up*); only a reply's first sheet is acceptable; a far push after a final offer can make a supplier walk.
| v12 | v9 with sticky only for quality terms, value-neutral chargeback/ppm, contract at horizon | 0.86 / 0.74 / 0.796 | 0.275 | – | lost v9's D01 gain (sticky payment helped there) |
| v13 | v9 with sticky terms only when they cost <= 0.8 % of C + v12's quality/contract fixes | 0.97 / 0.70 / 0.835 (with AI writer 0.97 / 0.72 / 0.846) | 0.276 | **P02 0.44 (was 0), P03 0.92 (= house), P10 0.67, P11 0.71 (house 0.31), P18 0.42**; board mean 0.50 -> 0.69 | **current champion candidate** |
| v14 | v13 + relationship-goal anchor at the supplier's real cost (should-cost x0.98), trade sheets without the relationship term (all were dropped), close only within 10 % of the room | 0.97 / 0.70 / 0.835 (= v13, as predicted: the sandbox has no should-cost) | 0.385 vs v13 0.31 on rel/price-increase cases | – (bot calibrated on real P02: 0.41 -> 0.83-0.91) | candidate for P01/P02-type cases |

**Routing for the final (`csee/agents/router.py`, Sat 17:10, from practice results):** price increase, renewal, capacity, quality and unknown types -> `base/v14`; RFQ -> `base/v7` (P05 0.81); bundling -> `base` (P07 0.72: the v13 line's deep anchor drew a final offer at reply 2); raw material -> `emre/base` (P08 0.55, P18 0.47: best measured; pinned so v13 switches can't leak in); payment days from a supplier's alternative sheet are adopted only for cash-short suppliers (P18 lost 0.048 to a locked-in 30 days). Bets for Emre's agent: `docs/notes/raw-material-review.md`.

**Final-mode estimate:** every run now records what it would have scored at the final's cutoffs (390/330/270 s, `csee/final_est.py`; `csee board --final`, `csee finalest`). The v13 validation cases took 49-215 s, so time was not binding in practice.


**Robustness fixes (all variants, Sat 24 Oct ~16:45; found by the LLM final rehearsal and a fresh-eyes review, no quota used):**
- **Price-only final offers:** a sheet that omits terms closes on the supplier's *standard* terms. Before accepting one, we ask once for "your price with our terms" (sim S03 0.29 -> 1.00, S01/S02 0.81 -> 1.00/0.99).
- **Fixed-price cases** (`unit_price` not negotiable) crashed every first move, so the agent never negotiated. Now we negotiate the other terms only.
- **A price must-have** (`unit_price <= X`): we never ask above it, and other terms are optimised at the cap. Before the fix, every ask broke it and the case ended in a walk-away.
- **A supplier holding a term that breaks a must-have** (P09-like: 49 days lead time against our <= 42): we meet it at the bound (42) instead of resending our 28 days until we walk away.
- **v14 trade sheets** priced below the supplier's cost for relationship goals are dropped (a wasted slot).
- **Runner:**
  - after 3 refused closes, it tries the kit's closing move, then a walk-away (an open session would sit until the wave cap);
  - a final case that failed before closing is played again (409 -> resume).
- **Check:** sim unchanged (base .267, v13 .285, v14 .317); sandbox v14 0.97 / 0.70; 159 tests pass.

| v15 | v14 + one 0.8 % push after a final offer, leading bidder only (sandbox logs: 10 of 11 pushes <= 2 % improved the deal, none walked) | 0.97 / 0.72 / 0.846 (2 repeats each; v14 0.835) | 0.317 (= v14: the sim bot treats a final offer as hard) | P01 0.93 (no push fired), **P02 0 (pushed 372.20 -> 369.22 after its final offer: it walked; accepting scored 0.48)**, P07 0.70 (push agreed 5.52 -> 5.48), P11 0.71 (push ignored) | **rejected**: 1 gain, 1 neutral, 1 walk-away worth -0.48, and no tell in the text |

**Free-tool ceiling (Sat ~17:00):**
- The local sim can't rank variants: levels are off by about 0.3 and it ranks P11 the wrong way round.
- A replay-calibrated bot per case (scratchpad `ceiling/`, leave-one-out error 0.046) says v14 never loses to v13 across 360 bot settings and gains on P02.
- The open bets need practice bots:
  - the v14 anchor (P01/P02);
  - pushing after a final offer (v15);
  - more checkable claims in round 2+ (suppliers asked for data in P03/P11/P18, and we sent none);
  - the "<= 2 % desk authority" line (P02/P10);
  - continuing the RFQ auction with an agreed bidder (P05).

| v16 | v14 + more checked arguments for rounds 2+ (`history_claims`, intel.history_claims): this supplier's cheapest orders of the part in the last 2 years (3 per argument, each ID next to its exact price; P02 339.37, P08 5.17, P18 5.26), mean ppm of its quality notifications, delivery over earlier quarters, and case `refs` we hold no data for (orders, should-cost), cited without a figure | **0.99 / 0.75 / 0.871** (v14 0.835; both figure-free arguments came back `verified` - D01/D02 had sent no arguments at all before) | – | – | **candidate**; 72 new practice-case arguments all match facts.json (static check); figured order arguments not yet checked by the arena |

**Pacing study (Sat evening, 1,132 supplier replies; scratchpad sub-misc):**
- **Patience.** Each supplier has a fixed patience before its final offer: median 4 replies (P10 1, P04 2, P08/P18 3, P02/P07 4, P01 5, P03/D01 5-6).
- **Deep asks shorten it.** An ask more than about 8-10 % below the supplier's floor cuts that patience by 1-2 replies: D01 6 -> 3, P07 4 -> 2, P18 3 -> 2, P11 6 -> 4-5.
- **Anchor cap.** `mert-anchorcap` caps the anchor by case type: 12 % for price increase/renewal, 15 % for bundling/capacity. Not routed yet.
- **Faster concessions lose on the sandbox** (D01 0.969 -> 0.856/0.921).
- **The gated push after a final offer is rejected.** Size min(1 %, 0.6 x the supplier's own concession), only after >= 1 %. 20 logged pushes inside the gate were safe, but P18 session afada094 walked after a 0.55 % push inside it ("we have already reached our absolute limit").
- **Push hook.** Agents now size a push per thread with the `final_push_size` hook, never by swapping `self.p`: threads decide in parallel outside the runner's lock.

**Practice batch Sat 19:04 (AI writer):**
- **mert-lever/v14:** P02 **0.733** (362 @90 with the CU clause at 5 % deadband, agreed; previous best 0.633; the engine model predicted 0.736) and P01 **0.933** (new best).
- **mert-raw/v16:** P08 0.57 (mert/v16's 0.711 stands) and P18 0.552 (= best).
- **Router:** price_increase -> mert-lever/v14; raw stays mert/v16.
- **Engine model** (scratchpad sub-engine): the bots are a deterministic rule engine with an LLM writing the e-mails.
  - It mirrors our value step up to a decaying cap.
  - It goes final at reply N, or from K0 when our gap > G.
  - It always agrees to its own final sheets proposed back.
  - It agrees to ANY of our sheets worth >= its ask, so a sheet 2-3 must be one we would accept.

**Competing prices as leverage (Sat 20:00; scratchpad sub-rival):**
- **What the arena verifies:** only the case's alternative quote, a `quote:` in the case refs, and RFQ rivals' offers in the session. Historical rival quotes and orders come back `irrelevant`; in one P18 run they drew "we cannot verify the competitor pricing", the opening was about 1.7 % worse and the run scored 0.401 vs 0.467.
- **What we cite now:** new `alt_quote_claim` cites the case's alternative quote once per supplier, and only when it is at least 1 % below the ask.
  - **Why:** bots answer a verified much-lower rival quote with "I give half the step now"; DEMO-J1 did 99 of 99 times.
  - **Practice:** it never fires on the 10 practice cases, because every alternative there is dearer than the ask.
  - **Final:** it could turn a hidden "best left without a deal" case into a deal.
- **Routes now use the a-variants:** mert-lever/v14a, base/v14a, base/v7a, mert/v16a, and base/basea for bundling (base + `rival_only_lower`).
- **Checks:** sandbox router 0.852 (unchanged); 431 tests pass.

**Sat 20:00 batch and new agents:**
- **mert-skiphedge/v16** (P08, 2 sessions): **0.754** (new best, was 0.711) and 0.711. The only change: an argument on an index the supplier says it has hedged is moved last, so round 1 cites the unhedged PPI-C2431 fall. Router: raw_material -> mert-skiphedge/v16a.
- **v18** (v14 + 12 % anchor) on P11: 0.71. The supplier holds 45.5 from reply 3; it is unchanged.
- **Online move planner** (`mert-plan`, `mert-plan-lever`, `mert-plan-raw`; scratchpad sub-planner) works in the supplier's value units:
  - it estimates the supplier's cap and decay from its steps;
  - it asks a full-cap step each round;
  - it keeps the gap under a per-reply budget (12/8/4/3/2.5/2 %), never drops its ask, and never pushes after a final offer.
- **Engine results for the planner** (not routed yet):
  - fitted personas: mean .764 vs router .752; P01 .884 -> .947, P18 .485 -> .552;
  - 531 perturbed personas: .658 vs .615, with **3 walk-aways vs 36**.

**Sat 20:40, record routes:**
- **P01: mert-plan-meso-lever/v14a scored 0.975**, a new best (engine predicted 0.962). It is the planner's value-unit pacing on top of the payment choice; the supplier took the 14-day sheet at once and stepped 136.1 -> 132.7. This is the first real confirmation of the planner. Router: price_increase -> mert-plan-meso-lever/v14a.
- **P01 MESO alone: 0.938** (stopped at 133.9 after +0.05 steps).
- **P11: the on-time-payment pledge failed twice** (v14a 0.71, v18 0.71). The bot noticed it ("We appreciate your commitment...") but held 45.50.

**A/B dress rehearsal (Sat 20:43): current router vs router-plan, all 10 practice cases, AI writer, 20 sessions**

| Case | router | router-plan |
|---|---|---|
| P01 | **0.988** (best) | 0.970 |
| P02 | 0.733 | 0.733 |
| P03 | 0.923 | 0.923 |
| P04 | 0.86 | 0.86 |
| P05 | 0.81 | 0.748 (same agent: variance) |
| P07 | **0.766** (best) | 0.734 |
| P08 | 0.711 | 0.744 |
| P10 | 0.57 | **0.671** |
| P11 | 0.71 | 0.626 |
| P18 | 0.552 | 0.552 |

- **Outcomes:** no walk-aways and no errors in either router. Board mean 0.777.
- **Planner fix:** it stopped and accepted after the supplier held twice (P11 accepted a hold at 46.00, while waiting got 45.50 as its final). That rule is now off (`frozen_after` 99); the engine shows no loss on P03/P04/P11.
- **Final router (hybrid of the per-type winners):**
  - mert-plan for renewal and capacity;
  - mert-plan-meso-raw for raw material;
  - mert-plan-meso-lever for price increase;
  - base/v14a for quality;
  - base/basea for bundling;
  - base/v7a for RFQ.

**Sat 22:50, P11 (quality) mechanism:**
- **Results:** the quality menu (Astra session) scored 0.794 / 0.71; the planner scored 0.71 / 0.672; base-d scored 0.71 every time (about 8 runs).
- **Why:** the supplier prices in 0.50 ticks, rounded up, and mirrors our step. It only drops a tick when our step is at least one tick.
  - The menu kept +0.55 steps to the end and got 45.00 in its final.
  - The planner closed the gap fast and its last steps (+0.16, +0.02) round to nothing.
  - Base drew the final at reply 4.
- **Lesson:** against coarse-tick suppliers, keep each step at least one tick and leave enough gap to keep stepping until the final.
- **Router:** quality -> mert-quality-menu/v14a.
- **Also rejected:** P02 fixed-price ladder (0.499: the bot stalls at 372 without the clause) and P18 joint payment/deadband menu (0.542).

**Sat 23:10, planner tick rule:** P11 scored 0.71 in both runs; not routed.
- **What the logs show:** the planner closes the gap to one tick by reply 5 (its no-cross cap), so its last step is +0.01 again.
- **What worked instead:** the menu agent kept a wide gap (41.99 vs 45.50) and +0.55 steps, and got 45.00 in the supplier's final.
- **Why this is not a planner fix:** the planner keeps the gap small on purpose (P02/P18 go final or walk on a 2.5-4 % gap). P11 tolerates 8-15 %. Gap tolerance is per supplier, and only the quality route (menu agent) uses wide-gap pacing.
