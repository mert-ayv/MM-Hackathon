# Negotiation Desk: the team dashboard

A local web app over our run logs (`runs/<run_id>/`, format in [`docs/run-log.md`](../docs/run-log.md)).
It's for debugging all weekend and for the pitch replay on Sunday. It only **reads** files, and the
runner never depends on it.

## Run it (one command)

```bash
./dashboard/run.sh            # http://127.0.0.1:8787
./dashboard/run.sh --open     # ...and open the browser
```

`run.sh` builds the frontend if `web/dist` is missing or older than the sources, then starts one
FastAPI process that serves both the API and the built app on one port. It needs no CDN at runtime:
fonts and code are bundled.

Options (passed through to the server):

| Flag | What |
|---|---|
| *(none)* | Reads `<repo>/runs/`. While that folder holds no runs, it falls back to the fixtures. |
| `--fixtures` | Shows `runs/` **and** `dashboard/fixtures/runs/` (demo data) |
| `--fixtures-only` | Shows only the fixtures (pitch rehearsal) |
| `--no-fallback` | Never shows the fixtures |
| `--runs PATH` | Reads another run folder (env `DASHBOARD_RUNS`) |
| `--port N` / `--host H` | Default `127.0.0.1:8787` (env `DASHBOARD_PORT`) |
| `--build` | Forces a frontend rebuild first (`run.sh` only) |

**First time / pitch laptop (do this online, once):** you need Node ≥ 18, npm and [uv](https://docs.astral.sh/uv/).
`./dashboard/run.sh --build` installs the npm packages (if missing), builds the app and syncs the server's uv
env. After that everything works offline.

The server is its own small uv project (`dashboard/server`: `fastapi` + `uvicorn` only). It
doesn't import the agent or the kit, so it can't break the runner and the runner can't break it.

## Views

- **Runs** (`#/`): one card per run (agent, version, set, mean score ×100, € saved, live dot) and a
  **cases × runs** table with score, deal / no deal, rounds, € saved and end_reason. ▼ marks a
  regression against the baseline (default: the run before the newest one; click "Use as
  baseline" to change it). Click a cell to open the case.
- **Case** (`#/case/<run>/<case>`): the briefing, the result strip (score, C open / deal / best /
  alt, € saved), a **gauge** placing the deal or best standing offer between C open and C best,
  and **C over rounds** (each supplier's standing offer, our cheapest ask, and the C open / best /
  alt lines). Below that you get one tab per supplier thread, with the dossier, then per round the
  strategist's reason, our e-mail with its term sheets (C each), claims with their verified /
  contradicted / irrelevant / duplicate badges, and the supplier's reply (status, standing offer
  with ΔC). On the right, **C by term** for any sheet you click (Δ vs the opening quote as a
  waterfall, or the absolute breakdown), plus the round's **specialists** (€ for us vs € for the
  supplier, proposal, claim) and the **plan** candidates with the chosen one marked.
- **Replay** (`#/replay/<run>/<case>`): plays a finished case back as if live. Pacing comes from
  the `ts` gaps at 1× / 4× / 16× or **Demo** (gaps capped at about 2 s, the agent's internal steps
  skimmed). E-mails type in, and the gauge and chart move with each reply. Keys: `Space` play/pause,
  `←`/`→` step, `Home`/`End`, `1`–`4` speed, `f` fullscreen. `?at=12` or `?at=end` jumps to an event.

Press **`P`** (or "Presentation" top right) for projector-sized type. New runs and new events show
up on their own: the app polls `/api/version` every 2.5 s, and an open case follows a live run.
Missing `dossier` / `specialists` / `plan` events (baseline agents) just leave those panels
empty, and unknown event types are ignored.

## Voice copilot ("Ask the negotiator", ElevenLabs)

An internal voice assistant for the procurement manager, docked bottom-right on every view (`V` opens it). It opens
with a ~20 s spoken debrief of the open negotiation (text built by code from the run log), then answers questions
like *"why did we accept in round 5?"* or *"where did we leave money?"*. Every figure comes from a client tool over
the run log (`src/lib/voice.ts`): `get_case_summary`, `get_round`, `get_cost_breakdown`, `get_supplier`,
`get_portfolio`, `list_playbook`, `show` (moves the screen to a round) and `propose_change`, which queues a diff card
in Agent Studio for one-click accept / reject. It never changes the agent by itself.

Setup (once, online):

