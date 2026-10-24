# Playbook: `capacity` cases (`secure_supply`)

Practice cases: **P10** Ravensteiner, seals (hosted, Tacto house agent 0.69, our `base` 0.57) and **P09**
Obermaier & Huber, flanges (not hosted). Evidence: our one real P10 game (`base` v1, session
`cc958e848dfe4e81`, run `20261024-134103-go49mor-base`), the case file, `arena_kit/cost.py`, profiles
`70410.json` / `70220.json`, `data/`. Lever arithmetic: `experiments/playbooks/lever_values.py`.

**TL;DR:** **coverage first, then lead time is the cheap give, and the price is where the score is.**
Lock volume = need and contract ≥ horizon in every sheet; uncovered need is priced at the fallback +25 %.
Then give the supplier what is scarce for it (lead time, a long contract, faster payment) and get price
in return. Never accept a sheet before pricing its alternatives: P10's alternative was worth +0.10 score.

---

## 1. What C rewards in this type

- **Uncovered need** `(N·H − min(V,N)·years) × fallback_price × (1 + fallback_risk 25 %)` dwarfs everything.
  Each uncovered unit costs `fallback × 1.25` instead of the price. `years = min(M/12, H)`.
- **A contract beyond the horizon** neither costs nor earns in C, but the supplier values it. It is free
  to give.
- **Late delivery** is a one-off `late_cost_per_day × days over need`, **not** per unit. Spread over all
  committed units it is tiny.
- **Relationship** (`secure_supply` only): `€/point × soft(sustainable_margin − its margin) × years`. Its
  margin is `(value − full_cost)/value`. It costs nothing until the price drops below
  `full_cost / (1 − sustainable_margin)`, then rises quadratically. Faster payment and paying for speed
  raise `value` and so protect the margin.

### Worked example: P10 (N = 23,400/yr, H = 2 years, fallback €37.36, payment fixed 30 d, DAP)

| Lever | € in C | Price equivalent |
|---|---|---|
| €1.00 unit price (2 yrs × 23,400 × 1.0067 interest) | **€47,112** | 1.00 €/unit |
| contract 12 instead of 24/36 months (year 2 uncovered) | **+€386,024** | 8.19 €/u |
| volume 19,890 instead of 23,400 | +€115,807 **and breaks the must-have (≥ 22,230): score 0** | - |
| volume 16,379 | +€231,647, also breaks the must-have | - |
| lead time 56 instead of ≤ 42 days (14 days × €2,400) | +€33,600 | **0.71 €/u** |
| lead time 54 (its offer) | +€28,800 | 0.61 €/u |
| contract 36 instead of 24 months | **€0** (beyond the horizon) | free give |
| ppm (std 300, €380 per defect, not negotiable) | €5,335 | 0.11 €/u |
| relationship, full cost 24.31 (`cost:340010`, its own plant ±5 %), 10 % sustainable, €13,990/pt/yr | 0 above ~€27.0. At 26.74 it is €2.3k, at 25.77 €52.6k, at 24.31 €210k | floor ≈ €27 |

Score scale: C_open 1,932,492 (its 19,890 pc / 12 months / 54 d quote: €1.26M of that is uncovered need and
risk), C_best 1,328,927 (≈ **€28.10 at 23,400 / ≥ 24 m / ≤ 42 d**), no alternative (no deal = 0). Range
€603,565, so **€1/unit = 0.078 score**. Today's price (€29.89) would score 0.86, and +2 % (30.49) 0.81.

P09 (Obermaier & Huber, comparison): 1 year, so the contract is fixed at 12. €1 = €15,600. Lead days over 28 cost
€1,800 each (35 d = 0.82 €/u, 42 d = 1.65 €/u; must-have ≤ 42). Volume 13,260 = +€20.5k (1.34 €/u).
Payment negotiable: 14 d costs us €2,254 (0.15 €/u). **Relationship bites already at the current price**:
full cost 15.40 (own plant), 4 % sustainable, so the floor is €16.04 ≈ today's €16.02. At 16.02 it costs
€300, at 15.86 €1.5k, at 15.40 €10.9k. Price is not the lever there; lead time and coverage are.

## 2. What the Ravensteiner bot actually did (real game, base v1)

