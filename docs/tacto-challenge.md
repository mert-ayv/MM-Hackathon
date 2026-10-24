# Tacto Challenge: kick-off presentation (notes)

Transcribed from the "Tacto Challenge Presentation" deck (Adrian Hupka, Head of Builders, Tacto), Sat 24 Oct 2026.
The full rules are in [../brief/brief.md](../brief/brief.md) and [../brief/api.md](../brief/api.md); FAQ at https://arena.tacto.ai/faq.

## About Tacto

Munich software company building AI for industrial procurement ("Tacto executes the perfect buy"). 350 industrial manufacturers as customers. Product areas: Supplier, Sourcing, Spend & Cost, and Compliance Intelligence. In their product, agents already do parts of the buyer's job.

**Why this challenge:** negotiating with suppliers is one of the hardest parts of procurement. They want to see how far a *fully autonomous* buyer can go.

## The task

Our agent is the buyer at **Hollerau Pumpenwerke**, a fictional pump maker. Each case starts with one supplier e-mail, for example:

- Gießerei Brandlhuber: price adjustment from 01 Nov, **+9.5 % on volute casings**
- Antriebstechnik Nordmark: **contract renewal**, 7.5 kW frequency converter
- Drehteile Fuchsreiter: **RFQ**, pump shaft for the new HX series

The agent reads the company data, negotiates, then **signs or walks away**. No human input during a case.

## The data

Each supplier has its own situation, and it's findable in the data:

- 3 years of purchasing history · ~33,000 rows in 24 tables · 33 real market price indices · 447 suppliers
- Example signals: a meeting note ("He works from his own spreadsheet, last updated two years ago"), news ("Drehteile Fuchsreiter GmbH looks for new customers"), a red Q3 scorecard (Odlewnia Kalwisz: on-time delivery 63.5 %, 2,376 ppm)
- **Suppliers check our arguments against the same data. Arguments that hold up move the price.**

## How a supplier works

Each supplier is a **team of agents, one per department**. We only talk to **Sales**, which writes the e-mails and decides the next move. Sales asks its colleagues internally (each sees only its own data):

| Role | Handles |
| --- | --- |
| Management | signs off bigger concessions |
| Engineering | drawings, specs |
| Quality | ppm, complaints |
| Logistics | capacity, delivery dates |
| Finance | costs, payment terms |

We send an e-mail plus term sheets and get back a reply plus a quote PDF. **Prices come from the supplier's cost and capacity data, not from the language model.** Every step is in the replay.

## The score

Each offer converts to one **total cost in € over the contract**: price, payment days, freight, quality, lead time, how much of our need it covers, and the supplier's health. Score = the share of the possible saving our deal captures.

Example: opening €347,904 → our deal €332,800 → best possible €324,224 → **score 0.64**.

### Why every term costs money (8,000 parts over 2 years, opening €43.20)

| Term | Rule | Example |
| --- | --- | --- |
| Price | per part, for every part committed | 8,000 × €41.60 = €332,800 |
| Payment days | paying earlier than our standard 60 days costs 8 %/yr interest | 30 days: +€2,219 · 90 days: −€2,219 |
| Freight | Incoterm decides who pays the truck (EXW: we collect and pay; DAP: they deliver) | EXW at €1.90: +€15,200 · DAP: €0 |
| Quality | bad parts cost sorting/rework/line stops; the chargeback pays part back | 2,500 ppm → 20 bad × (€200 − €50) = +€3,000 |
| Lead time | late parts stop our line | 56 days instead of 42: 14 × €300 = +€4,200 |
| Coverage | uncovered need is bought later at the fallback price + risk surcharge | 12 months instead of 24: 4,000 × €46 × 1.03 = +€189,520 |
| Supplier health | *strategic and bottleneck parts only*: squeezing a supplier below a healthy margin risks supply | 4 points below ≈ +€48,000 over 2 years |

Also counted: tooling (one-off €) and index clauses (expected index move + risk). All rates are in each case file and follow its category goal (for example, `quality_first` makes bad parts expensive). **A broken must-have scores 0.** The kit's `total_cost()` adds it all up.

## Getting started

1. Apply at https://arena.tacto.ai/apply
2. Show the match code at the Tacto desk; they approve
3. Copy the key, then: `uv sync --all-extras` · `uv run arena me` · `uv run arena play case:P01` · `uv run arena board`

Practice all weekend: **10 practice cases, 200 sessions/day**, a replay after every case. Office hours at MUCL from 14:00.

## Sunday

| Time | What |
| --- | --- |
| 08:00 | New market data |
| 13:00 | Code freeze |
| 13:30 | Live Final: **5 waves × 8 minutes**, every team at once, 0–100 points per wave → **up to 500** |
| 15:10 | Top 5 pitch |

**The Live Final uses new suppliers that are not in practice.** Start the agent before 13:30 and leave it running.

## Pitches and prizes

1. Top 5 of the Live Final pitch at 15:10 at the Tacto office: 5 min + 2 min questions
2. The jury sets places 1–3 from the final score and the pitch
3. Prizes: robots, caps and a small extra

**The jury reads our replays, so we need to be able to explain every decision the agent made.**
