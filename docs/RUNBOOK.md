# Sunday runbook: Live Final, 25 Oct 2026

All times are **CET, the new time** (clocks go back overnight: 03:00 → 02:00). Code freeze **13:00**, Live Final **13:30–14:30** (5 waves × 8 min), top-5 pitch **15:10**.

**Owner of the final machine:** ________ (one person; a cloud VM is preferred over a laptop on venue Wi-Fi).

## Before 08:00 (Saturday night)

- [ ] Final machine set up: repo cloned, `cd starter-kit && uv sync --all-extras`, `.env` copied over (never committed), `uv run arena me` answers with csee-base.
- [ ] `tmux` installed. On a laptop: power supply plugged in.
- [ ] Decide what the router plays (`starter-kit/csee/agents/router.py` ROUTES) from the board (`python -m csee board`) and the experiment log in [ARCHITECTURE.md](ARCHITECTURE.md).

## 08:00–11:30: data release and last improvements

- [ ] **08:05** `cd starter-kit && uv run arena data`, then check that the release was found (it must not print `None`):
  `uv run python -c "from arena_kit.data import DataPackage as D; p=D('data/package'); print(p.release, len(p.ids('news:')))"`
- [ ] Same on the final machine (or copy `data/release-sunday` over).
- [ ] Optional: extend the supplier profiles with the release's letters and news (a Claude session can do this in about 20 min).
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