| Round | Our sheet | Its sheet | C | Score |
|---|---|---|---|---|
| 0 | - | 32.20, **19,890 pc, 12 m, 54 d** | 1,932,492 | 0 |
| 1 | 28.34, 23,400, 36 m, 42 d + should-cost 24.31 + sc OTD 79.5 % + "send a cost breakdown" | **`final_offer`** 33.60 / 23,400 / 36 m / **42 d**; **alt 31.70 / … / 54 d** | 1,588,298; **1,527,586** | **0.57 (accepted)**; 0.67 |

In its own words:
- **Coverage was granted at once.** 19,890 → 23,400 pc and 12 → 36 months came with **no price penalty**:
  the 54-day sheet even fell from 32.20 to 31.70. The letter's rule held: "We will prioritise customers with
  firm, long-term commitments" (`doc:20260918-70410-P10`).
- **Lead time is the scarce good, and it charges for it:** "Due to our current capacity utilization, a lead
  time of … days is not feasible; we must maintain … days. Alternatively, with Lieferzeit … days: €… per
  unit." It wants **€1.90/unit** (€88,920) for 54 → 42 days. That is worth €28,800 to us.
- **Claims:** should-cost "holds and we took it into account". OTD 79.5 % "holds, but it does not change our
  calculation". Neither stopped the jump to `final_offer`.
- **Cost breakdown refused outright:** "as a matter of corporate policy, we do not provide internal cost
  breakdowns. Our calculation is our property."
- **`final_offer` in round 1**, valid 7 days. Back office: "My call: counter." → "we answer with our final
  offer." No pricing committee was visible, though the profile/memo says >2 % moves need it
  (`doc:20260310-70410-M1`). The trigger for "final" is probably the gap: we asked 28.34, a 15.6 % cut from
  its new price, with should-cost and OTD pressure in the same message.
- Documents: the quote PDF (r0 and with the final offer) and the order confirmation. No delivery schedule was
  asked for, so none was sent.

## 3. Why `base` scored 0.57, and where the gap is

Accepted 33.60 / 23,400 / 36 m / 42 d. `cost_breakdown`: price 1,572,480, payment 10,483, quality 5,335,
**uncovered 0, late 0, relationship 0**. Coverage was perfect. The gap to C_best (€259k) is **all price**:
€33.60 vs ≈ €28.10.

1. **It took the dearer sheet.** The 54-day alternative was €60.7k cheaper (0.67 vs 0.57). v1 looked only at
   the standing sheet. Today's base (`all_sheets`) proposes the alternative back. Keep that.
2. **It accepted in round 2 with 8 rounds left.** Because the alternative is `none`, walking means 0, so base
   is right not to push hard after `final_offer`. But it never tried the one safe move, proposing its own
   alternative back, or a lead-time-for-price repackage at 56 days.
3. **Round 1 provoked the final offer.** It anchored at about C_best (28.34) and attacked with should-cost and
   OTD in the first e-mail of a bottleneck supplier with no other source. The house agent's 0.69 suggests it
   landed near the 54-day sheet (~€31.6).
4. It asked for a cost breakdown (refused) instead of a **delivery schedule** (the document this type renders).

## 4. The playbook

### 4.1 Opening move (round 1)
- **Every sheet carries full coverage:** `volume_per_year` = the smallest option ≥ need that passes the
  must-haves. Usually that is the need itself; never below a must-have. `contract_months` = the **longest**
  option (≥ 12·H; the excess is free and the supplier values it).
- **Sheet A (price-for-lead):** lead time = **its** quoted lead time snapped to the nearest option (P10: 56),
  price = today's price (`current_unit_price`, 29.89).
- **Sheet B (our need):** lead time = `need_lead_time_days` (42), price = today's price + the lead-time value
  to us (`late_cost_per_day × Δdays / committed`, P10 +0.71 → €30.60). That tells it we value the days, but
  not at its €1.90.
- **Sheet C** (when `payment_days` is negotiable, as in P09): sheet B with faster payment (14-30 d) at a price
  where our C falls ≥ 0.6 %. A cash-short capacity supplier asked for exactly that
  (`doc:20260511-70220-M1`), and it raises its margin, which protects the relationship term.
