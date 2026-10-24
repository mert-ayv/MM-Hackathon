# Raw-material review (P08, P18, P16): for Emre's agent

Offline review on Sat 24 Oct, ~16:30 (cost function, replays, synthetic threads; no quota used). Raw material stays routed to **Emre's agent**, now pinned to base params (`router.py`: `"raw_material": "emre/base"`). It measures best: P08 0.549, P18 0.467, against 0.516 for `v7` and 0.419 for `v13`.

## Where the deals lose (C_deal − C_best)

| Deal | Score | Price level | Clause | Payment |
| --- | --- | --- | --- | --- |
| P08 Emre: 5.47, 5 % deadband, 90 d | 0.549 | 69.9k € (0.40) | 9.3k (0.05) | 0 |
| P18 Emre: 5.50, 5 % deadband, 90 d | 0.467 | 36.3k € | 2.3k | 0 |

- **The structure is already right.** Take the clause (both suppliers refuse a fixed price beyond 12 months), with a 5 % deadband (it's worth about 12 cents to us and they give it for 5–10 cents), at 90 days and 24–36 months.
- **88 % of the remaining gap is the price level.** Each cent per kg is worth 0.011 on P08 and 0.007 on P18. Both suppliers settle at 5.45–5.50 by reply 3, then send "final offer" with six rounds left.

## Bets for `csee/agents/emre.py` (Emre decides)

1. **Formula-price argument (largest upside, about +0.07–0.09 per case).** Use the supplier's own clause from `contract_clauses`:
   - **P08:** Donautal §3.2 gives Q4 = 5.45 × (1 + 0.45 × (3022.0/3102.0 − 1)) = **5.38**. Cite `idx:AS-14404@2026-05` and `@2026-08` (−2.6 %, verifiable) and say the new clause (base month 2026-08) must start at or below 5.38. Don't concede above 5.38 before its final offer.
   - **P18:** use the price before the PPI jump (5.26), rebased on AS-14404: 5.26 × 1.0267 = **5.40**. Werdenfels asked "which volume can you commit to?" at its final offer, and we never answered. Answer with `fc:370010@2026-09` (118,500 kg/yr in total).
2. **Keep negotiating after the final offer.** `final_push` of 0.5–1 % (base `v11` logic). Sandbox D01 moved 49.80 → 49.55, and there were 0 walk-aways in about 630 real supplier moves. A far-off push made DEMO-C1 walk, so keep the step small. 1 % ≈ +0.06 on P08 and +0.04 on P18.
3. **When the main sheet switches from fixed to a clause,** re-price the previous ask so total cost stays equal (`levers.price_for`). Today we give away about 0.9 % at that step.

**Policy for unseen raw-material suppliers:**
- **Index rising:** ask for a fixed price first; if a clause is insisted on, take the widest deadband.
- **Index falling:** ask for a clause with no deadband.
- **Always** 90 days; the contract should cover the horizon (36 months is free once a clause is in); 12 months is never worth it.

Full report and scripts: the lead's session scratchpad (`replay.py`, `decomp.py`, `synth.py`, `fixtest.py`).
