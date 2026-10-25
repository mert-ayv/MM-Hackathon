# 5-minute pitch outline (csee-base)

**Story in one line:** *The language model reads and writes like a buyer, math decides every number, guardrails protect the deal, and an agentic research loop found the strategy.*

Every number below has its source in brackets. Leave the `[LIVE FINAL]` slots for the final's result.

## The numbers that matter (pick 3-5)

| Number | What it means | Source |
|---|---|---|
| **0.78 vs 0.697** | Practice board mean (best per case) vs Tacto's house agent | README "Results" |
| **0.762 / 0.772** | The final router played once on all 10 cases, twice; every case closed with a deal | runs `20261024-204254-router-practice`, `20261024-223428-router-practice` |
| **0.481 → 0.77** | Our v1 agent vs the final router, same 10 cases | ARCHITECTURE changelog v1; runs above |
| **0.81 vs 0.56 · 0.79 vs 0.31 · 0.59 vs 0.39** | The three hardest cases (RFQ P05, quality P11, raw material P18) vs the house agent | ledger `experiments/*.jsonl` |
| **260 sessions** | Supplier bots decoded; the fitted model predicts the next price within about 0.6 % | README "What we learned" |
| **230 of 244** | Fact checks on our cited arguments came back `verified`; the other 14 were `duplicate`, and none were contradicted (91 logged practice sessions) | `runs/*practice*/` reply `claim_results` |
| **966 cases** | Robustness sweep over all 46 final suppliers: no crash, no broken must-have, no walk-away while a better deal stood | ARCHITECTURE "Sat 23:30" |
| **3 vs 36** | Walk-aways on 531 perturbed supplier models: our move planner vs our rule policy (score 0.658 vs 0.615) | README / ARCHITECTURE "Sat 20:00" |

Careful with "beats the house agent on 8 of 10". README says so, but CHALLENGE.md shows the house values only to 2 decimals.
- At that precision we are clearly ahead on P01, P05, P11 and P18.
- We are within ±0.01 on P02, P03, P04, P08 and P10.
- We are behind on P07 (0.766 vs 0.78).
- Safer wording: **"beats or matches the house agent on 9 of 10, with large wins on the hardest cases"**, or simply quote the means.

---

## Slide 1: Hook (0:00-0:30)
- **On screen:** Brandlhuber's letter, "+9.5 % on HN volute casings", next to our result, "+4.4 %, five months later, 14-day payment."
- **Say:** "A family foundry asks for 9.5 %. Our agent answered with the owner's own history: his 2022 loyalty, his 51-day notice against a 90-day contract, his request for fast payment. He wrote back *'We did not know that - a fair point.'* We closed at 98.8 % of the best possible deal."
- **Source:** replays.md #1 (session `5629648d9eb67d0d`).

## Slide 2: The job and how it is scored (0:30-0:50)
- **The job:** an autonomous buyer. It negotiates by e-mail with 1-3 supplier bots, then accepts one standing offer or walks away. No human is in the loop.
- **How it is scored:** score = (C_open − C_deal) / (C_open − C_best) on **total cost**: price, payment terms, freight, lead time, quality, index risk and supplier health. It is not unit price.
- **The bar:** Tacto's house agent averages 0.697.

## Slide 3: Architecture, "LLM reads and writes, math decides" (0:50-1:40)
Show it as four boxes:

1. **Supplier intelligence (offline).**
   - A dossier for all 46 suppliers, built from letters, call notes, news, scorecards, order history and should-cost. Every cited ID is checked by code.
   - It records cash pressure, hedges, levers each supplier values, and arguments that backfire.
2. **Commercial engine (code).**
   - The arena's exact total-cost model. We reproduce its deal cost to the euro on all 40 of our deals (README).
   - It prices every package and every lever, and our alternative is the walk-away line.
3. **Negotiation policy (code).**
   - Opening anchor, concession pacing and the 1-3 term sheets per e-mail. It answers levers the supplier names and decides accept or walk.
   - A router picks the measured winner per case type.
4. **Writer (Claude).**
   - It reads the supplier's e-mail and writes the reply in its register.
   - Numbers and claim sentences are fixed by code and kept word for word. IDs the model invents are deleted.
   - If the model is slow, a template is sent instead.

**Guardrails band underneath:**
- accept only the supplier's standing sheet;
- never accept above our alternative or against a must-have;
- never push after a final offer;
- close before the wave cap.

