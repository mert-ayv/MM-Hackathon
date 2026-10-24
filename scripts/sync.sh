#!/usr/bin/env bash
# Keep this checkout in sync with origin/main for the whole team (run by Claude Code hooks).
#   sync.sh pull   pull --rebase (autostash); never fails the session
#   sync.sh        pull, then commit everything (except secrets) and push
# Code changes in starter-kit/csee are pushed only if the free smoke test passes.
set -u
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$ROOT" || exit 0
say() { printf '{"systemMessage": "sync: %s"}\n' "$1"; }

if ! git pull --rebase --autostash -q origin main 2>/dev/null; then
  git rebase --abort 2>/dev/null
  say "pull failed (conflict?) - resolve manually with git status"
  exit 0
fi
[ "${1:-}" = "pull" ] && exit 0

[ -z "$(git status --porcelain)" ] && exit 0
git add -A
git reset -q -- starter-kit/.env '*.env' '.env*' 2>/dev/null   # never commit keys
git diff --cached --quiet && exit 0
if git diff --cached --name-only | grep -q '^starter-kit/csee/.*\.py$'; then
  if ! (cd starter-kit && uv run pytest -q tests/test_csee_smoke.py >/dev/null 2>&1); then
    git reset -q
    say "smoke test failed - code NOT pushed (run: cd starter-kit && uv run pytest tests/test_csee_smoke.py)"
    exit 0
  fi
fi
who="$(git config user.name || whoami)"
git commit -q -m "auto-sync: ${who} $(date +%H:%M)" || exit 0
if git push -q origin HEAD:main 2>/dev/null; then
  say "pushed $(git rev-parse --short HEAD)"
else
  say "push failed - will retry next turn"
fi
