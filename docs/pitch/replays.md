# Three replays for the jury

Three real practice sessions, chosen because the e-mails read like a professional buyer's and each one shows a different skill:

| # | Case | Skill it shows | Score | House agent |
|---|---|---|---|---|
| 1 | P01, Brandlhuber +9.5 % | Reading the supplier, a payment-term menu and paced concessions | **0.988** | 0.97 |
| 2 | P02, Nordmark copper | Answering the lever the supplier named with a priced index clause | **0.733** | 0.74 |
| 3 | P05, RFQ with 3 bidders | Competition with verified rival quotes | **0.810** | 0.56 |

A reserve (P11, quality, 0.794 vs house 0.31) is at the end, with its caveats.

**How to show them.** Open the dashboard with `./dashboard/run.sh --open`, then go to `#/replay/<run folder>/case:<Pxx>`. Press `P` for projector type and use Demo speed. The arena's own replay is at `https://arena.tacto.ai/replay/<session_id>`, and the jury can open that one themselves.

Source of every quote below: `runs/<run folder>/case_<Pxx>.jsonl`. Its events are `message_sent`, `reply`, `decision` (with the reason), `result` and `backoffice`.

---

## 1. P01: the family foundry's +9.5 % (score 0.988)

- **Run:** `runs/20261024-204254-router-practice/` · **session `5629648d9eb67d0d`** · case:P01 · agent `router` at commit `2b74d94`, AI writer (ledger: "A/B dress rehearsal").
- **Outcome:** Brandlhuber asked for 126.53 → 138.55 (+9.5 %) from 1 Nov 2026. We closed at **132.10 (+4.4 %) from 1 Apr 2027**, paying in 14 days.
  - C fell from €1,153,780 (opening) to €1,097,524, a saving of **€56,256**.
  - C_best is €1,096,816, so we captured 98.8 % of the possible saving.
- **Before/after on the same case:** our v1 template agent scored 0.767. The v15 agent closed on 30-day terms for 0.926. The 14-day menu took it to 0.988.

**What the agent knew before writing a word** (dossier `starter-kit/csee/profiles/70110.json`, built from the data package):
- The letter gave 51 days' notice, but the contract requires 90.
- The owner wrote "Could you pay our invoices within 10 days?" (`doc:20260902-70110-M2`).
- The part is already priced below his full cost: our should-cost model says 132.64.
- The persona note: "repeats that in 2022 he kept supplying at the old price for a quarter. Acknowledge it explicitly."
- Arguments to avoid:
  - threatening to move the part to Kalwisz ("quoted 143.22 ... empty threat");
  - lecturing him about his stale costing sheet.

### Round by round

**R1, buyer.** The decision log says `plan anchor 12% below its opening value -> 121.48`. Excerpt from the e-mail:
> "We have not forgotten that in 2022 you kept supplying us at the old price for a full quarter. That loyalty matters to us … Your letter gives 51 days' notice (doc:20260911-70110-P01), while our agreement requires 90 days (ctr:4600070110)."

The e-mail offers three options, all valid from 2027-04-01:
- 121.48 at 90 days;
- 117.93 at 14 days;
- 117.42 at 30 days.

- *Why:* all three opening asks cost us about the same, and the owner's choice among them tells us how much he values cash. The pacing study found that an opening ask of about 12 % keeps the supplier talking, while deeper asks bring on its final offer sooner.

**R1, supplier: 135.50, 14 days, from 1 Apr 2027.** All three facts came back `verified`.
> "We checked the notice period data you cited; it holds and we took it into account. We did not know that - a fair point. … Faster payment helps our cash flow; that is reflected in the price."

- He picked the 14-day track, so his money rate is higher than ours. He also accepted the later start date.

**R2, buyer.** The decision log says `plan r2: c^ 2.25% gap 7.82% -> target 8.00%`.
- *In plain words:* he moved 2.25 %. We match what he will mirror and keep the remaining gap under the budget that avoids an early final offer.
- Offers: 128.76 at 14 days, plus two trade sheets (90 days; or an earlier start date at 124.53).

**R2 to R5, supplier.** His asks were 133.80, then 132.80, then 132.30, and finally **132.10, "This is our final offer (letztes Angebot)"**. Each step is smaller than the one before. That is the decaying concession cap our engine model predicts.
- Our own steps followed his (`c^ 0.58% gap 2.26%`, then `c^ 0.25% gap 1.00%`, then `c^ 0.28% gap 0.43% … (no-cross cap)`).
- Every e-mail kept the relationship tone:
> "We would be glad to meet in person and go through the delivery record together."

**R6, buyer: accept.** The decision log says `cheapest valid standing sheet C=1085718 < C_alt 1176178`. There was no push after the final offer: in our logs, 2 of 17 pushes after a final offer ended in a walk-away.

