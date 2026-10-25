# Q&A prep (2 minutes, so 2-4 sentences per answer)

Sources: `docs/ARCHITECTURE.md` (ARCH), `README.md` "Our approach", `docs/notes/negotiation-research.md`, the ledger `experiments/*.jsonl` and the run logs `runs/*practice*/`. Session IDs refer to `docs/pitch/replays.md`.

## The three questions Tacto said they will ask

**1. "Why did your agent write that?"**
Every number and every package in an e-mail comes from code, and each move is logged with its reason. For example, P01 round 2 reads `plan r2: c^ 2.25% gap 7.82% -> target 8.00%`: the supplier moved 2.25 %, so we matched what it would mirror and kept the gap under the size that triggers an early final offer. The factual sentences ("Your letter gives 51 days' notice … our agreement requires 90 days") are built by code from the data package with their IDs, and the arena checks each one. In 91 logged practice sessions, 230 of 244 checks came back `verified`, the other 14 `duplicate`, and none contradicted. Claude only writes the words around those numbers, in the supplier's register.

**2. "Would it work on a real supplier?"**
The parts that win are standard procurement practice:
- total-cost evaluation instead of unit price;
- checkable facts (notice periods, index falls, rival quotes, forecasts);
- an index clause when the supplier blames a raw material;
- a choice of equal-cost packages (MESOs: Leonardelli et al. 2019; Pactum's menus are used with real Walmart vendors).

The bot-specific part is the pacing (the concession cap and patience). It is estimated live from the supplier's own replies, not hard-coded, so against a person it degrades to "reciprocate what the other side gives", which is what reciprocity research recommends. The guardrails (never above the alternative, never against a must-have) protect us with any counterpart.

**3. "What did your agent learn about suppliers, and from where?"**
Three sources:
- **Before the session:** a dossier per supplier (all 46) built from the data package. For example, Brandlhuber asked us in writing to pay within 10 days, and his part is priced below his own cost.
- **Within the session:** the planner estimates each supplier's concession cap and decay from its first replies. A payment menu shows its money rate by the option it picks: P01 picked 14 days, while P03/P04 ignored it, because they value cash below our 8 %.
- **Across sessions:** the back-office notes let us fit a model of the bots on 260 sessions, which predicts the next price within about 0.6 %. They are tit-for-tat negotiators with a shrinking cap and a fixed patience (median 4 replies over 1,132 replies).

## Tough questions

**"Isn't this overfitting to the 10 practice bots?"**
The final uses hidden cases, so we tested on more than the practice set:
- 531 perturbed supplier models: the planner scored 0.658 vs 0.615, with 3 walk-aways vs 36;
- a 966-case sweep over all 46 final suppliers with random must-haves, alternatives and round limits;
- a 322-case run on the Live-Final clock.

The sweep found no crash and no broken must-have, and it surfaced three loss mechanisms, which we fixed (0.596 → 0.606, 27 cases better, 0 worse). We also rejected changes that won one practice case but hurt elsewhere. Example: the v15 push after a final offer gained on P07 and turned P02 from 0.48 into a walk-away (0).

**"Why not let the LLM negotiate?"**
We tried it twice and measured it.
- **Claude with our pricing functions as tools:** it never improved a move where it changed one. P07 scored 0.728 vs 0.766, because its extra 60-day option pulled the supplier's concessions onto the wrong track. It also cost 10-20 s per move.
- **A full LLM strategist:** P05 scored 0.52 / 0.72 vs 0.81 for the rule policy.

The bots price numbers by rules, so sound reasoning in words doesn't move them. A package priced to the euro does. We kept the LLM where it measurably helps: reading their e-mail, answering their questions and writing in their register. In P07, answering "Which volume can you commit to?" brought a concession.

**"Isn't exploiting the bots' rules unethical, or gaming the arena?"**
Everything we send is a true, checkable fact or a real offer we would sign. We rejected prompt injection and feigned desperation. The only rival prices we cite are ones the arena can verify: the case's alternative quote and rival bids in the same RFQ. The "exploit" is reciprocity: give what the other side will mirror and don't bluff after a final offer. That is also good practice with humans. On relationship cases we stop at the supplier's cost: P01 closed at 132.10, against our should-cost of 132.64 for his part, because squeezing a sole-source family foundry below cost is bad procurement.

**"In P05 you cited Hrvelec's 31.50 to the German shops without saying it came at 52 days. Isn't that misleading?"**
The sentence is true and the arena verified it. Real buyers routinely cite the best competing price without the full sheet. But it is fair criticism: the stricter version is "31.50 at 52 days' lead time", and it would be a one-line change to the claim. We would make it for production use with real suppliers.

**"How does it handle a new supplier, or a case type it hasn't seen?"**
Tacto confirmed that every final supplier is one of the 46 in the data package, and each has a dossier. The Sunday release (new letters, news, a memo) is re-read at runtime, for example to detect new hedges. If a supplier has no dossier, the agent falls back to the case file, the cost engine and the live estimate of the supplier's cap. An unknown case type goes to a default route (`base-d/v14a`). Every dossier field is advisory and fails closed, so an error never blocks a move.

**"What if the LLM hallucinates a number or a fact?"**
It can't change one that counts:
- term sheets are structured data from code, not text;
- claim sentences are inserted word for word;
- any ID the model adds on its own is deleted;
- an ID next to a paraphrased figure is removed.

If the model is slow (over 15 s) or fails, the template e-mail is sent instead. 75 generated claims were re-checked against the facts file with 0 problems (ARCH v1.5), and in our 91 logged practice sessions no claim came back contradicted.

**"Why do you accept the first agreement instead of pushing for more? Aren't you leaving money on the table?"**
We measured it. 2 of 17 pushes after a final offer ended in a walk-away, and a later gated push of only 0.55 % also made a supplier walk ("we have already reached our absolute limit"). On P02, the same supplier walked when pushed and the case scored 0 instead of 0.48. The expected value of a push is negative here, so we take the money before the final offer instead: concede early and exactly what the supplier mirrors.

**"Your P02 score (0.733) is not above the house agent (0.74). Why show it?"**
Because it shows *why* a deal came about: the supplier named copper, and we answered with a priced clause in round 1. It moved our best on that case from 0.633 to 0.733, and the engine model had predicted 0.736 before we spent the session. For pure score, the hard cases are our case: RFQ 0.81 vs 0.56, quality 0.79 vs 0.31, raw material 0.59 vs 0.39.

**"What breaks it? What happens at the 8-minute wave cap?"**
Each supplier thread runs in parallel, and the runner closes before the cap using the slowest round time plus a margin.
- **Close fails three times:** it uses the kit's closing move, then walks away, so a session is never left open.
- **A case fails before closing:** it is replayed (409 → resume).

Every practice case finished inside the 390 s safety close, and local wave rehearsals ran with zero errors.

**"What would you build next for Tacto, with real customers?"**
1. Calibrate the pacing on real supplier histories. Human patience and step sizes replace the bot model, and the same estimation code applies.
2. Make the dossier step a product: letters, call notes and scorecards turned into a supplier brief with checked IDs.
3. Keep the human-review gate on the walk-away line and on the final accept, which are exactly the two decisions our guardrails already isolate.

## Numbers to have ready

| Number | What it is |
|---|---|
| Practice mean 0.78 vs house 0.697 | Final router single shots: 0.762 / 0.772, every case closed with a deal |
| v1 0.481 → 0.77 | From our first agent to the final router |
| P01 0.988 | 138.55 → 132.10, effective 5 months later, €56k saved |
| P02 0.733 | Copper clause with a 5 % deadband, agreed in round 1, €35k saved |
| P05 0.81 (house 0.56) | 36.00 → 28.13 (−22 %), €67k saved |
| P11 0.794 (house 0.31) | 6,400 → 300 ppm and 47.00 → 45.00; the replication run scored 0.71 |
| 260 sessions | Bot model fitted on them; next price within about 0.6 % |
| 1,132 replies | Pacing study: median patience of 4 replies |
| 531 perturbed models | Planner 0.658 vs 0.615; walk-aways 3 vs 36 |
| 966 + 322 cases | Robustness sweep and the timed run on the Live-Final clock |
| 230 / 244 claim checks | `verified`; the other 14 were `duplicate`, and none were contradicted |
| 386 ledger rows | Every session logged with author, agent, commit and score |