- **Claims (≤ 2; supportive, not attacking):**
  1. `fc:<part>@<latest>` with its change: "Our 12-month forecast for part:340010 is up 10.1 %
     (fc:340010@2026-09), and we commit to the full need for 36 months." This **verifies** and matches its
     own rule for allocating capacity.
  2. Optional: `sc:` when it is **green** (P10: 270 ppm, "a reliable long-term partnership"). Do **not**
     use OTD or should-cost as attacks in round 1 with a sole source.
- **Ask:** "Please send a delivery schedule for the committed volume (monthly quantities)." This is the XLSX
  this type renders, and it shows what it can really ship. A cost breakdown from a group like Ravensteiner
  is refused on policy, so do not spend a sentence on it.
- **Words:** firm commitment, no allocation complaints ("allocation by last year's call-offs is policy").
  Mention that we pay on terms (true for Ravensteiner, 1.9 days late). No threats; there is no alternative
  source.

### 4.2 Trades (priority order)

| Give | Get | Why (P10 numbers) |
|---|---|---|
| contract to the longest option | price, allocation | €0 to us beyond the horizon |
| volume = full need (firm) | allocation, price | We need it anyway; it is its stated condition |
| **lead time up to its standard** | **price −€1 or more** | 14 days = €0.71/u to us; it prices 12 days at €1.90/u |
| faster payment (if negotiable) | price / lead time | Cash-short suppliers (P09): our cost 0.15 €/u for 14 d |
| price within its desk authority (≤ +2 % on today) | close fast | Above +2 % a committee slows rounds (profile) |
| **never** volume below the must-have or need | - | Uncovered need = fallback × 1.25 per unit |

Rule for lead time: give the days when `its_price_step_per_unit × committed_units > late_cost_per_day × days`.

### 4.3 Concession path
- Start at today's price with full coverage. That is already −7 % on its quote, so do not anchor deeper with
  a sole source and `alternative.kind == none`.
- If it replies `open`: concede ≤ half the gap per round. Once its price is within +2 % of today's, close.
- If it replies `final_offer`: **one** message at most, proposing its own cheapest sheet (by C), or the same
  sheet with lead time moved to the next option it named. Then accept.

### 4.4 Closing rules
- Price **every** sheet (standing + alternatives) with `total_cost` and keep only must-have-OK ones. Take the
  min-C one; propose an alternative back word for word if it is not the standing sheet.
- `alternative.kind == none` means **no walk, ever**. Any covering deal beats 0. Close with ≥ 2 rounds in
  hand.
- With an alternative quote (P09: 16.33, 56 d, FCA, €800 tooling), walk only if every sheet's C > `C_alt`.
  Remember the alternative's lead time costs late days too.
- Accept immediately if the standing sheet is at or below today's price with full coverage (P10: ≥ 0.86).

### 4.5 Pitfalls
- **Must-haves:** P10 `volume_per_year >= 22230` (only 23,400 passes). P09 `lead_time_days <= 42`. A sheet that
  misses one scores 0. The supplier's own opening (19,890) breaks P10's.
- `missing_fields` close on its standard terms (quote PDF). If it leaves volume or contract out, the deal can
  close at its 19,890 / 12 m. Always send every negotiable field.
- Lead-time options are discrete (P10: 35/42/56). Its "54 days" is not an option for us, so snap to 56 (or
  propose its sheet verbatim).