### What a real buyer recognises
- **Notice period vs contract.** A classic, checkable lever. The supplier conceded it: "we did not know that - a fair point."
- **Cash for price.** He asked for fast payment, and we sold him 14-day terms for a smaller increase.
- **Relationship handled deliberately.** We acknowledged the 2022 loyalty and made no empty threat.
  - The deal (132.10) sits at our should-cost estimate of his part (132.64). We did not squeeze a family supplier below cost; the case goal is "stabilise".
- **The increase is delayed 5 months.** That matches the 90-day notice argument.

**Blemish to know about.** Our R2 argument on on-time delivery (83.3 %) came back `duplicate`, and he answered "The delivery record you cited is not visible to us". The agent did not argue. It offered to go through the record together in the meeting.

---

## 2. P02: Nordmark names copper, we price a copper clause (score 0.733)

- **Run:** `runs/20261024-223428-router-practice/` · **session `f6c869429136eff0`** · case:P02 · agent `router` at commit `16c802c` (the locked final router), AI writer.
- **The same move in two earlier sessions:**
  - `a50fee95c5392d93` (router, 20:42), identical result;
  - `e12ba8b1ded8b5f0` (`mert-lever/v14`), the first time it happened.
- **Outcome:** the current price is 348.32, and Nordmark asked 370.96 (+6.5 %). We closed at **362.00 (+3.9 %) with 90-day payment** (its quote said 30) and a copper clause.
  - The clause is on CU-NOTATION, with a 20 % material share and a 5 % deadband.
  - C fell from €2,282,867 to €2,248,166, a saving of **€34,701**.
- **Score history on this case:**

| Attempt | Score |
|---|---|
| v13 | 0.441 |
| Our LLM strategist (previous best) | 0.633 |
| This lever answer | **0.733** (the engine model had predicted 0.736) |

### Round by round

**R0, supplier quote:**
> "CU-NOTATION rose 47.7 % in twelve months and is 20 % of our cost. … no Preisgleitklausel."

- The supplier itself named the lever: copper risk. Code parses that sentence (series, rise, share) and checks that an index clause on that series is an allowed term in this case.

**R1, buyer.** The decision log says `plan anchor 12% below its opening value -> 330.85; levers: index_clause->362.0 (acceptable (p_ind 360.38))`. Three packages:
> "1. EUR 330.85 per unit, payment at 90 days net, fixed price.
> 2. EUR 362.00 per unit, payment at 90 days net, with a price adjustment clause on CU-NOTATION (material share 20%, deadband 5%, base month August 2026).
> 3. EUR 325.28 per unit, payment at 14 days net, fixed price."

The e-mail also carried one argument: "Our demand forecast for this part grows +11.9% (fc:350011@2026-09)."
- *Why:* the cost engine prices the clause sheet. Copper risk is worth more to Nordmark than the clause costs us, especially with a 5 % deadband, under which small copper moves are not passed on. So we can offer 362 with the clause, below its 370.96 ask, and still be inside the supplier's acceptance band.

**R1, supplier: `agreed`.** The forecast came back `verified`.
> "We checked the volume change data you cited; it holds and we took it into account. … We accept your proposed package 2 at EUR 362.00 per unit, including the CU-NOTATION price adjustment clause and 90 days net payment."

- Back office (session `e12ba8b1ded8b5f0`): "Read the buyer's e-mail: … term sheets and … cited fact to check; we agree."

**R2, buyer: accept.** The decision log says `cheapest valid standing sheet C=2216127 < C_alt 2604228`.
- *Why accept at once:* pushing this same supplier after its final offer made it walk away. In session `bb4c42cd1a037ae0` (v15), the push from 372.20 to 369.22 ended in a walk-away and scored 0; accepting would have scored 0.48.

### What a real buyer recognises
- **The textbook answer to a raw-material increase:** don't fight the index, share it. An index clause with a deadband turns a one-off +6.5 % into a smaller base increase plus a transparent risk-sharing rule.
- **Choice instead of ultimatum.** Three packages let the supplier tell us what it values. It chose the clause.
- **Honest note for Q&A:** 0.733 is level with the house agent (0.74), not above it. This replay shows the reasoning, not a record.

**Glitch to know about (visible in the replay).** The sentence "Our package 2 gives you a Preisgleitklausel on CU-NOTATION … at EUR 362.00 per unit." is appended **after the signature**.
- It comes from `csee/agents/mert.py` (`explain()`). That code only inserts the line before the template signature "Best regards …", and the AI writer signs with "Kind regards".
- All 7 logged e-mails that contain such a lever note have the same problem.
- When showing this replay, crop the screenshot or mention it.

---

## 3. P05: an RFQ with three machine shops (score 0.810 vs house 0.56)