## Slide 4: What we learned about the suppliers, and from where (1:40-2:30)
- **Source:** our own sessions. Each round's back-office note exposes the bot's decision ("My call: counter", "I give half the step now and check the rest"). We fitted a model on 260 sessions.
- **Finding:** the bots behave like a classic **tit-for-tat negotiator** (Faratin, Sierra & Jennings 1998).
  - They mirror our concession up to a cap that shrinks each round.
  - They hold when we don't move.
  - They send a final offer after a fixed patience: median 4 replies, measured over 1,132 supplier replies.
- **What it means for us:**
  - Concede exactly what they will mirror, early. This is the best response to tit-for-tat (de Jonge 2022).
  - Don't open too deep: deep asks shorten their patience by 1-2 replies.
  - Never push after a final offer: 2 of 17 such pushes ended in a walk-away.
- **Visual:** P01's supplier asks, step by step: 138.55 → 135.50 → 133.80 → 132.80 → 132.30 → 132.10 "final". Each step is smaller than the last.

## Slide 5: One replay, live (2:30-3:40)
Pick **P02** (one round, easy to follow) or **P01** (richer story). Use the dashboard Replay at Demo speed; the walk-through is in replays.md.
- **P02 in three beats:**
  1. The supplier blames copper: "+47.7 %, 20 % of our cost".
  2. Our engine prices a copper clause with a 5 % deadband at 362 (its ask was 370.96), as one of three packages.
  3. The supplier writes "We accept your proposed package 2", and we accept.
- **The close:** "0.633 → 0.733 on this case, and the engine model predicted 0.736 before we spent a session."
- If time is short, show the **back-office panel** from P05: "The buyer shows a much lower rival quote. I give half the step now and check the rest."

## Slide 6: Results (3:40-4:15)
- Practice: **0.78 mean vs 0.697** for the house agent. The final router, played in single shots, scored **0.762 and 0.772**, and every case closed with a deal.
- Biggest gains are on the hard cases: RFQ **0.81 vs 0.56**, quality **0.79 vs 0.31**, raw material **0.59 vs 0.39**.
- From **v1 0.481 to 0.77** in one day. Every step is in the ARCHITECTURE changelog, with its evidence.
- `[LIVE FINAL]`: points out of 500, rank, € saved and walk-aways, taken from our own logs only.

## Slide 7: How we decided, including what we rejected (4:15-4:45)
- **The research loop.**
  - Claude Code subagents fitted the bot model, ran the literature review (MESOs, tit-for-tat, Pactum/Walmart menus) and simulated 531 perturbed suppliers.
  - Every change climbed one ladder: free sandbox → fitted engine model → one logged practice session. The ledger has 386 rows: who, agent, commit, score.
- **Rejected because we measured it:**
  - **An LLM deciding the moves.** Claude with our pricing functions as tools never improved a move where it changed one (P07 0.728 vs 0.766, sandbox D02 0.67 vs 0.72). Our LLM strategist scored P05 0.52 and 0.72, against 0.81 for the rule policy.
  - **Pushing after a final offer.** On P02 one push of −0.8 % made the supplier walk: 0.48 → 0.
  - **Persuasion tricks and prompt injection.** The bots decide by rules, and the jury reads every replay.
- **The point to make:** "We let the data, not the demo, decide where the LLM belongs."

## Slide 8: Close (4:45-5:00)
- **Built for the final:** only known suppliers appear in it, all 46 are in the dossier, and the Sunday data release is merged at runtime. Threads run in parallel with time-aware closing, and failed cases are retried.
- **Last line:** "*It reads the supplier before it negotiates, trades what is cheap for us for what is valuable to them, and code checks every euro.*"

---

## Material for the two 1-minute videos

**Demo video**
- 0-10 s: three supplier e-mails arrive (P05 openings).
- 10-40 s: Replay of P05 or P01 at Demo speed. The gauge fills, and the claim badges turn `verified`.
- 40-55 s: the cost-by-term waterfall for the deal sheet.
- 55-60 s: "Code decides every number. The language model only words it."

**Technical video**
- Build up slide 3's four boxes plus the guardrails.
- Then the research ladder (sandbox → engine model → practice) and the ledger.
- End on the tit-for-tat finding, with P01's shrinking steps as the chart.
