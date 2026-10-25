# Sunday runbook: Live Final, 25 Oct 2026

All times are **CET, the new time** (clocks go back overnight: 03:00 → 02:00). Code freeze **13:00**, Live Final **13:30–14:30** (5 waves × 8 min), top-5 pitch **15:10**.

**Owner of the final machine:** Mert (go49mor), his MacBook Pro: repo, `.env` and the uv environment are set up and tested there (decided Sat 21:15; a fresh cloud VM the night before would add more risk than it removes).
- On power the whole time, `caffeinate -dims` running, lid open; venue Wi-Fi plus a **phone hotspot ready** as fallback. The runner retries failed cases while a wave runs and a restart resumes running sessions (409).
- **Standby:** a second teammate laptop with the repo cloned at the `final` tag and `.env` copied, runner NOT started. Start it only if the MacBook is confirmed dead (two runners on one key would both answer the same sessions). Then the standby runs exactly the same command; it resumes the open sessions.

## Before 08:00 (Saturday night)

- [x] Final machine: Mert's MacBook (repo, `.env`, uv environment, tests green on Sat night).
- [x] Router decided: `starter-kit/csee/agents/router.py` ROUTES (A/B dress rehearsal + robustness sweep; see [ARCHITECTURE.md](ARCHITECTURE.md)). No route changes after 11:30 without dress-rehearsal evidence.
- [ ] `tmux` is not installed: `brew install tmux`, or use `screen` (installed).

## Minute-by-minute checklist, 07:45-14:30

