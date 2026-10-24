# csee-base buyer agent: architecture

How our agent negotiates, and how each architecture version is tracked. Code: [`starter-kit/csee/`](../starter-kit/csee/). Built on Tacto's `arena_kit` (client, cost function, document readers), which we don't modify.

## Principle

**Code decides every number; language only explains it.** Supplier prices come from their cost data, so our score is won by offering the right *package*, using every term, not by eloquence. A model, when enabled, only words the e-mail. Every figure, term sheet, data argument and accept/walk decision comes from code.

## Pipeline per case

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
| `runner.py` | Plays every thread of a case in parallel (the 60 s clock is per thread), closes before the wave cap, falls back to the kit's closing move on any error, runs the Live Final waves. |
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