- **Run:** `runs/20261024-223428-router-practice/` · **session `6c011ef0be058563`** · case:P05 · agent `router` at commit `16c802c`, AI writer.
- **Same score in other runs:** `d8788b7fd32fa596` and `de7493b34e88c0d6`. Do not show `d8788b7fd32fa596`: one of its e-mails has a duplicated, truncated option line, and one bidder walked.
- **The case:** a new HX pump shaft, 4,200 pieces a year for 2 years, with the must-have lead time ≤ 42 days. The opening quotes were:

| Bidder | Opening quote |
|---|---|
| Dralveck (DE) | 36.00 |
| Hrvelec (CZ) | 31.50, but at 52 days, which breaks the must-have |
| Fuchsreiter (DE) | 38.50 |

- **Outcome:** we closed with **Dralveck at 28.13**: 35-day lead time, 30-day payment. That is −21.9 % on its quote and −22.7 % on today's 36.39.
  - C fell from €305,545 to €238,996, a saving of **€66,549**.
  - The house agent scores 0.56 on this case, and our v1 scored 0.352.

### Round by round

**R1, buyer: three e-mails in parallel**, each with arguments picked for that bidder:
- **To Dralveck and Fuchsreiter:** "We hold a competing offer at EUR 31.50 per unit (offer:70240-0)." Also on-time delivery, and for Fuchsreiter the news "looks for new customers (news:20260309-03)".
- **To Hrvelec:** "Alloy surcharge … changed -5.5% over the last three months" and "cold drawing of bars changed -2.1%", both cost drivers of a turned steel shaft.
- Every message offers two packages: 90-day payment, or a slightly lower price at 30 days, both at 35-day lead time.

**R1, suppliers.** Every argument came back `verified`. The back office shows what the rival quote did:
> Dralveck owner → team: "The buyer shows a much lower rival quote. I give half the step now and check the rest."
> (next round) team → Owner: "Checked: give the rest of the step."

Replies:
- **Dralveck** went from 36.00 to 30.50: "you make a fair point so I am coming down."
- **Fuchsreiter** went from 38.50 to 30.50.
- **Hrvelec** offered 31.00, but only at 52 days, which breaks our must-have. Its 35-day price went *up* to 34.50.

**R2, buyer.** Concessions are sized on each bidder's own step:
- Dralveck: `concede 0.61 of gap 2.42 (early, their step 5.50)`;
- Fuchsreiter: `concede 0.38 of gap 1.52 (early, their step 8.00)`.
- To Hrvelec, the now-verified rival bid: "We hold a competing offer at EUR 30.50 per unit (offer:70250-1)."
- To Dralveck:
> "Your standard 35-day lead time works for us, so no overtime premium is needed. The HX shaft is new, multi-year business, and it would fit well with your free capacity."

**R2, suppliers.**
- **Dralveck: `agreed` at 28.13**, 30 days, 35-day lead time: "We can accept your terms and await your order."
- **Fuchsreiter: `agreed` at 28.80.**
- **Hrvelec** matched 30.50, but again only at 52 days. Its 35-day price stayed at 34.50.

**R3, buyer: accept Dralveck.** The decision log says `cheapest valid standing sheet C=238996`. The other bidders' threads are closed by the coordinator.

### What a real buyer recognises
- **A proper RFQ round.** Each bidder sees a real, checkable competing price, and the agent compares bids on **total cost**, not on unit price alone.
  - Hrvelec's 31.00 headline looked cheapest, but it breaks the lead-time must-have.
- **Different arguments for different suppliers.** Index falls go to the shop whose cost they drive; the rival price goes to the shops that were dearer.
- **Treats owners like owners.** "Hallo Herr Dralveck", short and direct, in the register of his own e-mails.
- **Honest note for Q&A.** The 31.50 rival price we cited to the German shops is true and verified, but it came with a 52-day lead time, and we did not say so. See `qa.md`.

---

## Reserve: P11, quality first (0.794 vs house 0.31)

- **Run:** `runs/20261024-223203-mert-quality-menu-v14a-practice/` · **session `683eaea1caebb9f8`** · agent `mert-quality-menu/v14a` at `bfff391`. This is the router's quality route.
- **Story:** Kalwisz (red scorecard: 63.5 % on time, 2,376 ppm) opened with **47.00 at 6,400 ppm**. We closed at **45.00 at 300 ppm**: a commitment 21× tighter, at a lower price. C fell by €75,446.
- **How:** each round we sent a menu of 300 / 800 / 1,500 ppm at equal cost to us, with steps of +0.55, above the supplier's 0.50 price tick, so every step was mirrored. The supplier committed to 300 ppm in round 2 and sent its 8D report.
- **Caveats:**
  - The replication run scored 0.71 (`cf8d8d57302979ef`).
  - The supplier asked for faster payment in every reply, but payment is **fixed at 60 days** in this case and not negotiable. Our e-mails deferred it ("will come back to you on this point separately"), which a reader may find evasive.
  - Use this case for the number (best result against the house agent), not as the walk-through.
