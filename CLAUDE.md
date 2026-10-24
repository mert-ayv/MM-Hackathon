# MM-Hackathon: team csee-base, Tacto Negotiation Arena

We build an autonomous AI buyer agent (`starter-kit/csee/`) that negotiates with Tacto's supplier bots. Goal: **1st place in the Live Final, Sun 25 Oct 13:30** (code freeze 13:00). Read `CHALLENGE.md` (rules, scoring) and `STRATEGY.md` (plan, experiment workflow) before changing the agent.

## Team rules for every Claude session

- **The repo syncs automatically** (`.claude/settings.json` hooks → `scripts/sync.sh`): pull on session start and on every prompt, commit + push after every turn. Code in `starter-kit/csee` is only pushed if `tests/test_csee_smoke.py` passes. If a sync message reports a conflict or failure, fix it before continuing.
- **Ask the human before anything that uses practice quota** (200 sessions / 24h shared by 4 people): `csee run`/`csee play` on `case:P..`, `arena play/run --set practice`. State how many sessions it uses and how many are left (`uv run arena me`). Free and fine without asking: `csee bench` (sandbox D01/D02), the local simulator, the smoke test.
- **Never commit secrets**: `starter-kit/.env` holds the team arena key and LLM keys. Never print keys.
- **Never push to Tacto's repo** (`upstream`, push disabled). Kit updates: `git pull upstream main`.
- **Experiments**: each person owns one agent file in `csee/agents/` (`ege.py`, `mert.py`, `annika.py`, `emre.py`; subclasses of `CseeAgent`) and edits only their own; run with `--agent NAME`. Parameter tweaks = a variant in `csee/variants.py`, run with `--variant`. Compare with `python -m csee board`. Shared modules (`agent.py`, `levers.py`, `intel.py`, `writer.py`, `runner.py`) change every agent: keep `base` behaviour unless the team agrees. No `exp/` branches: `sync.sh` pushes HEAD to main. `base` on `main` is the champion that runs in the final.
- **During the Live Final our agent must not read** `/v1/events`, `/screen`, `/leaderboard`, `/results` (the `leaderboard` skill is for people only).
- Run commands from `starter-kit/` with `uv run`; background shell commands ignore `cd`, so use `uv run --directory <abs path>` and absolute log paths.
