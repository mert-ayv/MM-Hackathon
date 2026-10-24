# v16 review and isolated Mert candidate

24 October 2026. Reviewed v16 commit `449c13a`. The final router is unchanged.

## What v16 covers

v16 = v14 plus `history_claims=True`: past orders, quality notifications,
earlier delivery quarters and references without locally available figures.
The ledger has two sandbox repetitions per case and policy:

| Policy | D01 mean | D02 mean | Mean across cases |
|---|---:|---:|---:|
| base/v14 | 0.9685 | 0.7022 | 0.8353 |
| base/v16 | 0.9864 | 0.7548 | 0.8706 |

This is promising evidence for additional arguments, not practice validation.
It does not change the close-gap stopping policy, package-change accounting,
P02's procedural framing or the router. v16 inherits v14's disabled final push,
but Emre's `prepare()` overrides it with a 0.5% push for raw material.

One claim needs caution: when the value of a should-cost reference is unavailable,
v16 nevertheless says it "leaves clear room below your price." A reference being
verified is not evidence that its value helps us. The candidate drops that claim;
it retains neutral requests to compare referenced orders.

## Candidate: `--agent mert --variant v16`

Implemented only in `csee/agents/mert.py`, with regression tests in
`tests/test_mert_agent.py`. No shared policy or router changes.

- Inherits Emre's raw-material clause and payment alternatives, plus the chosen
  parameter preset. With `v16`, historical evidence is enabled.
- When the normal close-gap rule would stop an **open** raw-material supplier
  whose latest package became cheaper, holds the previous buyer package for up
  to two additional counters. It stops extending if the supplier stalls, meets
  the ask, or the time/move reserve is short. Explicit final/agreed statuses do
  not trigger this extension. Identical repeated asks count toward the bound
  after a restart, conservatively.
- When changing non-price terms, prices the new package within the prior
  package's cost plus the policy's explicit price concession. A clause or shorter
  payment cannot silently add another concession. An infeasible repricing stops
  this counter rather than exceeding the budget.
- Tracks the main price actually sent after Emre substitutes a clause package,
  rather than retaining the pre-substitution draft price.
- Disables discretionary final-offer pushes, including Emre's override.
- Drops the unsupported unknown-should-cost assertion.

For other case types, uses the selected base policy, apart from the claim guard
and disabled final pushes. P02's authority argument and broader semantic planning
are not implemented by this candidate.

## Validation

- Smoke tests over all registered agents/variants and practice case files,
  existing Emre tests, runner tests and the first 12 candidate tests: **130 passed**.
- Final focused candidate suite, including infeasible repricing: **13 passed**.
- Ruff checks pass on the two Python files changed.
- Offline replay of three real stopping points, using both base and v16 params:

| Recorded session | Case | Existing Emre decision | Candidate decision |
|---|---|---|---|
| `a1109a6560290010` | P08 | Ready at 5.47 | Counter at previous 5.46 package |
| `18a6abe22afa0781` | P08 | Ready at 5.49 | Counter at previous 5.47 package |
| `7fd3257d6054fe3e` | P18 | Ready at 5.50 | Counter at previous 5.49 package |

These are decision checks, not counterfactual supplier outcomes. The supplier
could reject a repeat, stop conceding or walk. This limited continuation alone
cannot explain a jump to the leaderboard's raw-material records.

No hosted negotiations were started for this work. Practice testing needs the
team's quota approval under `CLAUDE.md`.

## Proposed next measurement: 12 sessions

- P08 and P18: current raw route (`emre/base`) versus candidate (`mert/v16`),
  two repetitions of each: 8 sessions. Measures the candidate bundle; does not
  isolate the effect of historical arguments from the policy changes.
- P02: `base/v14` versus `base/v16`, two repetitions each: 4 sessions. Tests
  whether added evidence helps the existing P02 policy without adding a final push.

Run close in time; log exact code/patch and writer mode. Inspect claim results,
end reasons, mean/minimum score, elapsed time and must-have validity. Reject a
candidate that causes new walk-aways or systematic regression. Repeat promising
results before any router promotion; two repetitions are screening evidence.
