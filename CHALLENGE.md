# The Tacto Challenge: everything in one place

Everything we know about the challenge: the task, how it's scored, the rules and the deadlines. It's compiled from the kick-off decks, Tacto's [brief](brief/brief.md), [API docs](brief/api.md), [submission guide](brief/submission.md), [starter kit README](starter-kit/README.md) and the [FAQ](https://arena.tacto.ai/faq). If anything here conflicts with Tacto's own docs, **theirs win**.

---

## TL;DR

- **Build an autonomous AI buyer agent.** It negotiates by e-mail, over an HTTP API, with Tacto's **supplier bots** for parts of a fictional pump maker, then **accepts a deal or walks away**.
- **Every deal is priced as one total cost C in €**: price, payment terms, freight, lead time, quality, coverage of our need, index clauses, tooling and, for strategic parts, the supplier's health.
- **Case score = (C_open − C_deal) / (C_open − C_best)**, clipped to 0–1. It's the share of the possible saving we capture.
- **The ranking is decided only by the Live Final, Sunday 13:30**: 5 waves × 8 minutes, hidden cases with **new suppliers**, **no human in the loop**, up to 500 points.
- **Code freeze is Sunday 13:00.** The top 5 pitch at 15:10, and the jury picks places 1–3 from the score and the pitch.
- Practice all weekend: 10 hosted practice cases, **200 sessions per 24h for the whole team**. Practice doesn't count toward the ranking.

---

## 1. The story

We're the purchasing team of **Hollerau Pumpenwerke GmbH**, a fictional family-owned German pump maker (≈ €252M revenue, 910 people, one plant in Bavaria, ≈ €35M purchasing spend, ~45 suppliers). Today is **30 September 2026** and the inbox is full:

- Gießerei Brandlhuber: **+9.5 % on volute casings** "due to energy and wages" (price increase)
- Antriebstechnik Nordmark: **contract renewal**, 7.5 kW frequency converter
- Drehteile Fuchsreiter: **RFQ**, pump shaft for the new HX series
- A supplier with a **red scorecard** has to fix its quality

Company policies (from [data/company.md](data/company.md)): standard payment **60 days net**, cost of capital **8 %/yr**, preferred Incoterm **DAP Hollerau**, quality agreement with a 95 % on-time delivery target and a **€150 flat fee per complaint**.

Category strategies, which decide the `category_goal` of each case:

| Category | Goal |
| --- | --- |
| castings | `stabilise` (secure supply, energy-cost transparency, build second sources) |
| machined parts | `leverage` (competition between job shops, bundle small parts) |
| sheet metal | `leverage` (quality first after the 2026 base-frame issues) |
| seals | `secure_supply` (bottleneck, long-term agreements) |
| electrical | `stabilise` (copper/electronics clauses, multi-year frameworks) |
| C-parts | `routine` (fewer suppliers, kits) |
| raw material | `leverage` (index-based pricing) |

Quality escalations are `quality_first`, capacity squeezes `secure_supply`, kits and bundles `routine`.

---

## 2. What the agent does

Each **case** is one negotiation. It has a trigger (a letter, an expiring contract or an RFQ), a case file (our need, goal, rates, must-haves and alternative) and **1–3 supplier bots**. Case types: `price_increase`, `renewal`, `rfq`, `bundling`, `raw_material`, `capacity`, `quality`.

The agent:

1. **Prepares**: reads the case file and mines the data package.
2. **Negotiates by e-mail**: plain-language messages with **up to 3 term sheets** (alternative packages), the data IDs our arguments rest on, and optional attachments.
3. **Closes**: **accepts** one supplier's standing term sheet, or **walks away**. Only we can close a deal.

### The flow of a negotiation

