# MM Hackathon: Tacto Negotiation Arena

Our entry for the [Industrial Agents Hackathon](https://industrialagents.dev) (Munich, Oct 24–25 2026), **Tacto track**.

We're building an **AI buyer agent** for Hollerau Pumpenwerke, a fictional German pump maker. It reads the company's procurement data, negotiates by e-mail with Tacto's supplier bots, and closes the best total deal or walks away. A Live Final on hidden cases ranks every team.

Tacto's materials live alongside our code: [brief](brief/brief.md) · [API docs](brief/api.md) · [submission](brief/submission.md) · [starter kit](starter-kit/README.md) · [data](data/README.md) · [FAQ](https://arena.tacto.ai/faq) · [build page](https://arena.tacto.ai/live)

## Team

- Mert Ayvazoglu ([@mert-ayv](https://github.com/mert-ayv))
- Ege Dogu Kaya ([@edkaya](https://github.com/edkaya))
- Annika Siefke ([@annikasiefke](https://github.com/annikasiefke))
- Emre Öztas ([@emreoztas64](https://github.com/emreoztas64))

## Setup

You need Python 3.12, [uv](https://docs.astral.sh/uv/) and git.

```bash
git clone https://github.com/mert-ayv/MM-Hackathon.git
cd MM-Hackathon/starter-kit
cp .env.example .env            # fill in ARENA_API_KEY and ANTHROPIC_API_KEY. Never commit .env
uv sync --all-extras
uv run arena data               # unpacks the data package into starter-kit/data/package
uv run arena me                 # checks the key: team and practice quota
uv run arena play case:P01 -v   # naive agent, one practice case
```

Environment variables (in `starter-kit/.env`): `ARENA_URL`, `ARENA_API_KEY`, `ARENA_DATA`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_EFFORT`, `ANTHROPIC_API_KEY`.

**Quota:** 200 practice sessions per team per rolling 24h, **shared by all four of us**. Use the local simulator (`uv run arena-sim serve --no-clock`) and the free sandbox (`case:D01`, `case:D02`) for plumbing.

Pulling Tacto's kit updates: `git pull upstream main` (remote `upstream` = tacto-playground/negotiation-arena-kit).

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