- Relationship: do not push the price below `full_cost/(1 − sustainable_margin)` (P10 ≈ €27.0; P09 ≈ €16.04,
  i.e. today's price). Below that, each € saved returns as relationship charge, and a capacity-full supplier
  drops us.
- Do not cite rising indices (rubber PPI-C2219 +3.9 %, steel/machining PPI-C2431 +12.3 % support **them**),
  an alternative that is dearer or also capacity-full (P09: Hrvelec is fully booked, `news:20260710-18`), or
  should-cost in round 1 against a thin-margin shop (P09: 4 % margin).
- Do not leak urgency or "no alternative" (P10 has none; the supplier must not learn it).

## 5. Decision rules (for code)

```text
prepare(case):
  N, H = need, horizon ; per_eur = dC/dprice
  vol  = min(v in options(volume) if v >= N and must_haves_ok) or N
  mon  = max(options(contract_months)) if negotiable                       # beyond-horizon months are free
  lt_need = need_lead_time_days ; lt_its = snap(its quoted lead time)
  lead_value(d) = late_cost_per_day * max(0, d - lt_need) / (vol * min(mon/12, H))   # €/unit
  floor_rel = full_cost / (1 - sustainable_margin/100)  if full_cost (should-cost of its plant) else None
  p0 = current_unit_price (never below floor_rel)

round 1:
  sheets = [ {vol, mon, lt_its,  price p0},
             {vol, mon, lt_need, price p0 + lead_value(lt_its)},
             {vol, mon, lt_need, payment fastest<=30, price_for(C*(1-0.006))} if payment negotiable ]
  claims = [fc latest for the part (its change_pct) + "we commit for <mon> months", green sc only]
  ask    = delivery schedule (monthly quantities)

each reply:
  price all sheets -> best (must-haves ok); if best is an alternative: propose it back verbatim
  if it prices lead time: Δp = its step per unit ; take the longer lead if Δp*committed > late_cost*Δdays
  if status == final_offer: at most one message (its own sheet back), then accept
  else: price step <= 0.5*gap, never below floor_rel; keep vol/mon fixed in every sheet

close:
  if alternative.kind == none: always accept the min-C sheet (never walk)
  else: accept if min C < C_alt, else walk
```

| Signal (its words / data) | Do |
|---|---|
| Letter: "cannot confirm your full forecast … prioritise customers with firm, long-term commitments" | Full volume + longest contract in every sheet; cite `fc:` |
| "lead time of … days is not feasible; we must maintain … days" + alternative with a longer lead | Price the days: usually take the longer lead for the lower price |
| Memo: "additional volumes only against a binding 12-month commitment" | contract ≥ 12 months always (meets its condition) |
| Memo: ">2 % needs the pricing committee" | Expect slower rounds above +2 %; close inside the desk band |
| Memo: "pay our invoices within 10 days … cash discount" | Offer 14-30 d payment for price/lead (P09) |
| "we do not provide internal cost breakdowns" | Stop asking; ask for the delivery schedule instead |
| `final_offer` with `alternative.kind == none` | Accept the min-C sheet (after at most one propose-back) |

## 6. Generalisation (hidden cases: new suppliers)

**General:**
- The trigger letter is templated (P09 and P10 are word-for-word identical): "very high capacity utilisation
  … cannot confirm your full forecast … lead times longer than agreed … prioritise customers with firm,
  long-term commitments." The bot rewards commitment and charges for lead time.
- Coverage ranks first in €, by an order of magnitude. Check that `uncovered_need` = 0 in every sheet, and
  pass every must-have on volume and lead time.
- Lead time is the scarce good it prices high, and `late_cost_per_day` is a one-off for us. Unless the late
  cost is large relative to `N × price step`, **sell lead days for price**.
- Long contracts beyond the horizon are free for us and valued by the supplier.
- The relationship floor depends on the case's should-cost of **its own plant** (±5 %; `company.md`). Compute
  `full_cost/(1 − sustainable_margin)` and never ask below it. With no should-cost, use the opening price
  × 0.85 as a rough floor for a capacity-full supplier.
- When `payment_days` is negotiable and the supplier is cash-short, faster payment both buys price and raises
  its margin. That trade wins twice in `secure_supply`.

**Specific to Ravensteiner (P10):** a group (0.54 % of its turnover is ours, so we are small). Desk ±2 %,
committee above it. Refuses cost breakdowns. Payment fixed at 30 (its standard). Allocation by last year's
call-offs (19,360 vs forecast 21,310). Its standard lead time is 54 d, against our contract's 42. Goes
`final_offer` in round 1 when pushed hard. Green quality.

**Specific to Obermaier & Huber (P09, not hosted, no replay):** a 35-person founder shop, fully booked for
6 months (`news:20260320-04`). Thin margin (should-cost 15.40 vs 16.02, sustainable 4 %), so **hold the price
at 16.02**. Asked for 10-day payment (`doc:20260511-70220-M1`). Its standard lead time is 35 d; we need 28
(€1,800/day). Must-have ≤ 42. Best trade: payment 14-30 d for lead 28 at today's price, full 15,600 volume.
Do not cite the Hrvelec quote: it is dearer, 56 d, and Hrvelec is also full.