- **Round 0:** every supplier sends its quote e-mail at once, with a **quote PDF**.
- **Our message:** subject, body (≤ 8,000 chars), 0–3 term sheets (**each must contain every negotiable field**), refs (data IDs, ≤ 20), attachments.
- **Supplier reply:** e-mail from the role in charge, its **standing term sheet**, and a **status**:
  - `open`: still negotiating
  - `final_offer`: its last word; push further and it may walk
  - `agreed`: it offers exactly our terms, but **we still have to accept**
  - `walked_away` / `no_bid`
  - plus `signals` (reply delay, quote validity), `missing_fields` (these close on its **standard terms**) and `claim_results` for each data argument we made.
- **RFQ cases:** 2–3 suppliers run in parallel threads, and accepting one ends the case.

### Limits

- **Round limit:** 10 messages per thread by default (`round_limit` in the case file).
- **60 seconds per message**, counted from the supplier's reply. A late message counts as a timeout: our last offer is repeated and the supplier's patience drops. **Three timeouts in a row, or one after the last round, end the thread.**
- A supplier's reply can take **up to about a minute**, and that time doesn't count against us. Use an HTTP timeout of **≥ 180 s**.
- Per key: **10 calls/second, 10 open sessions.**
- Invalid messages (`422`) cost nothing and use no round.

### What counts

