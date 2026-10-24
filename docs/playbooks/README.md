# Negotiation playbooks per case type

Evidence-based playbooks for the buyer agent. Each one covers what the cost function C rewards in the type
(a worked example with real numbers), what Tacto's supplier bots did in our real games, why `base` scored
what it did, the playbook (opening, trades, claims, closing, pitfalls), decision rules to code, and what
generalises to the hidden final cases.

| Type | Category goal | Playbook | Practice cases | Base / house agent |
|---|---|---|---|---|
| `capacity` | `secure_supply` | [capacity.md](capacity.md) | P09 (local), **P10** (hosted) | P10: 0.57 / 0.69 |
| `quality` | `quality_first` | [quality.md](quality.md) | **P11** (hosted), P12 (local) | P11: 0.23 (v7 0.06) / 0.31 |

The lever arithmetic is reproducible with `experiments/playbooks/lever_values.py`:
`uv run --directory starter-kit python ../experiments/playbooks/lever_values.py`.

One-line summaries:
- **capacity:** cover the full need for the full horizon in every sheet, sell lead-time days (a one-off
  € per day for us, priced per unit by the supplier) and long contracts (free beyond the horizon) for price,
  price every alternative sheet, and never walk without an alternative.
- **quality:** take the lowest ppm, which the bot gives away. Never buy a chargeback, which the bot prices at
  its real defect rate (5-20× its value to us). Freeze the quality terms after round 1 and negotiate price
  only; answer the cash plea.