Built from a pre-mortem on Sat night ("it is 16:00 and we did not win - why?"). The top risks, in order:
1. The runner is not really playing at 13:30.
2. The machine sleeps, loses power or loses the network.
3. Open sessions or the rate budget are contended (stale or teammates' sessions, a second runner).
4. Submission or freeze mechanics (repo private, wrong hash, a push after 13:00).
5. The release is not loaded or breaks the agent.
6. Resume semantics after a crash.
7. Network blips.
8. LLM writer degraded.
9. A hidden case breaks a route.
10. The pitch.

> **Sleep kills cases.** Sat 01:30 a single-shot router run lost P11 (record-level final offer 45.00, worth 0.794): the MacBook slept 51 min mid-run, the arena's 60 s clock ran on, the session timed out. `csee final/run/play` now start `caffeinate -dimsu -w <pid>` themselves (macOS), but still do `pmset` + `caffeinate` below.

- [ ] **07:45** Phones show CET. Final machine: power in, lid open, battery charging. `brew install tmux` (or use `screen`). `sudo pmset -a sleep 0 displaysleep 0 disablesleep 1`. Hotspot tested once.
- [ ] **08:00** `curl -s https://arena.tacto.ai/v1/data` until `release-sunday` carries a `url`.
- [ ] **08:05** `cd starter-kit && uv run arena data`, then the DataPackage one-liner (section 1.5): release path not None; facts > 10356, news > 39, docs > 208. Else `ARENA_RELEASE=/abs/path` in `.env`.
- [ ] **08:10** `uv run python -m csee.dossier` sanity check. One person reads memo + news, posts "what changes for the agent" by 08:30.
- [ ] **08:15** Free regression with the release: `uv run pytest -q tests/test_csee_smoke.py -k router`; `uv run python -m csee --agent router --no-llm sim --seeds 1`; `uv run python -m csee --agent router bench --repeat 1`.
- [ ] **08:20-09:00** Optional profiles: `scripts/sunday_release.sh` (stages only) -> two reviewers read every `arguments_to_avoid` and every removal -> apply -> `csee.fallback archetypes` -> `pytest tests/test_fallback.py tests/test_csee_smoke.py` -> commit. In doubt, skip.
- [ ] **09:00-11:30** Improvements only with evidence; router smoke green before every Stop-hook push; keep >= 30 practice sessions in reserve.
- [ ] **11:30 FEATURE FREEZE.** Bug fixes only. Full suite: `uv run pytest -q tests` (~6 min). Anthropic console: credits + limits.
- [ ] **11:35** Standby laptop: `git pull`, `.env` via AirDrop, `uv sync --all-extras`, `uv run arena data`, `uv run arena me` OK. Nothing started.
- [ ] **11:45** Hack & More: demo + technical video and architecture notes uploaded; approach text (README "Our approach") ready to paste. Slides done, speaker + timer assigned.
- [ ] **12:00** Pre-flight on the final machine and venue network (1 session): `uv run python -m csee --agent router -v play case:P04 --confirm`. Check: sane score, LLM e-mails written, no `template used` / `decision took` warnings, replay opens. Decide the network for the final (portal/drops -> hotspot).
- [ ] **12:15** Mechanics rehearsal (free): terminal 1 `uv run arena-sim serve --final-rehearsal --data data/package`; terminal 2 `ARENA_URL=http://127.0.0.1:8000 uv run arena register csee sim`, then `ARENA_URL=http://127.0.0.1:8000 ARENA_API_KEY=<sim key> uv run python -m csee --agent router -v final --waves 2 --no-runlog` -> "wave 2 closed", no Traceback. Stop the sim afterwards.
- [ ] **12:30** Close every Claude Code session in every clone. `git pull && git status --porcelain` empty; `git log -1 origin/main` == local HEAD.
- [ ] **12:35** Repo public: `gh repo edit mert-ayv/MM-Hackathon --visibility public --accept-visibility-change-consequences`; logged-out `curl -s -o /dev/null -w '%{http_code}\n' https://github.com/mert-ayv/MM-Hackathon` -> 200.
- [ ] **12:40** `git tag final && git push origin final && git rev-parse final && git ls-remote --tags origin final` (same hash). Post the hash. From now nobody commits or pushes.
- [ ] **12:45** Submit on Hack & More: repo link, FULL hash of `final`, approach text. Screenshot the confirmation.
- [ ] **12:55** Hook freeze active. Every laptop: `git status` shows nothing to push.
- [ ] **13:00 CODE FREEZE.** Every laptop: `pgrep -fl "csee|arena|import_sessions"` -> kill. Run the stale-session snippet (section 1.3) -> `open now: 0`.
- [ ] **13:05** Final machine: `git fetch && git status --porcelain && git checkout final && git rev-parse HEAD` (== submitted). `cd starter-kit && uv sync --all-extras && uv run --no-sync python -c "import anthropic, csee.agents; print('ok')" && uv run arena me`.
- [ ] **13:10** `screen -S final` (or tmux). Window 1: `caffeinate -dims`. Window 2, from `starter-kit/`:
```bash
mkdir -p logs; LOG=logs/final-$(date +%H%M).log
while :; do
  PYTHONUNBUFFERED=1 uv run --no-sync python -m csee --agent router -v final 2>&1 | tee -a "$LOG"
  grep -q "wave 5 closed" "$LOG" && break
  sleep 3
done
```
- [ ] **13:15** Runner started; no output is normal until wave 1 (403 is silent). Window 3: `tail -f "$LOG" | grep -E "wave|closing|error|failed|Traceback|template used|decision took"`.
- [ ] **13:20** Standby laptop at `final`, ready, NOT started.
- [ ] **13:25** Heartbeat from a second terminal: `uv run arena me` (active). Phone hotspot on, phone on power. Hands off the keyboard from 13:29.
- [ ] **13:30-14:30 hands off.** Only `tail -f`. Expect `wave 1: starting` within ~10 s of the host; if nothing by 13:32: `uv run arena me`, network, then let the loop restart. Restart only a dead process; standby only for a dead MacBook. Nobody touches the key, `csee board/eval`, `arena board`, the dashboard, or git.
- [ ] **14:30** Humans: results, pick the replay, go to the Tacto office; pitch 15:10. Restore `pmset` afterwards.

**Stale-session snippet** (13:00, no quota; walking away from an open practice/sandbox session leaves our best score untouched):
```bash
cd starter-kit && uv run python - <<'EOF'
from arena_kit.cli import load_env; load_env()
from arena_kit.client import ArenaClient
c = ArenaClient()
for set_ in ("practice", "sandbox"):
    for s in c.sessions(set_):
        if s.get("status") != "ended":
            st = c.session(s["session_id"]); sid = next(iter(st["threads"]))
            r = c.send_message(s["session_id"], sid, {"action": {"type": "walk_away"}})
            print("closed", set_, s["case_id"], s["session_id"], r.get("end_reason"))
print("open now:", sum(x.get("status") != "ended" for t in ("practice", "sandbox") for x in c.sessions(t)))
EOF
```

## After the final

- No pushes until the awards. If we're in the top 5, the pitch is at **15:10** at the Tacto office: pick a replay from https://arena.tacto.ai/results (see [PITCH_DEMO_IDEAS.md](PITCH_DEMO_IDEAS.md)).
