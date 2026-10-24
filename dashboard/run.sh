#!/usr/bin/env bash
# One command: build the frontend if needed, then serve it plus the read-only API on one port.
#   ./dashboard/run.sh                  # runs/ (falls back to the fixtures while runs/ is empty)
#   ./dashboard/run.sh --fixtures       # runs/ and the fixtures
#   ./dashboard/run.sh --build --open   # force a rebuild, open the browser
set -euo pipefail
cd "$(dirname "$0")"

args=()
force=0
for a in "$@"; do
  if [ "$a" = "--build" ]; then force=1; else args+=("$a"); fi
done

stale() {
  [ ! -f web/dist/index.html ] && return 0
  [ -n "$(find web/src web/index.html web/package.json web/tailwind.config.js -newer web/dist/index.html 2>/dev/null | head -1)" ]
}

if [ "$force" = 1 ] || stale; then
  echo "Building the dashboard frontend…"
  (cd web && { [ -d node_modules ] || npm ci --no-audit --no-fund; } && npm run build >/dev/null)
fi

exec uv run --project server dashboard ${args[@]+"${args[@]}"}
