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
uv run python -m csee final                   # THE LIVE FINAL (start before 13:30, leave running)
```

Add `--no-llm` to use template e-mails. Without an LLM key it uses templates anyway. Add `--agent <name>` (before the command) to play one of the team agents in `csee/agents/` instead of `base`, e.g. `uv run python -m csee --agent ege sim`.

| Module | What |
| --- | --- |
| `levers.py` | the best value of every term for us, EUR value of each lever, price for a target cost |
| `intel.py` | supplier cost-floor estimate, verified data arguments (indices, should-cost, notice periods, scorecards, rival offers), cost-breakdown parser |
| `agent.py` | per-thread concessions and term sheets, trade sheets, the accept/walk decision (`base`, the champion) |
| `agents/` | one agent per teammate (`ege.py`, `mert.py`, `annika.py`, `emre.py`), each a `CseeAgent` subclass; registry in `agents/__init__.py` |
| `writer.py` | e-mail wording: templates, or a model (claim sentences kept verbatim) |
| `runner.py` | all supplier threads of a case **in parallel** (the 60 s clock is per thread), practice runs, Live Final waves |
| `evaluate.py` | fetch results + traces + back office, report vs house agent |
| [`docs/PITCH_DEMO_IDEAS.md`](docs/PITCH_DEMO_IDEAS.md) | pitch, 1-min videos, ElevenLabs audio replay, negotiation visualiser ideas |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | **how the agent works + changelog of architecture versions with evidence** |
| `profiles/` | one JSON profile per supplier: situation, pressures, what it values, arguments to use/avoid |

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

_TBD._
