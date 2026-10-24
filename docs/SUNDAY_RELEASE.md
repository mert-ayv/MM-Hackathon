# Sunday release runbook (Sun 25 Oct, 08:00-08:45 CET)

At 08:00 CET (07:00 UTC) Tacto publishes `release-sunday` (market news, supplier letters, a memo from
early October) with its own `facts.json` of **new IDs only**. Hidden final cases may cite it. We fold it
into `starter-kit/csee/profiles/` with `csee.profile_builder`, review the diffs, apply, push. Code freeze 13:00.

**If anything fails, do nothing:** the agent keeps the old curated profiles, and at runtime it still has
`case.facts` and the release itself (once installed under `$ARENA_DATA/release-sunday`, `DataPackage`
merges it and `intel.claims_for` already reads release news). A missed profile update costs a little
negotiating colour, never a case.

## Who does what

| When | Who | What |
|---|---|---|
| 07:55 | **Runner** (laptop with `starter-kit/.env`) | `git pull`; check `ARENA_DATA` in `starter-kit/.env` points at the package (absolute path, contains `facts.json`); `curl -s https://arena.tacto.ai/v1/data` shows `release-sunday` |
| 08:00-08:05 | Runner | `scripts/sunday_release.sh` (retry every 2-3 min until the release is public) |
| 08:05-08:25 | **Reviewers** (2 people, split the suppliers alphabetically) | read `REPORT.md`, then each `<id>.md` |
| 08:25-08:35 | Runner | apply, smoke test, commit, push |
| 08:35-08:45 | **Infra** (final VM owner) | install the release on the final machine (same steps 0-2), pull the profiles, smoke test |

## Commands

```bash
cd starter-kit
# whole Sunday path: check ARENA_DATA, download, install release, stage updates (strong model), smoke test
../scripts/sunday_release.sh                       # PROFILE_MODEL defaults to claude-opus-5-5
EXTRA_ARGS=--market-fanout ../scripts/sunday_release.sh   # also re-check every supplier whose category a
                                                          # market item touches (more calls, ~45 s wall)
```

What the script does:

0. Resolves `ARENA_DATA` (env, else `starter-kit/.env`, relative = to `starter-kit/`) and **stops loudly**
   if it has no `facts.json` - the agent would otherwise run without data.
1. `uv run arena data --out runs/download-<stamp>` (GETs only, never over the package).
2. Finds the release's `facts.json`, copies the folder to **`$ARENA_DATA/release-sunday`** (where
   `DataPackage(ARENA_DATA)` finds it; an older copy is moved to `.bak-<stamp>`), and asserts
   `DataPackage(ARENA_DATA).release` is set.
3. `python -m csee.profile_builder update --release ...` - every affected supplier in parallel
   (rehearsal: 23 suppliers in ~25 s wall with Opus 5.5, ~$0.045 per supplier; Haiku ~$0.002).
4. Prints the report path: `runs/profiles/release-<stamp>/REPORT.md`.
5. Runs the smoke test. **It stops before `apply` and before `git push`.**

Manual equivalents (if the script breaks):

```bash
cd starter-kit
uv run arena data --out runs/dl && ls runs/dl            # find release-sunday/facts.json
cp -R runs/dl/release-sunday "$ARENA_DATA/release-sunday"
uv run --extra anthropic python -m csee.profile_builder --data "$ARENA_DATA" \
    update --release "$ARENA_DATA/release-sunday" --model claude-opus-5-5
uv run python -m csee.profile_builder apply runs/profiles/<stamp>            # all
uv run python -m csee.profile_builder apply runs/profiles/<stamp> --only 70110 70240   # a subset
```

Model: `--model` > `PROFILE_MODEL` > `claude-haiku-5-5`. If Opus is slow or rate-limited, rerun with
`PROFILE_MODEL=claude-sonnet-5-5` (~$0.025 per supplier).

## How to review (08:05-08:25)