```bash
echo 'ELEVENLABS_API_KEY=...' >> starter-kit/.env       # never commit it
python3 dashboard/voice/provision.py                     # creates/updates the agent from dashboard/voice/agent.json
python3 dashboard/voice/provision.py check               # signed-URL round trip
python3 dashboard/voice/provision.py tts                 # voices the offline demo (web/public/voice/*.mp3)
```

The agent id lands in `dashboard/voice/.agent_id` (git-ignored; or set `ELEVENLABS_AGENT_ID`). The server hands the
browser a signed URL (`/api/voice/session`), so the key never leaves it. Without a key, or when the venue Wi-Fi
fails, the dock plays the **demo**: a scripted conversation over the showcase P01 (`web/public/voice/demo.json`),
with the pre-generated ElevenLabs clips (browser speech if they're missing). Its tool calls are real: it scrolls the
negotiation and drops the suggestion into Agent Studio.

## The team's real games

```bash
# from the repo root
uv run --project starter-kit python dashboard/import_sessions.py --fetch   # + read-only GETs on the arena
uv run --project starter-kit python dashboard/import_sessions.py           # offline: saved sessions + cache
```

The importer turns finished arena sessions into runs under `runs/<run_id>/` (git-ignored), tagged
`"source": "imported"`. It reads `starter-kit/runs/sessions/*.json` (from `csee eval`) and, with
`--fetch`, the arena itself, using **GETs only** (`/sessions`, `/sessions/{sid}`, `/threads/…`,
`/backoffice`, the quote PDFs). That costs no quota and never moves. Everything fetched is cached
in `runs/.arena-cache/`.

- **Events per game:** `case_opened`, `message_sent` (with the claims the arena read), `reply`
  (with the supplier's alternative sheets and its reasons from the trace), `decision` for accept
  and walk-away, `result`, `trace` and `backoffice`. The timeline shows the supplier's reasons and
  back-office notes per round.
- **Pricing:** every sheet is priced with `arena_kit.cost` and the supplier's standard terms from
  its quote PDF, then checked against the arena's `c_open` / `c_deal`. Deals in
  `stabilise` / `secure_supply` cases differ only in the relationship term, because the arena
  knows the supplier's true cost.
- **Grouping:** runs are grouped by the experiment ledger (`experiments/*.jsonl`: author, agent,
  variant, commit, set). Sessions without a ledger row land in one `arena-<set>` run per day.
  Repeated plays of a case in one run are `case_D01~2.jsonl` and line up across runs in the
  comparison.
- **Filters:** the runs view filters by set and author.

Once `csee` writes its own run logs (`starter-kit/csee/runlog.py`), those runs show up next to the
imported ones.

## Fixtures

`dashboard/fixtures/runs/` holds runs that follow the log contract:

| Run | Cases |
|---|---|
| `20261024-143005-A` (specialists + strategist, full internals) | P01 Brandlhuber +9.5 % → deal, score 0.74 · P20 3-supplier RFQ, Kalwisz walks away → Wimbacher, 0.68 · P13 Lindlbauer walks away after we push past its final offer → no deal, 0.30 |
| `20261024-151744-C` (agentic, no internals, one 409 error) | P01 0.46 (a regression vs A, after a contradicted claim) · P20 0.72 · P13 0.73 |
| `20261024-101512-naive` | P01 0.18, the kit's naive agent |
| `20261024-140325-sim-naive` | **real log**: the kit's naive agent vs the local `arena-sim` (S01, S03) |

Every C and breakdown comes from `arena_kit.cost`. To regenerate them:

```bash
# from the repo root
uv run --project starter-kit python dashboard/fixtures/generate.py
# real log against the local simulator only (refuses any non-localhost URL):
(cd starter-kit && uv run --extra sim arena-sim serve --no-clock --data ../data --port 8765) &
uv run --project starter-kit python dashboard/fixtures/sim_log.py case:S01 case:S03 --url http://127.0.0.1:8765
```

The repo root `.gitignore` ignores every `runs/` folder; `fixtures/.gitignore` re-includes this one.

## Develop

```bash
cd dashboard/server && uv run dashboard --fixtures      # API on :8787
cd dashboard/web && npm run dev                          # Vite on :5173, proxies /api
cd dashboard/web && npm run build                        # typecheck + production build
cd dashboard/server && uv run pytest -q                  # server tests
```

API: `GET /api/runs` (runs with per-case summaries), `GET /api/runs/{run_id}/cases/{case_id}`
(all events), `GET /api/version` (changes whenever a run file changes), `GET /api/health`.
