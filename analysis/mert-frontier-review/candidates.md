# Isolated candidates implemented, 24 October 22:30

Neither candidate is selected by the final router. Practice approval is still
required. No practice sessions were started for this implementation.

## mert-quality-menu / v14a

Generic quality-case extension in `starter-kit/csee/agents/mert.py`. Keeps the main
offer and adds up to two weaker, allowed ppm commitments. Reprices each at no more
than the main offer's total cost, including cent-rounding correction. Rejects
must-have violations and omits alternatives that would require retracting a
previous offer for the same structure. Does not modify fixed payment/volume.
For a 45.00/300ppm main offer, P11 alternatives are 44.77/800 and 44.46/1500.

## mert-fixed-probe / v14a

Explicitly practice-specific P02 experiment, not a general final policy. Starts
with exactly one fixed-price proposal at 368.00, payment 90 days. If negotiation
continues, returns to the existing lever policy; no indefinite fixed-price hold.
Other cases retain the parent policy. Both candidates disable final-offer pushes.

## Validation

- 26 focused candidate and existing Mert regression tests passed.
- Router resolution check passed after concurrent sync conflict repair.
- Both candidates passed the v14a smoke test across all ten practice case files
  (synthetic suppliers, no practice quota).
- Local simulator completed P02/P11 for both candidates. Means 0.261 and 0.301;
  these are plumbing results, not credible estimates of hosted performance.
- Four free sandbox sessions completed without errors and with deals. Each
  candidate scored 0.968545 on D01 and 0.702151 on D02. Neither sandbox case
  exercises the new P11/P02-specific behavior; these check integration only.
- Ledger: `experiments/2026-10-24-mert-codex.jsonl`; exact run source patch:
  `experiments/patches/c8611177.diff`.

The tests demonstrate valid proposals and successful execution. They do not show
that the target suppliers accept the new packages or that either candidate will
improve the leaderboard. A single approved P11 screen is the next informative
hosted experiment, followed by a repeat only if promising. No promotion yet.

A concurrent automatic pull produced a router conflict (capacity slot). Preserved
both versions in `router-sync-conflict.txt` and retained the pre-turn local
`base-d/v14s` capacity route. This repair introduces no candidate routing change.
The upstream alternative was `annika-k9j/v14a`; choosing between those remains
separate from these experiments.