`REPORT.md` has one row per supplier: new items, whether the model found them relevant, how many
pressures/arguments were added, removals, check notes, **agent signals changed**, time and cost.
Each `<id>.md` shows: change summary, the new items' text, situation before/after, every added entry,
`what_it_values` before/after, removals with their reasons, the agent-signal diff, the ID/quote check
log, and the full JSON diff.

Check, in this order:

1. **Agent signals changed** (column + section). These are the keywords `agent.py` acts on:
   a new `cash` pressure raises the supplier's interest rate in `supplier_estimate`; `cash`/`payment` in
   `what_it_values` or a `payment_days` tradeable adds a faster-payment trade sheet; and any claim kind
   (`index`, `news`, `scorecard`, ...) named in `arguments_to_avoid` makes the agent **skip all claims of
   that kind** for this supplier. A WARNING line flags the last case - accept it only if intended.
2. **Removals**: every removal must name the new item that makes the old entry wrong. Reject otherwise.
3. **Numbers in the situation and arguments** match the new letter (asked %, price, effective date,
   notice days). Hard fields are never touched by the update.
4. **Checks**: "dropped unknown ID" / "dropped non-verbatim quote" lines are fine (the guard did its
   job); if a key argument was dropped, it is simply not in the profile.
5. `_market.json`: company-wide items (memo, market news): summary, categories, series, implication.

To reject one supplier: apply with `--only` for the others, or delete its staged `.json` first.
To fix one by hand: edit the staged `.json`, then apply.

## Apply and push (08:25-08:35)

```bash
cd starter-kit
uv run python -m csee.profile_builder apply runs/profiles/release-<stamp>
uv run pytest -q tests/test_csee_smoke.py tests/test_profile_builder.py
git add csee/profiles && git commit -m "profiles: Sunday release" && git push
```

Applying is safe for the agent: profiles keep the same schema, plus `updated_from` (new IDs) and
`update_notes`; `_market.json` is ignored by `intel.load_profile` unless the optional hook is merged.

## Fallbacks

| Problem | Do |
|---|---|
| Release not public at 08:05 | rerun the script every few minutes; nothing changes until it succeeds |
| `ARENA_DATA ... has no facts.json` | fix `ARENA_DATA` in `starter-kit/.env` (absolute path to the package); `uv run arena data` if the package is missing |
| Release layout differs (no `facts.json` at the top) | point `RELEASE_DIR=` at the folder holding `facts.json`; the updater reads any new ID from `facts.json` + `data/*.csv` and fetches text via `DataPackage.document` |
| Some suppliers fail (listed under Errors) | they keep their old profile; rerun `update --suppliers <ids>` |
| LLM down / no key | skip the profile update entirely; still install the release (steps 0-2) so the agent sees its facts |
| Review not finished by 09:00 | apply only the reviewed suppliers with `--only` |
| Anything doubtful after apply | `git revert` the profiles commit - the old profiles + `case.facts` at runtime are the baseline |

## Tools behind it (`starter-kit/csee/profile_builder/`)

```bash
uv run python -m csee.profile_builder facts 70110      # deterministic hard fields (SQL)
uv run python -m csee.profile_builder validate         # field-by-field vs the 46 curated profiles
uv run --extra anthropic python -m csee.profile_builder soft 70110 70240   # LLM soft fields -> staged
uv run python -m csee.profile_builder rehearse build --also doc:20260913-70430-P15 --orphan-memos
uv run --extra anthropic python -m csee.profile_builder rehearse run [--model M] [--suppliers ...]
```

The rehearsal holds out every document and news item from 2026-09-15 on (plus a memo), packages them in
the release layout (`facts.json` with only those IDs, `data/documents.csv`, `data/news.csv`,
`correspondence/*.md`), strips them from a copy of the package and from the curated profiles, runs the
update and scores how much of the held-out information comes back (`REHEARSAL.md`).
