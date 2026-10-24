# Sunday runbook: Live Final, 25 Oct 2026

All times are **CET, the new time** (clocks go back overnight: 03:00 → 02:00). Code freeze **13:00**, Live Final **13:30–14:30** (5 waves × 8 min), top-5 pitch **15:10**.

**Owner of the final machine:** Mert (go49mor), his MacBook Pro: repo, `.env` and the uv environment are set up and tested there (decided Sat 21:15; a fresh cloud VM the night before would add more risk than it removes).
- On power the whole time, `caffeinate -dims` running, lid open; venue Wi-Fi plus a **phone hotspot ready** as fallback. The runner retries failed cases while a wave runs and a restart resumes running sessions (409).
- **Standby:** a second teammate laptop with the repo cloned at the `final` tag and `.env` copied, runner NOT started. Start it only if the MacBook is confirmed dead (two runners on one key would both answer the same sessions). Then the standby runs exactly the same command; it resumes the open sessions.

## Before 08:00 (Saturday night)

- [ ] Final machine set up: repo cloned, `cd starter-kit && uv sync --all-extras`, `.env` copied over (never committed), `uv run arena me` answers with csee-base.
- [ ] `tmux` installed. On a laptop: power supply plugged in.
- [ ] Decide what the router plays (`starter-kit/csee/agents/router.py` ROUTES) from the board (`python -m csee board`) and the experiment log in [ARCHITECTURE.md](ARCHITECTURE.md).

## 08:00–11:30: data release and last improvements

- [ ] **08:05** `cd starter-kit && uv run arena data`, then check that the release was found (it must not print `None`):
  `uv run python -c "from arena_kit.data import DataPackage as D; p=D('data/package'); print(p.release, len(p.ids('news:')))"`
- [ ] Same on the final machine (or copy `data/release-sunday` over).
- [ ] `uv run python -m csee.dossier`: lists what the release adds per supplier (new hedges, price letters, cash asks, news). The agent re-derives these at runtime from the merged package; check that nothing looks wrong (e.g. a hedge on the wrong series).
- [ ] Optional: extend the supplier profiles with the release's letters and news: `scripts/sunday_release.sh` (Annika's profile builder; see `docs/SUNDAY_RELEASE.md`; needs `ANTHROPIC_API_KEY`). It only **stages** changes. Before `apply`:
  - **Read every newly added `arguments_to_avoid` entry by hand.** The agent drops an argument whose kind keywords appear there (`should-cost`, `cost:`, `quote`, `competitor`, `otd`, `delivery record`, `ppm`, `forecast`, `notice`, `news:`, or an index series and its theme: electric, copper, alloy, steel). One careless entry can silently switch off our strongest argument for that supplier.
  - Check the "Removed" section (removal matching is loose).
  - After `apply`: `uv run python -m csee.fallback archetypes`, then `uv run pytest -q tests/test_fallback.py tests/test_csee_smoke.py`, then commit.
- [ ] **11:30 feature freeze.** After that, bug fixes only.

## 11:30–12:55: pre-flight and submission

- [ ] Pre-flight **on the final machine, with the final setup** (this one uses 1 practice session):
  `uv run python -m csee --agent router -v play case:P04 --confirm`
- [ ] Free mechanics check: `uv run python -m csee --agent router bench --repeat 1` (sandbox).
- [ ] With the LLM writer on: confirm that the e-mails get written and that `writer … template used` warnings stay rare (rate limits for about 30 parallel calls).
- [ ] README "Our approach" section filled in; 1-min demo and technical videos uploaded.
- [ ] **12:45 Make the repo public** so the jury can open it (the history was checked: no keys). Then `git tag final && git push origin final`.
- [ ] **12:55 Submit on Hack & More:** repo link, the **full commit hash** of `final`, the approach description.

## 13:00: code freeze

- [ ] From 11:55 UTC (12:55 CET), `scripts/sync.sh` stops committing and pushing by itself. **Nobody pushes until the results are out.** Slides live outside the repo.
- [ ] Stop **all** practice, sandbox, bench and dashboard runs and close Claude Code sessions in the repo: they share our key's 10 open sessions and 10 calls/s.
- [ ] Check that no practice session is still open (`GET /v1/sessions?set=practice`, all `ended`).

## 13:15: start the final runner (and leave it running)

On the final machine, in `tmux`, from a checkout of exactly the submitted commit:

```bash
git fetch && git checkout final            # the tagged, submitted commit (detached: auto-sync stays off)
cd starter-kit && mkdir -p logs
while :; do
  uv run python -m csee --agent router -v final 2>&1 | tee -a logs/final.log
  grep -q "wave 5 closed" logs/final.log && break
  sleep 3                                   # crashed? restart: it picks up its running sessions (409 → resume)
done
```

On a laptop, also run `caffeinate -dims` in a second tmux window.

## 13:30–14:30: hands off

- **No human in the loop.** Restarting a crashed runner is allowed; choosing cases or writing messages is not.
- **Our agent must not read** `/v1/events`, `/screen`, `/leaderboard` or `/results`. Don't invoke the `leaderboard` skill or `csee board` during the final. People may watch the venue screen.
- Watch only `logs/final.log`: `tail -f logs/final.log | grep -E "wave|closing|error|failed"`.

## After the final

- No pushes until the awards. If we're in the top 5, the pitch is at **15:10** at the Tacto office: pick a replay from https://arena.tacto.ai/results (see [PITCH_DEMO_IDEAS.md](PITCH_DEMO_IDEAS.md)).
