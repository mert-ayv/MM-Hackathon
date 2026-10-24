# Playbook: `quality` cases (`quality_first`)

Practice cases: **P11** Kalwisz, bearing brackets (hosted, Tacto house agent 0.31, our best 0.23) and
**P12** Aichbauer, base frames (not hosted). Evidence: our 2 real P11 games (`base` v1 session
`1b5c13e504dfbec2`, run `20261024-134103-go49mor-base`; `v7` session `29dd0eb541476e52`, fetched read-only),
the case file, `arena_kit/cost.py`, profiles `70140.json` / `70310.json`, `data/`. Lever arithmetic:
`experiments/playbooks/lever_values.py`.

**TL;DR:** in a quality case the **ppm commitment is cheap to get, and chargebacks are expensive to buy**.
Ask for the lowest ppm option with chargeback 0 (or the supplier's standard). Keep those terms fixed
from round 1 and negotiate only the price. A quality case is a **price** case once the ppm is locked.

---

## 1. What C rewards in this type

Quality term of C: `committed × ppm/1e6 × (cost_per_defect − min(chargeback, cost_per_defect))`.

- ppm and chargeback multiply each other. A low ppm makes the chargeback almost worthless to us, and a
  chargeback at or above `cost_per_defect` zeroes the term at any ppm.
- A chargeback above `cost_per_defect` is worth nothing more to us (P11: 500 counts as 450).
- No relationship term (`quality_first` is not in `RELATIONSHIP_GOALS`), so squeezing the price costs
  nothing in C. The only limit is the supplier's floor.
- `fallback_risk_pct` is low (8 %) and usually `alternative` is a dearer second source or today's contract.

### Worked example: P11 (N = 15,900/yr, 1 year, cost_per_defect €450, payment/lead/incoterm fixed)

| Lever | € in C | Price equivalent |
|---|---|---|
| €1.00 unit price | **€15,900** | 1.00 €/unit |
| 1 ppm point (chargeback 0) | €7.16 | 100 ppm = €716 = 0.045 €/u |
| ppm 1500 vs 300 (chargeback 0) | €8,586 | 0.54 €/u |
| ppm 6400 (opening) vs 300 | **€43,646** | 2.75 €/u |
| €1 chargeback at ppm 300 / 1500 | €4.77 / €23.85 | chargeback 500 vs 0 at 300 ppm = €2,146 = **0.135 €/u** |
| lead time, payment, incoterm | fixed in P11 | - |
| relationship | none (`quality_first`) | - |

Score scale: C_open 817,578 (€47.00 at **6,400 ppm**), C_best 722,500, C_alt 894,383 (Pfaffenreuth
quote 53.56 + €7.5k tooling). Range €95,078, so **€1/unit of price = 0.167 score**, and **6,400 → 300 ppm
alone = 0.46 score**. Almost half the range sits in the opening's bad ppm, and the supplier gives
that away for free (see §2).

Backed out from C_best: the best package is about **€43.8 at 300 ppm and chargeback 0** (or €43.90 at
any ppm with chargeback ≥ 450). That is 3 % **below** today's price of €45.15.

P12 (Aichbauer, for comparison): €1 = €8,980 (+ payment fixed at 45 d costs 0.33 % of spend). One ppm
point at the contract's chargeback of 150 = €1.12. Chargeback ≥ €275 zeroes the quality term. Lead time
over 23 days costs €450 a day (35 d = €5,400 = 0.60 €/u). No must-haves; the alternative is today's
contract (100.14, **4,118 ppm**, chargeback 150, 21 d).

## 2. What the Kalwisz bot actually did (real games)

| Game / round | Our sheet | Its sheet (standing / alternative) | C | Score if taken |
|---|---|---|---|---|
| opening | - | 47.00, **6400 ppm**, cb 0 (standard) | 817,578 | 0 |
| base r1 | 41.36 / 1500 / cb 500 + sc OTD + energy index | 50.00 / 1500 / 500; **alt 47.50 / 1500 / 150** | 819,486; **786,891** | 0; **0.32** |
| base r2 | 42.22 / 1500 / 500 + LCI-C +2.7 % | 49.00 / 1500 / 500 | 803,586 | 0.15 |
| base r3 | 43.32 / 1500 / 500 | 49.00; alt 48.00 / 1500 / 300 | 791,264 (alt) | 0.28 |
| base r4-6 | 44.42 → 45.52 | 48.50 / 1500 / 500, `final_offer` in r6 | 795,636 | **0.23 accepted** |
| v7 r1 | 36.66 / 1500 / 500 (22 % anchor) | 50.50 / 1500 / 500; alt 48.50 / 1500 / 150 | 827,436 | 0 |
| v7 r2 | 37.84 / **300 / 150** | **47.50 / 300 / 150** | **781,167** | **0.38** (best seen) |
| v7 r3-4 | 38.94 → 40.00 / 1500 / 500 (flipped back) | 49.50 / 1500 / 500, `final_offer` r4 | 811,536 | **0.06 accepted** |

What moved it, in its own words:
- **The chargeback is what it prices, not the ppm.** "1500 ppm with a 500 EUR chargeback adds too much
  risk, so I lowered the chargeback to … EUR to offer … EUR" (base r1). "we really can't go below … EUR if
  we keep the … EUR chargeback. Alternatively, with a chargeback of €300: €48.00" (base r3). "I put the
  chargeback at 150 because 500 is way too much risk" (v7 r1). It prices €500 → €150 at **€2.00-2.50/unit**
  and €500 → €300 at €1.00/unit. To us €500 vs €150 is worth €0.45/unit at 1500 ppm and €0.11/unit at
  300 ppm. **Buying a chargeback costs 5-20× what it is worth.** (It prices the chargeback at its real
  defect rate. The scorecard says 2,376 ppm, and its price steps imply about 5,000-7,000.)
- **A low ppm commitment is nearly free.** It took 6,400 → 1,500 ppm without a word, and 300 ppm with
  chargeback 150 came in **cheaper** (47.50) than 1,500 / 150 one round earlier (48.50): "We can do the …
  ppm and … EUR chargeback, but for that quality we need … EUR" (v7 r2).
- **Cash is its one want, and in P11 we cannot give it** (`payment_days` is a fixed term at 60). Every
  reply says it: "Faster payment would help us more than anything", "you keep ignoring it!" (base r6).
  The profile adds that we pay ~9 days late on average.
- **Data claims were verified but barely moved it.** sc OTD 63.5 % and PPI-D351 −3.7 %: "we see your figures,
  but we cannot give up margin right now". LCI-C +2.7 % (a cost driver that **rose**): "Your figures confirm
  our case: that driver rose". It still stepped 50 → 49 that round, which is the usual concession, not the
  claim's effect.
- **Cost breakdown:** "My team will get back to you on the cost breakdown". It never came. Only "Material
  accounts for about 30 % of our cost" was given.
- **Concessions are small and stop fast:** 50.00 → 49.00 → 49.00 → 48.50 → hold → `final_offer`, about €1.50
  (3 %) in total. Back office: "My call: counter" in r1-r4, then **"My call: hold" in r5 and r6**, then the
  final offer. No approvals or manager were involved. Every message was an Export Manager's desk call.
- **Flipping terms costs money.** v7 alternated 1500/500 → 300/150 → 1500/500. The supplier re-priced each set
  from scratch and settled on the dearest one.
- **The deep anchor bought nothing.** The 22 % anchor (36.66) drew a **higher** first counter (50.50) than the
  12 % anchor (41.36 → 50.00).
- No 8D report or delivery schedule was ever asked for, so none came. Documents seen: the quote PDF (r0 and at
  `final_offer`) and the order confirmation.

## 3. Why `base` scored 0.23 (and v7 0.06)

`cost_breakdown` of the accepted deal: price 771,150 + freight 24,486 + quality **0**. The whole gap to C_best
(€73k) is **price**: €48.50 vs ≈ €43.8. Base "bought" quality 0 with chargeback 500, and the supplier charged
about €2-3/unit for it. At 300 ppm and chargeback 0, quality would have cost only €2,146.

Root causes in code:
1. `levers.best_terms` sees ppm 1500 + chargeback 500 and 300 + 500 as equal (quality 0). The tie-break
   "supplier likes" picks ppm **1500** and the only zero-cost chargeback, **500**. The lever engine does not
   know that a chargeback costs the supplier `real_ppm × chargeback` and that the bot prices that cost in.
2. v1 accepted only the standing sheet and ignored the cheaper alternative (47.50/150: C 786,891, 0.32).
   Today's base proposes the alternative back (`all_sheets`), which is right.
3. Wrong claims: an energy index (irrelevant here) and a **rising** LCI-C. The scorecard claim cited OTD,
   never **ppm**. No QN claims.
4. Nothing in the message answers the cash plea. It cannot be a term in P11, but it can be said in words.
5. v7 `generic_trades` flipped the quality terms between rounds (fixed by the `sticky_terms` idea).

## 4. The playbook

### 4.1 Opening move (round 1)
- **Main sheet:** lowest ppm option, chargeback = the supplier's standard (usually 0), price = **today's
  price** (`current_unit_price`), or the opening price if that is lower. Every other negotiable term at its
  cheapest-for-us value.
- **Sheet 2, a probe:** the same at the next ppm option up (800), with the price €0.30-0.50 lower. The
  supplier's answer to two sheets shows whether it prices ppm at all.
- **Sheet 3** (only when the case has a cash lever, like `payment_days` in P12 or P09): the main sheet
  with faster payment (14-30 d) at a price that leaves our C at least 0.6 % lower (base's `trade_gain`).
  This is the trade it begs for.
- **Claims (≤ 3, one sentence each, figure and ID together):**
  1. `sc:<sup>@<latest>`: "Your rolling scorecard shows **2376 ppm** and 63.5 % on-time delivery
     (sc:70140@2026Q3), red." Say "ppm", so it is checked as the mean ppm.
  2. 1-2 `qn:` on **this part**, each in its own sentence with **its ppm** from `facts.json`, e.g.
     "Complaint qn:20004952 on the bearing bracket ran at 27778 ppm." The arena checks `qn` against its
     `ppm` field ("the mean ppm if you speak of quality"). If one sentence holds several IDs, the figure must
     be their mean, so keep it to one ID per sentence. Prefer recent QNs on this part with the highest ppm.
  3. Only if a driver **fell**: an index claim. Never cite a rising driver, energy, or currency in a quality
     case.
- **Ask in words:** "Please send your 8D report for part:310020 and your improvement plan." The 8D PDF carries
  its ppm commitment: read it and match our ppm option to it. Add: "We will pay on our 60-day terms on time
  from January." Kalwisz-type suppliers (cash-short, we pay late) value that, and it binds nothing.
- **Do not** ask for a price cut in words ("I cannot sign anything that lowers our margin now",
  `doc:20260715-70140-M1`). Frame the price as "holding today's price for a binding quality commitment".
- **Do not** threaten to resource unless the alternative is cheaper than its offer. P11's second source is
  18.6 % dearer, and citing it reveals that.

### 4.2 Trades (priority order)

| Give | Get | Why |
|---|---|---|
| **chargeback down to its standard (0)** | price −€1 to −2.5/unit | Worth ≤ 0.14 €/u to us at low ppm; it values it at €0.5-1.25/u per €100 |
| faster payment (if negotiable) | price or ppm | It values cash at 12-14 %/yr, we pay 8 %. The profile's #1 want |
| ppm one step up (300 → 800) | price −€0.25 or more | Only if it prices ppm (it did not in P11): 500 ppm = 0.23 €/u to us |
| lead time towards its standard (P12) | price | Only while `late_cost_per_day × days` < its price step × N |
| nothing for the ppm itself | lowest ppm | It conceded 6,400 → 300 for nothing |

Never trade the price **up** to buy a chargeback. If it insists on a chargeback (an "insisted" field twice),
take the lowest one it offers.

### 4.3 Concession path on price (terms frozen)
- Anchor = `min(current_unit_price, opening price)`, minus 2-3 % when it is not cash-short. P11 suggests
  anchoring deeper does not help.
- Concede in small steps, ≤ its own last step (`follow_share` ≤ 1). When it says "hold" or repeats a price
  twice, stop conceding and move a **term** instead (chargeback down, payment faster), or close.
- Keep the non-price terms identical in every sheet after round 1 (`sticky_terms`). Only the alternative
  sheets explore terms.

### 4.4 Closing rules
- Price **every** sheet it sends (standing and alternatives) with `total_cost`. If an alternative is cheaper,
  propose it back word for word and accept the `agreed` that follows. (A post-final message that adopts its
  own sheet has never caused a walk in our games: D02 several times.)
- Accept on `final_offer` when its cheapest sheet beats `C_alt` and we have no term left to trade. Do not
  push price after `final_offer`. One message proposing one of its own sheets back is allowed.
- Accept early when the standing sheet's score is ≥ 0.7 of the estimated range (`(C_open − C)/(C_open − C_best_est)`
  with `C_best_est` = C at 0.97 × current price and the lowest ppm).
- Walk away only if every sheet is dearer than `C_alt`. In P11 every offer seen (max 827k) beat `C_alt`
  (894k), so **never walk** there.

### 4.5 Pitfalls
- **Must-have:** P11 requires `ppm_commitment <= 1500`. The opening (6,400) breaks it, so never accept the
  opening. Check `must_haves_ok` on every sheet. Alternatives can break it too.
- Chargeback above `cost_per_defect` is wasted. Never ask more than `cost_per_defect`.
- `missing_fields` close on its **standard terms** (quote PDF). Kalwisz's standard chargeback is 0 and its
  ppm 6,400. A sheet without `ppm_commitment` would close at 6,400 ppm and break the must-have.
- Do not cite rising indices, energy in a casting quality case, a dearer second source as a threat, or
  "you are late with 8D" when the scorecard shows 0 overdue (both P11 and P12 show 0).
- Cite each ID once per case (duplicates are wasted) and use ≤ 3 claims per message.
- Do not leak that the alternative is dearer or that the part is sole-sourced.

## 5. Decision rules (for code)

```text
prepare(case):
  q = case.buyer.cost_per_defect ; N = need ; per_eur = dC/dprice
  ppm_opts = term_options.ppm_commitment (filtered by must-haves)
  cb_std   = supplier standard chargeback (quote PDF) or 0
  target   = {ppm: min(ppm_opts), chargeback: cb_std, other negotiables: best_terms() for us}
  anchor   = min(current_unit_price, opening_price) * (0.97 if not cash_short else 1.0)

round 1:
  sheets = [target@anchor,
            target{ppm: next_up(ppm_opts)}@anchor-0.3,
            target{payment_days: fastest<=30}@price_for(C*(1-0.006))  if payment_days negotiable]
  claims = [sc latest (say "ppm" + its ppm), qn on this part (max 2, recent, highest ppm; one ID per sentence
            with facts[qn].ppm), falling index only]
  ask    = "8D report + improvement plan for <part>"; promise on-time payment if profile/memo says we pay late

each reply:
  price all sheets (standing + alternatives) -> best_theirs (must-haves ok)
  if best_theirs is an alternative and cheaper: propose it back verbatim
  if reply prices chargeback: value_us = N*ppm/1e6*min(cb,q) ; if its price step > value_us: drop cb to cb_std
  if reply prices ppm:        value_us = N*q/1e6*Δppm         ; keep lower ppm only if its step < value_us
  freeze non-price terms = those of our main sheet (never flip)
  step = min(0.5*gap, its_last_step) ; if its_last_step == 0 twice: no price step, trade a term or close

close:
  accept min-C sheet when status in {final_offer, agreed} or rounds_left <= 1, if C < C_alt
  never walk when C < C_alt ; never push price after final_offer
```

| Signal (its words) | Do |
|---|---|
| "chargeback … too much risk", "with that … EUR chargeback hanging over us" | Drop the chargeback to its standard, ask for the price step |
| "Faster payment would help", "cash is tight", memo "pay within 10 days" | Offer faster payment if negotiable; otherwise promise on-time payment in words |
| "We can do the … ppm … but for that quality we need … EUR" | It prices ppm: compare its step with N·q·Δppm/1e6 |
| "cannot give up margin", "can't go any lower", two equal prices | Stop price steps, close on the cheapest sheet |
| `final_offer` | Accept the min-C sheet (propose an alternative back first if it is cheaper) |

## 6. Generalisation (hidden cases: new suppliers)

**General (from the cost function and the templated case design):**
- The trigger letter is our Supplier Quality's escalation ("scorecard is red … binding improvement plan …
  quality commitments and cost recovery"). The negotiables are some of {ppm, chargeback, price, lead time};
  ppm/chargeback options are [300, 800, 1500, 2500] / [0, 150, 300, 500].
- €-ranking of levers: price ≫ the ppm the opening states ≫ the ppm between options ≫ chargeback.
  Compute it per case with `lever_values`. Don't assume it.
- **A big opening ppm is a gift.** C_open uses the opening ppm. A bot that quotes a bad ppm gives most of the
  score range away for nothing when we fix ppm at the lowest option.
- **A supplier values the chargeback at its real defect rate** (the scorecard ppm or worse). The chargeback
  is always the dearest thing to buy from a red supplier. Our value is at the committed ppm.
- The scorecard (`sc:`) and QN (`qn:`) claims verify reliably; they "hold" but rarely move price on their
  own. Use them to justify the **quality terms**, not the price.
- Quality suppliers are often **cash-short** (a red scorecard plus a "pay within 10 days" memo). Faster
  payment is the currency when it is negotiable.

**Specific to Kalwisz (P11):**
- `payment_days` fixed at 60, so the cash lever is only in words. Bank-led restructuring
  (`news:20260911-28`), "no margin cuts". Sole source with its own tooling. Second source is +18.6 %.
- Real ppm 2,376 (scorecard), but it quotes 6,400. Export-manager persona, folksy and "eager to partner".
  Holds at about €48.50 after 4 counters.
- `quote:7300011`: its own quote at €45.15 (with 10-day payment). It is not in the P11 `refs`, so a citation
  may come back `irrelevant`. That is harmless, so try it once as a price reference.

**Specific to Aichbauer (P12, not hosted, no replay):** no must-haves. We are 11.3 % of its turnover.
Payment fixed at 45. Lead time negotiable (16-35; need 23, its standard 21). The alternative (today's
contract) already carries **4,118 ppm**, so any deal at ≤ 800 ppm and price ≤ 100.14 beats it by ~€3.7k.
Its standard chargeback is probably 150 (the contract's flat fee and today's terms). Check the quote PDF's
standard terms. If it is 150, ask for 150, not 0: going below the standard costs a price step for €0.12/u. VDA 6.3 grade C and cash memo `doc:20260911-70310-M1`.