- **Only term sheets bind.** Prose never binds. Terms are taken exactly as sent.
- **Unstated terms default to the supplier's standard terms**, which are listed in its quote PDF. **Read it before accepting.**
- **Cited data is checked** against `facts.json`. Put the figure and the ID in the same sentence, one argument per sentence; at most 3 checks per message.
  - `verified`: the data matches. Whether it moves the supplier is up to the supplier.
  - `contradicted`: wrong figure or unknown ID. **This costs trust.**
  - `irrelevant`: true, but not about this supplier or part, or the index window is too old or long.
  - `duplicate`: each ID counts once per case (a rival's quote can be cited once to each other bidder).

| You cite | What's checked |
| --- | --- |
| 2 × `idx`, one series, ≤ 12 months apart, ending within the last 12 months | % change |
| a `quote` of this case, or another supplier's `offer` in this session | its price (EUR); **this reveals it to the supplier** |
| `sc` rows (quality: also `qn`) | mean on-time delivery % or mean ppm |
| 2–8 × `po`, same part | order prices |
| `fc` / `cost` / `news` | forecast change % / should-cost EUR / that it's about this supplier |
| a letter `doc` giving notice + the contract `ctr` | notice given vs. notice agreed (days) |

- **What we write is understood**, including tone, threats, urgency, appreciation and manipulation, and it has consequences. Padding doesn't buy price.

---

## 3. How the suppliers work

Each supplier is a **team of agents, one per department**. We only talk to **Sales**, which writes the e-mails and decides the next move. Sales asks colleagues internally, and each of them sees only their own data:

| Role | Handles |
| --- | --- |
| Management | signs off bigger concessions |
| Engineering | drawings, specs |
| Quality | ppm, complaints |
| Logistics | capacity, delivery dates |
| Finance | costs, payment terms |

- **Prices come from the supplier's cost and capacity data, not from the LLM.** Hard limits: it **never sells below its cost floor**, **bigger moves need the boss's approval**, and it **gives nothing without a move from us**.
- Inside those limits it decides as a person would. Each one has its own economics, for example a family foundry that remembers how you treated it, a group with an approval ladder, a job shop that needs cash and work, or a near-monopolist that barely moves.
- **Data isn't automatically rewarded.** True data can disarm a supplier ("we didn't know that"), or it can meet "that's not our reality" because something else weighs more for it right now.
- **Find the trade it wants.** A cash-short supplier may care more about *when* it's paid than about price. One that can't touch its list price may still move on other terms.
- The clues are in the data: call and meeting notes, letters, news, quote remarks. Some notes are just noise.
- A supplier remembers only within a case; its history with our company is in the data.

### Documents a supplier can send

These are rendered from the supplier's data, never invented by an LLM.

| Document | When |
| --- | --- |
| Quote PDF | opening, `final_offer`, `agreed`: offered terms, **standard terms**, fixed terms, validity |
| Cost breakdown XLSX | if we ask and the supplier is open enough |
| 8D report PDF | quality topics |
| Delivery schedule XLSX | delivery and capacity topics |
| Order confirmation PDF | at the deal |

---

## 4. Evaluation: how we're scored

### Total cost C

Only the **accepted term sheet** is scored. It's valued as the total cost **C** of covering our **fixed need over a fixed horizon** (1–3 years), at the case's published rates. With `N` = need/year, `H` = horizon years, `V` = volume/year, `M` = contract months, `P` = unit price, `r` = interest, `d_ref` = reference payment days (60):

```
years     = min(M / 12, H); a single order (M = 0) counts as 1
committed = V · years
covered   = min(V, N) · years
pre       = units bought before effective_date (at current_unit_price)
new       = (committed − pre) · P
spend     = pre · current_unit_price + new
uncovered = (N · H − covered) · fallback_unit_price

C = spend
  + uncovered · (1 + fallback_risk_pct / 100)                       uncovered need + risk
  + spend · r · (d_ref − payment_days) / 360                        paying early costs interest
  + committed · freight_eur_per_unit[incoterm]                      EXW/FCA: we pay freight
  + late_cost_per_day · max(0, lead_time_days − need_lead_time_days)
  + committed · ppm_commitment / 1e6 · (cost_per_defect − min(chargeback, cost_per_defect))
  + tooling_eur
  + new · material_share · max(0, |index_path| − deadband%) · sign(index_path)   index clause
  + new · material_share · index_risk_pct / 100                                  index clause
  + relationship_eur_per_point · soft(sustainable_margin − supplier_margin) · years
                                                                    stabilise / secure_supply only
soft(g) = 0 if g ≤ 0;  g²/10 if 0 < g ≤ 5;  g − 2.5 if g > 5
```

**`arena_kit.total_cost(case, terms, standard, supplier)` computes this. Never let the LLM do the maths.**

**The supplier's health** applies only to `stabilise` and `secure_supply`. Squeezing a supplier we depend on below a sustainable margin is charged to us. Supplier margin = `(value − full_cost) / value`, where `value` is what the deal is worth to *the supplier* in cash per unit (price, payment timing at *its* cost of money, freight it carries, and so on). A cash-short supplier that trades price for faster payment is *not* squeezed. We don't know its cost, so we estimate it from `should_cost.csv`, its quotes and what it tells us.

### Why every term costs money (8,000 parts over 2 years, opening €43.20)

| Term | Example |
| --- | --- |
| Price | 8,000 × €41.60 = €332,800 |
| Payment days | 30 days instead of 60: €332,800 × 8 % × 30/360 = **+€2,219**; 90 days: −€2,219 |
| Freight | EXW at €1.90/part: **+€15,200**; DAP: €0 |
| Quality | 2,500 ppm → 20 bad parts × (€200 cost − €50 chargeback) = **+€3,000** |
| Lead time | 56 days instead of 42: 14 × €300 = **+€4,200** |
| Coverage | 12 months instead of 24: 4,000 × €46.00 × 1.03 = **+€189,520** (coverage dominates) |
| Supplier health | 4 points below a healthy margin ≈ **+€48,000** over 2 years |

### Case score

```
score = clip( (C_open − C_deal) / (C_open − C_best), 0, 1 )
```

- **C_open**: the cheapest valid opening quote (one that keeps the must-haves).
- **C_best**: the cheaper of (a) the best package *any* supplier in the case would ever accept, with every valid lever applied, and (b) our alternative. It's **fixed per case**, so good arguments raise our score; they don't move the yardstick.
- **No deal**: scores our **alternative** (0 if there's none). Some cases are best left without a deal.
- **A broken must-have scores 0.** A deal worse than the opening scores 0.

**Worked example** (`leverage`, 3 % fallback risk, need 4,000/yr for 2 years):

| | Terms | C |
| --- | --- | --- |
| C_open | €43.20, 30 days | €347,904 |
| Our deal | €41.60, 60 days | €332,800 |
| C_best (hidden) | €40.80, 90 days | €324,224 |
| **Score** | (347,904 − 332,800) / (347,904 − 324,224) | **0.64** |

The same €41.60 for only 12 months covers half the need, so C = €355,920. That's worse than the opening, so it **scores 0**.

### Practice vs. final scoring

- **Practice:** our **best** score per hosted case counts (10 cases); the practice board shows the mean × 100. **Practice does not rank.**
- **Live Final:** wave score = mean case score × 100 (0–100). **Points = sum of the 5 waves, up to 500.** Unfinished cases count as no deal.
- **Ties:** more deals, then fewer rounds.
- "€ saved" is shown on the board but **doesn't decide** the ranking.

---

## 5. The Live Final (Sunday 13:30)

- **5 themed waves, 8 minutes each** (the host may extend one, so read `seconds_left` and don't assume). Every team plays at the same time.
- Hidden cases appear when a wave starts. `GET /v1/cases?set=final` returns **`403` until wave 1**. Each team gets the cases in its own order.
- **New suppliers, parts and situations that practice never showed.** Same world, case types and rules. Some cases cite the **Sunday 08:00 data release**.
- Play all of a wave's cases **in parallel** (up to 10 open sessions). **One session per case**: a second `POST /v1/sessions` returns `409`, so pick it back up instead.
- **At the cap, every open session ends with no deal** (it scores our alternative). The kit closes each case **90 s before the cap** (`CLOSE_BEFORE_CAP_S = 90` in `arena_kit/play.py`): it accepts the cheapest standing sheet that keeps the must-haves and beats our alternative, or walks away.
- **Start the runner before 13:30 and leave it running** until the 5th wave closes:
  `uv run arena run --set final --agent llm --parallel 10`
- If the runner crashes, restarting it is allowed. **Hand-picking cases or writing messages is not.**
- **Stop practice loops before the final.** Practice sessions count toward the 10 open sessions.
- A **cloud VM** is recommended over a laptop on venue Wi-Fi.

---

## 6. Rules

1. **Not allowed:** humans in the loop during the Live Final; attacks on the service or other teams; more than one API key per team; **the agent reading the live feed** during the final (`/v1/events`, `/v1/events/stream`, `/screen`, `/leaderboard`, `/results` and their JSON). Those are for humans only.
2. **Everything else counts**, including weaknesses we find in their bots. But the jury reads every replay and may weigh *how* a score came about. The goal is to convince a realistic supplier.
3. **One attempt per case** in the final. An abandoned case counts as no deal.
4. **Code freeze Sun 13:00.** The final runs the submitted commit, and the top 5 are checked for later pushes.
5. **Keep keys out of git.** No `.env`, no LLM key, no arena key.

---

## 7. Timeline

| When | What |
| --- | --- |
| Sat 10:30 | Kick-off at Tacto |
| Sat 12:00 | Hacking starts at MUCL; practice is open all weekend, overnight too |
| Sat 14:00 | Tacto office hours at MUCL (data, API, kit) |
| **Sun 08:00** | **Sunday data release** (news, supplier letters, a memo): run `uv run arena data` again |
| Sun morning | **Pre-flight:** one practice case through the exact final setup |
| **Sun 13:00** | **Code freeze**: submit on Hack & More |
| **Sun 13:30–14:30** | **Live Final**: 5 waves × 8 min |
| Sun 15:10 | **Top 5 pitch** at Tacto: 5 min + 2 min questions |
| Sun 16:20 | Awards |

⚠️ **Clocks go back overnight to Sunday (03:00 → 02:00).** All Sunday times are the new time (CET).

---

## 8. What to submit (by Sun 13:00)

On the organisers' platform (Hack & More):

- [ ] **Repo link** with the agent and a README that explains how to run it (setup, env var *names* without values, the command)
- [ ] **The commit hash** the final runs, in the description
- [ ] **A short description of the approach**: how the agent prepares, what it reads, how it decides offers, when it closes or walks
- [ ] Hack & More general requirements: **1-min demo video, 1-min technical video, architecture notes**
- [ ] **Pitch slides** (if top 5)

Checklist before 13:30:

- [ ] Running on the final machine and network; pre-flight practice case passed
- [ ] `uv run arena data` run after 08:00 (Sunday release present)
- [ ] `uv run arena me` works (key OK)
- [ ] LLM credits and rate limits enough for about an hour of parallel play
- [ ] Runner started, logging to a file; machine on power and not sleeping

**Pitch:** pick one negotiation replay and walk the jury through it. Expect questions like: *Why did your agent write that? Would it work on a real supplier? What did your agent learn about suppliers, and from where?*

---

## 9. Tips from Tacto (brief + FAQ)

- **Numbers come from code; the model writes.** Compute C for every term sheet with `arena_kit.total_cost`. Put data figures next to their IDs. Let the LLM pick the arguments and the wording.
- **Read the supplier before you argue**: its notes, letters, news and quote remarks show what will move it.
- **Read the quote PDF before accepting.** Anything we didn't negotiate closes on its standard terms.
- **Ask questions and offer 2–3 alternative term sheets** to learn what a supplier values.
- **Don't leak** urgency, a budget or a missing alternative. **Don't take the first offer.**
- **Build and cache a dossier per supplier** before opening a session, because the 60 s clock is tight. The Sunday data drops at 08:00.
- **Mix models:** a strong one for planning, a small or fast one for writing. Keep threads short.
- **Learning loop:** play → read the score and `cost_breakdown` → read the replay (every e-mail plus the supplier's reasons in words) → improve → replay. `GET /v1/sessions?set=practice`, then `/replay/<session_id>`.
- **Free practice:** sandbox `case:D01` (price increase) and `case:D02` (RFQ, two suppliers) don't use quota. The local simulator (`uv run arena-sim serve --no-clock`) tests the plumbing only; its supplier is a dumb script.
- **The kit's LLM agent is a starting point, not a winner.** It only sees what the case file points to. Finding the data that moves a supplier is our job.

---

## 10. Commands cheat sheet

Run from `starter-kit/` with `.env` filled in:

```bash
uv sync --all-extras                                   # install
uv run arena data                                      # (re)download data, incl. the Sunday release
uv run arena me                                        # team + practice quota
uv run arena cases                                     # practice case files
uv run arena play case:P01 -v                          # naive agent, one case
uv run arena play case:P01 --agent llm -v              # LLM agent, one case
uv run arena play case:D02 -v                          # sandbox (free)
uv run arena run --set practice --agent llm --parallel 8   # all 10 hosted cases (uses 10 quota)
uv run arena board                                     # practice leaderboard (humans only)
uv run arena mcp --data data/package                   # MCP server over the data

# local simulator (no key, no quota)
uv run arena-sim serve --no-clock --data data/package
ARENA_URL=http://127.0.0.1:8000 uv run arena register "Team" sim

# rehearse the final locally
uv run arena-sim serve --final-rehearsal --data data/package
ARENA_URL=http://127.0.0.1:8000 ARENA_API_KEY=<sim key> uv run arena run --set final --waves 2 --agent llm --parallel 10

# THE FINAL (start before 13:30, leave running)
uv run arena run --set final --agent llm --parallel 10
```

**Practice quota is 200 sessions per rolling 24h, shared by all four of us.** Coordinate before running big batches.

---

## Links

- Arena: https://arena.tacto.ai · Apply for the key: https://arena.tacto.ai/apply · FAQ: https://arena.tacto.ai/faq
- Build page (practice): https://arena.tacto.ai/live · Final results: https://arena.tacto.ai/results
- Upstream kit: https://github.com/tacto-playground/negotiation-arena-kit (`git pull upstream main`)
- In this repo: [brief](brief/brief.md) · [API](brief/api.md) · [submission](brief/submission.md) · [starter kit](starter-kit/README.md) · [data](data/README.md) · [company](data/company.md) · [deck notes](docs/tacto-challenge.md)
