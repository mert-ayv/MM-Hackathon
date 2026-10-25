# Design decisions, and why

Each section names what we chose, what we tried or considered instead, and what our own sessions showed.
Sources: `README.md` "Our approach", `docs/ARCHITECTURE.md` (changelog and experiment log), `docs/pitch/qa.md`,
`docs/pitch/replays.md`, `starter-kit/csee/agents/router.py`, the ledger `experiments/*.jsonl`.

## 1. Code decides every number; the language model only reads and writes

**Choice.** A deterministic engine computes every price, payment term, start date and package. Claude reads the
supplier's e-mail and writes our reply around those fixed numbers.

**Alternative we tried.** We let the model choose the moves, twice. First, Claude with our pricing functions as
tools: wherever it changed a move, the result was worse. On P07 it scored 0.728 against 0.766, because an extra
60-day payment option it added pulled the supplier's concessions onto the wrong track. Each move also took 10 to
20 seconds of a 60-second clock. Second, a full LLM strategist: P05 scored 0.52 and 0.72, against 0.81 for the
rule policy.

**Why it lost.** The supplier bots price by rules over numbers. Good reasoning in words does not move them; a
package priced to the euro does. Total cost has many parts (price, payment days, freight, lead time, quality,
index risk), and our engine reproduces the arena's own cost to the euro on all 40 of our deals. So the model stays
where it measurably helps: reading the e-mail and answering questions. On P07, answering "Which volume can you
commit to?" brought a concession.

## 2. Model the opponent instead of using a generic strategy

**Choice.** We fitted a model of the supplier bots from 260 of our own sessions. Each round's back-office note
reveals the bot's decision, which made this possible. The model predicts the next supplier price within about 0.6 %.

**What it showed.** The bots behave like a classic tit-for-tat negotiator. They mirror our concession up to a
cap that shrinks every round. They hold when we don't move. They send a final offer after a fixed patience, a
median of 4 replies over 1,132 replies. An opening ask more than about 8 to 10 % below their floor cuts that
patience by 1 to 2 replies: D01 went from 6 to 3, P07 from 4 to 2.

**What we built from it.** A move planner that estimates each supplier's cap from its first replies, then concedes
exactly what the supplier will mirror while keeping the gap small enough to avoid an early final offer. On 531
perturbed supplier models it scored 0.658 against 0.615 for our earlier rule policy, with 3 walk-aways instead
of 36.

## 3. Never push after a final offer

**Alternative we tried.** The sandbox suggested pushing was safe: 10 of 11 small pushes improved the deal. We
shipped a 0.8 % push (v15). On the real P02 supplier it walked away, and the case scored 0 instead of 0.48. Across
our logs, 2 of 17 pushes after a final offer ended in a walk-away. A tighter, gated push of only 0.55 % still made
P18 walk ("we have already reached our absolute limit").

**Why we chose not to.** The expected value of a push is negative. We take the money earlier instead, by
conceding exactly what the supplier mirrors. The lesson we kept: sandbox evidence alone can mislead, so a change
needs the fitted model and a real session behind it.

## 4. Offer up to three packages per e-mail, not one counter-offer

**Choice.** Where it pays, we send packages that cost us the same, such as a lower price with 14-day payment next
to a higher price with 30-day payment. The one the supplier picks reveals how much it values cash.

**Evidence.** On P01 the owner picked 14-day payment, which moved the case from 0.926 to 0.988. The same menu did
nothing on P03 and P04: those suppliers value cash below our 8 % (P03 about 4.1 %), so they ignored it. We therefore
route the menu only to price-increase cases with cash-hungry suppliers, instead of using it everywhere.

## 5. Only true, sourced arguments, chosen by what actually moved prices

**Choice.** Every factual sentence is built by code from the data package, with its source ID, and inserted word
for word. The bots fact-check each one. In 91 logged practice sessions, 230 of 244 checks came back verified, the
other 14 duplicate, and none contradicted.

**What we dropped, and why.** We kept only argument types that moved a price. Order-history arguments moved a price
0 times in 26, so they are gone. Rising indices "confirm their case", so we cite only falling ones. Citing an index
the supplier has hedged does not help: skipping it on P08 took us from 0.711 to 0.754. We rejected persuasion
tricks and prompt injection outright; the bots decide by rules, and the jury reads every replay.

## 6. Answer the supplier's lever with a priced clause

**Choice.** When a supplier names a cost driver, we answer with a clause priced by the engine rather than arguing
about price. On P02 the supplier blamed copper; we offered a copper clause with a 5 % deadband, and it agreed in
round 1. That moved the case from 0.633 to 0.733, and the engine model had predicted 0.736 before we spent a
session. A fixed-price ladder on the same case scored 0.499, because the bot stalls without the clause.

## 7. A router per case type, not one agent

**Choice.** Different case types reward different policies, so the final agent routes each type to the version
that won it in measured A/B runs. Example: the deep opening that wins RFQs (P05 0.831, 0.831, 0.854) is wrong for
bundling, where the same deep anchor drew a final offer at reply 2.

## 8. Measure before shipping

Practice sessions were scarce (400 per 24 hours, shared by four people), so every change climbed one ladder: the
free sandbox, then the fitted bot model, then one logged practice session only if the model predicted a gain. Every
session is logged with author, agent, commit and score. For robustness we ran a 966-case sweep over all 46 final
suppliers and a 322-case run on the Live-Final clock. It found no crash and no broken must-have, and surfaced three
loss mechanisms, which we fixed.

## Result

From our first agent at 0.481 to the final router at 0.77 on the same 10 practice cases. Our best-per-case practice
mean is 0.81, against 0.70 for Tacto's house agent, with the largest gains on the hardest cases: RFQ 0.81 vs 0.56,
quality 0.79 vs 0.31, raw material 0.59 vs 0.39.
