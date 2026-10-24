# MM Hackathon: Tacto Negotiation Arena

Our entry for the [Industrial Agents Hackathon](https://industrialagents.dev) (Munich, Oct 24–25 2026), **Tacto track**.

We're building an **AI buyer agent** for Hollerau Pumpenwerke, a fictional German pump maker. It reads the company's procurement data, negotiates by e-mail with Tacto's supplier bots, and closes the best total deal or walks away. A Live Final on hidden cases ranks every team.

> 📘 **New here? Read [CHALLENGE.md](CHALLENGE.md) first, then [STRATEGY.md](STRATEGY.md) (how we win and who does what).** It covers the task, how we're scored, the rules, the Live Final, the submission and the deadlines.

Tacto's materials live alongside our code: [challenge deck notes](docs/tacto-challenge.md) · [brief](brief/brief.md) · [API docs](brief/api.md) · [submission](brief/submission.md) · [starter kit](starter-kit/README.md) · [data](data/README.md) · [FAQ](https://arena.tacto.ai/faq) · [build page](https://arena.tacto.ai/live)

## Team

- Mert Ayvazoglu ([@mert-ayv](https://github.com/mert-ayv))
- Ege Dogu Kaya ([@edkaya](https://github.com/edkaya))
- Annika Siefke ([@annikasiefke](https://github.com/annikasiefke))
- Emre Öztas ([@emreoztas64](https://github.com/emreoztas64))

## Setup

You need Python 3.12, [uv](https://docs.astral.sh/uv/) and git.

**1. Clone and install**

```bash
git clone https://github.com/mert-ayv/MM-Hackathon.git
cd MM-Hackathon/starter-kit
cp .env.example .env
uv sync --all-extras
uv run arena data               # unpacks the data package into starter-kit/data/package
```

**2. Put the keys in `starter-kit/.env`.** Our arena team is **csee-base** and we have **one arena key for the whole team**: get it from the teammate who registered, and don't apply for a second one. The file is git-ignored, so **never commit it** and never paste keys into code, issues or chat logs.

```bash
# starter-kit/.env
ARENA_URL=https://arena.tacto.ai
ARENA_API_KEY=<our team key>
ARENA_DATA=data/package

LLM_PROVIDER=anthropic
LLM_MODEL=claude-opus-5-5
LLM_EFFORT=low
ANTHROPIC_API_KEY=<your Anthropic key>
```

**3. Check it works** (run from `starter-kit/`)

```bash
uv run arena me                         # our team + practice quota left: the key works
uv run arena play case:P01 -v           # naive agent plays one practice case → score + replay link
uv run arena play case:P01 --agent llm -v   # the LLM agent (needs ANTHROPIC_API_KEY)
```

`arena play` prints the deal, `c_deal` vs `c_open` / `c_best`, the score and a **replay link**. Open the link: it shows every e-mail and the supplier's reasons.

No key yet? The local simulator needs none:

```bash
uv run arena-sim serve --no-clock --data data/package          # terminal 1
ARENA_URL=http://127.0.0.1:8000 uv run arena register "Me" sim  # terminal 2 → prints a sim key
ARENA_URL=http://127.0.0.1:8000 ARENA_API_KEY=<sim key> uv run arena play case:S01 -v
```

**Quota:** 200 practice sessions per team per rolling 24h, **shared by all four of us**. Use the local simulator (`uv run arena-sim serve --no-clock`) and the free sandbox (`case:D01`, `case:D02`) for plumbing.

Pulling Tacto's kit updates: `git pull upstream main` (remote `upstream` = tacto-playground/negotiation-arena-kit).

## Our agent (`starter-kit/csee/`)

Run from `starter-kit/` with `.env` filled in:

```bash
uv run python -m csee play case:P01 -v        # our agent, one practice case → score + replay link
uv run python -m csee run                     # all 10 hosted practice cases in parallel (uses 10 quota!)
uv run python -m csee run --set sandbox       # free: D01, D02
uv run python -m csee eval                    # pull every finished session into runs/, table vs house agent
uv run python -m csee show <session_id>       # one negotiation move by move, with the supplier's reasons
uv run python -m csee --agent router -v final 2>&1 | tee -a logs/final.log   # THE LIVE FINAL - see docs/RUNBOOK.md
```

Add `--no-llm` to use template e-mails. Without an LLM key it uses templates anyway. Add `--agent <name>` (before the command) to play one of the team agents in `csee/agents/` instead of `base`, e.g. `uv run python -m csee --agent ege sim`.

| Module | What |
| --- | --- |
| `levers.py` | the best value of every term for us, EUR value of each lever, price for a target cost |
| `intel.py` | supplier cost-floor estimate, verified data arguments (indices, should-cost, notice periods, scorecards, rival offers), cost-breakdown parser |
| `agent.py` | per-thread concessions and term sheets, trade sheets, the accept/walk decision (`base`, the champion) |
| `agents/` | one agent per teammate (`ege.py`, `mert.py`, `annika.py`, `emre.py`), each a `CseeAgent` subclass; registry in `agents/__init__.py`; `agents/router.py` plays each case type with the agent that wins it (`--agent router`, for the final) |
| `writer.py` | e-mail wording: templates, or a model (claim sentences kept verbatim) |
| `runner.py` | all supplier threads of a case **in parallel** (the 60 s clock is per thread), practice runs, Live Final waves |
| `evaluate.py` | fetch results + traces + back office, report vs house agent |
| [`docs/PITCH_DEMO_IDEAS.md`](docs/PITCH_DEMO_IDEAS.md) | pitch, 1-min videos, ElevenLabs audio replay, negotiation visualiser ideas |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | **how the agent works + changelog of architecture versions with evidence** |
| `profiles/` | one JSON profile per supplier: situation, pressures, what it values, arguments to use/avoid |

The raw-material challenger is `mert-plan-raw/v16a` (the router selects `mert-plan-meso-raw-dc/v16a`).
It keeps a shared index clause once both parties offer it, applies its planned concession to the final
outgoing package, and prices a longer indexed contract as a separate trade within its concession
budget. Completed P08/P18 replay states and offline regressions validate construction; a hosted score
improvement has not yet been measured. Compare locally without model calls or arena sessions:

```bash
uv run python -m csee --no-llm sim --agents mert-skiphedge mert-plan-raw \
  --variants v16a --cases case:P08 case:P18 --seeds 3
```

### Ege's strategy layer

`--agent ege` uses a tool-calling strategist for price increases, RFQs and bundles when an Anthropic
model is configured. It reads the complete conversation, retrieves documents and case-local evidence,
keeps evidence-backed supplier hypotheses, and chooses offers, concessions, questions and stopping.
Base's next move is optional advice and a fallback if the model fails or exceeds its time budget.

Each move uses draft, deterministic cost review, then model confirmation. Material untested term
values are tracked as test now, defer, or decline. A deferred probe is due at the next buyer decision
and must appear in a package or be explicitly cancelled with a reason. Its deadline cannot restart.
Pending probes can be cancelled when accepting a final offer; they never force another counter.
State is scoped to the current case and supplier.

For RFQs, `compare_rfq_bids` ranks complete live bids, separates alternatives needing confirmation,
and calculates a price to match a rival on total cost at the proposed payment/delivery terms. Rival
claims use only valid, lower-price and lower-cost standing offers. A strategist's RFQ accept/stop
decision ends its own bargaining thread; the coordinator compares current valid first sheets before
awarding. Another bidder's work can continue until the runner closes for completion or time pressure.

The deterministic tools calculate package costs, show the breakdown and supplier-cost sensitivity,
construct factual argument sentences, and check allowed fields, must-haves and acceptable standing
offers. Relationship costs remain estimates; the cost tool does not predict acceptance or the true
arena score. Conditional trade packages may cost different amounts, and offer validity is not treated
as a refusal to negotiate. The code renders every submitted sheet and checked argument in the email.

Run the actual model against local suppliers with:

```bash
cd starter-kit
uv run python -m csee --agent ege sim --llm --cases case:P01 case:P02 --seeds 1
# RFQ strategist against local suppliers, with the RFQ champion's baseline parameter preset:
uv run python -m csee --agent ege sim --llm --variants v7a --cases case:P05 case:P06 --seeds 1
```

This uses **LLM credits, no arena sessions**. Without `sim --llm`, simulation uses template/base
behaviour and cannot measure the strategist. The fully offline checks use scripted HTTP responses
through the real SDK tool runner: `uv run pytest -q tests/test_ege_agent.py tests/test_ege_strategy.py`.
They cover unseen suppliers, evidence retrieval, invalid-move correction, strategy freedom, contract
validation and timeouts; they do not establish a score improvement on hosted or hidden cases.

## Dashboard

A local web app for debugging runs and for the pitch replay ([dashboard/README.md](dashboard/README.md)):

```bash
uv run --project starter-kit python dashboard/import_sessions.py --fetch   # our real arena games → runs/ (GET only, no quota)
./dashboard/run.sh --open                                                  # http://127.0.0.1:8787
```

It compares runs (base vs variants per author), shows each case round by round (e-mails, term
sheets with C, claim results, the supplier's reasons) and replays a negotiation for the pitch. It
needs Node ≥ 18 and uv the first time, and works offline after that.

## How scoring works (short version)

- Each deal is priced as a **total cost C** in € (price, uncovered need, payment terms, freight, lead time, quality, tooling, index clause and, for `stabilise`/`secure_supply`, the supplier's margin health). The formula is in [api.md](brief/api.md#cost-and-score); compute it with `arena_kit.total_cost`.
- **Case score = (C_open − C_deal) / (C_open − C_best)**, clipped to 0–1. No deal scores your alternative; a broken must-have scores 0.
- **Live Final:** 5 themed waves × 8 minutes, cases played in parallel. Points = sum of the wave scores (max 500). The top 5 pitch.

## Key times

| When | What |
| --- | --- |
| Sat 14:00 | Tacto office hours at MUCL |
| **Sun 08:00** | Sunday data release: run `uv run arena data` again |
| Sun morning | Pre-flight: one practice case through the final setup |
| **Sun 13:00** | **Code freeze**: submit repo + commit hash on Hack & More |
| **Sun 13:30** | **Live Final**: runner must already be running; no human in the loop |
| Sun 15:10 | Top 5 pitch at Tacto: 5 min + 2 min Q&A |

Clocks go back overnight to Sunday (03:00 → 02:00); Sunday times are the new time.

## Submission checklist (Sun 13:00)

- [ ] Repo with the agent + this README (how to run it)
- [ ] Commit hash the final runs
- [ ] Short description of our approach
- [ ] Hack & More: 1-min demo video, 1-min technical video, architecture notes
- [ ] Pitch slides (if top 5)
- [ ] Final runner started before 13:30 on a machine that won't sleep, logging to a file

## Our approach

**In one line:** the language model reads and writes like a buyer; deterministic code decides every number. Guardrails protect the deal, and every design choice was measured before it shipped.

### Architecture

| Layer | What it does | Where |
|---|---|---|
| Commercial engine | Prices every package with the arena's exact total-cost model, including the relationship charge for stabilise/secure-supply goals (we reproduce the arena's deal cost to the euro on all 40 of our deals). The case's alternative is our walk-away line. | `csee/levers.py`, `arena_kit/cost.py` |
| Negotiation policy | Opening anchor, concession pacing, which 1–3 term sheets to send, when to accept. Uses an online move planner (below) and a router that picks the proven policy per case type. | `csee/agent.py`, `csee/agents/mert.py`, `csee/agents/router.py` |
| Supplier intelligence | A dossier for all 46 suppliers. It covers hedges from letters and call notes, cost drivers and index exposure, cash pressure (including how late we pay them), levers they value, approval ladder, capacity and quality. Checked data arguments are drawn from the data package. | `csee/dossier/`, `csee/intel.py` |
| Writer | Claude Opus 5.5 writes the e-mail around fixed numbers and verbatim, checkable claim sentences. A template is the fallback if the model is slow. | `csee/writer.py` |
| Guardrails | The agent: <br>• accepts only the supplier's standing (first) sheet; <br>• never accepts above the alternative or against a must-have; <br>• never pushes after a final offer; <br>• completes price-only offers before accepting. <br>The runner adds time-aware closing before the wave cap, retries and resume. | `csee/agent.py`, `csee/runner.py` |

### What we learned about the opponent, and how we exploit it

We fitted a model of the supplier bots from 260 of our own sessions. Each round's back-office note exposes the bot's decision, which made this possible. The model predicts the next supplier price within about 0.6 %. The suppliers behave like a classic **tit-for-tat negotiator** (Faratin, Sierra & Jennings 1998):

- They mirror our concession step, up to a cap that shrinks each round.
- They hold when we do not move.
- They send a final offer after a fixed number of replies, or earlier when our ask stays far away.
- They always accept their own final sheet proposed back, and agree to any of our sheets that is worth at least their current ask.
- Pushing after a final offer has negative expected value: in our logs 2 of 17 such pushes ended in a walk-away.

From that we built:

- **An online move planner.** It estimates each supplier's cap and decay from its first replies. It then concedes exactly what the supplier will mirror and keeps the gap inside the budget that avoids an early final offer. This is the best response to a tit-for-tat opponent ([de Jonge 2022](https://www.iiia.csic.es/~davedejonge/homepage/files/articles/2022%20-%20de%20Jonge%20-%20MiCRO.pdf)). On 531 perturbed supplier models it scores 0.658 against 0.615 for our rule policy, with 3 walk-aways instead of 36.
- **Lever answers.** When a supplier names a lever (for example a copper index clause or faster payment), we answer with a sheet priced by our cost engine. On P02 the supplier agreed to a copper clause with a 5 % deadband at once: 0.633 → 0.733.
- **Payment-term menus (MESOs).** We offer the shortest and longest payment term at equal cost to us, and the supplier reveals its money rate by the one it picks. On P01 that moved us from 30-day terms to 14-day terms: 0.926 → 0.988.
- **Checked arguments that move the engine.** We cite index falls on cost drivers the supplier names and has not hedged, should-cost, rival quotes and forecasts. We drop argument types the bots ignore ("holds, but does not change our calculation"). Skipping a hedged index on P08 took us from 0.711 to 0.754.

### How we decided (no change shipped on intuition)

Every practice session is logged with author, agent, variant, commit and score (`experiments/`, `runs/`). A change moved up this ladder:

1. The free sandbox.
2. The fitted engine model, which can also be perturbed for robustness.
3. A real practice session, only when the model predicted a gain.

The final router is the per-case-type winner of a 20-session A/B dress rehearsal. Full experiment log: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Research notes: [docs/notes/negotiation-research.md](docs/notes/negotiation-research.md).

### Results (practice board, Sat evening)

Mean 0.778 over the 10 practice suppliers, against 0.697 for Tacto's house agent. We beat the house agent on 8 of 10 cases, often by a wide margin: P05 0.81 vs 0.56, P11 0.71 vs 0.31, P18 0.55 vs 0.39.

### Built for the Live Final

- Only known suppliers appear, and every one is in the dossier. The Sunday data release is merged at runtime.
- Parallel threads with time-aware pacing: every practice case finished inside the 390 s safety close.
- A must-have the agent cannot see in the quote no longer blocks every offer.
- Failed cases are retried while the wave runs.
- Local wave rehearsals ran with zero errors.
