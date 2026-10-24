# How we win: strategy and work plan

**Goal: first place in the Live Final, Sun 13:30.** That needs (1) a top-5 Live Final score and (2) the best pitch among the top 5. Background is in [CHALLENGE.md](CHALLENGE.md).

## What the scoring rewards

1. **C_best is fixed per case: the best package any supplier would *ever* accept, with every lever applied.** Haggling on price alone caps our score. To reach a score near 1 we have to pull every lever the supplier will trade: payment days, Incoterm, lead time, contract length, volume, effective date, ppm/chargeback, index clause and tooling.
2. **Coverage dominates.** A deal that doesn't cover `need_per_year × horizon_years` pays the fallback price plus risk on the gap. Example: 12 months instead of 24 turned a 0.64 deal into a 0. Volume and contract months must cover the need unless there's a very good reason.
3. **Effective date is a lever in price-increase cases.** Units bought before the new price takes effect are bought at the *current* price, so pushing the increase back is worth real money.
4. **Mutual-gain trades.** If a supplier is short of cash, paying earlier is worth more to it than it costs us (8 %/yr), so we trade payment days for price. If it needs volume, we trade a longer or larger commitment. The cost function and `supplier_value()` let us find these trades in code.
5. **In `stabilise` and `secure_supply` cases, don't squeeze below the sustainable margin**; we pay for it in C. Estimate full cost from `should_cost.csv` and stop there.
6. **No deal can be optimal.** If the alternative beats every reachable deal, walk away.
7. **A broken must-have scores 0.** Check must-haves in code before every accept, using the supplier's standard terms for any field we left out.
8. **Wave score is the mean of its cases.** One crashed or timed-out case drags down the whole wave, so robustness is worth as much as cleverness.

## Architecture: code decides the numbers, the LLM reads and writes

```
                 ┌──────────── offline (tonight + Sun 08:00) ─────────────┐
 data package ──►│ Dossier builder: one dossier per supplier              │
 Sunday release  │  scorecards, QNs, contract and clauses (notice, index), │
                 │  price history, negotiation_history (asked vs settled), │
                 │  should-cost → estimated floor, cost drivers + index    │
                 │  changes → ready-made VERIFIED claim sentences, notes,  │
                 │  letters, news → LLM summary: persona, pressures,       │
                 │  what it wants, what moves it                           │
                 └───────────────────────┬─────────────────────────────────┘
 case file ──► Lever engine (pure code)  ▼
               • € value of every lever for us (price-equivalent per unit)
               • target package and walk-away line; coverage enforced
               • 2–3 term sheets that probe what the supplier values
               ──► LLM writer (fast model, < 60 s): e-mail with the claims, tone matched to the persona
               ──► Guard (code): complete and snap sheets, drop unknown IDs, cap claims at 3,
                    never accept a must-have break or anything worse than the alternative
 every reply ──► update the estimate of the supplier's floor and its signals → next move
```

- **Heavy thinking happens before the session opens** (the 60 s clock starts at `POST /sessions`). In the final, waves are 8 minutes, so dossiers for all ~46 detailed suppliers must be precomputed and cached.
- **Every move is logged with its reasoning**, which we need for the pitch: the jury reads our replays.

## Work split (4 people)

| Who | Track | Done when |
| --- | --- | --- |
| **A** | **Dossiers and claims**: mine notes, letters, news, negotiation history and scorecards; precompute verified claim sentences; LLM persona summaries | every detailed supplier has a cached dossier; claims come back `verified` |
| **B** | **Lever engine and negotiation policy**: lever valuation, target and walk-away, concession schedule, multi-sheet probing, accept/walk logic | beats the kit's LLM agent on every practice case |
| **C** | **Eval loop and final infra**: practice runner with a score table, replay scraper and analysis, cloud VM, final rehearsal on the simulator, logging | one command plays all practice cases and prints scores vs. the last run; the final runner rehearsed |
| **D** | **Pitch and submission**: architecture notes, 1-min demo and tech videos, slides, a replay walkthrough | everything uploaded by 13:00 |

**Quota discipline:** 200 practice sessions per 24h, shared by all four of us. Use the simulator and the sandbox (`D01`, `D02`, free) for plumbing, and the hosted practice cases only to measure real changes. Log every run in `runs/` (git-ignored).

## Timeline

| When | Milestone |
| --- | --- |
| Sat afternoon | Keys in; baseline (naive + kit LLM) on all 10 practice cases; read every replay |
| Sat evening | Dossiers v1 + lever engine v1 → our agent beats the baseline |
| Sat night | Iterate on replays; cloud VM up; final rehearsal on the simulator |
| Sun 08:00 | Sunday release → rebuild dossiers |
| Sun morning | Pre-flight from the VM; freeze features by ~11:30; bug fixes only |
| **Sun 13:00** | **Code freeze, submit commit hash** |
| **Sun 13:25** | **Runner running on the VM, logging** |
