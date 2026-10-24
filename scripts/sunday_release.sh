#!/usr/bin/env bash
# Sunday 08:00 runbook in one command: fetch the release, install it where the agent's DataPackage
# finds it, stage profile updates, smoke test. Stops BEFORE applying and pushing: a human reviews.
#
#   scripts/sunday_release.sh                                  # strong model (default claude-opus-5-5)
#   PROFILE_MODEL=claude-sonnet-5-5 scripts/sunday_release.sh
#   RELEASE_DIR=/path/to/release-sunday scripts/sunday_release.sh   # skip the download (rehearsal)
#   ARENA_DATA=/abs/path/to/package scripts/sunday_release.sh       # else taken from starter-kit/.env
#   EXTRA_ARGS=--market-fanout scripts/sunday_release.sh            # also update suppliers by market category
set -euo pipefail
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
KIT="$ROOT/starter-kit"
cd "$KIT"
export PROFILE_MODEL="${PROFILE_MODEL:-claude-opus-5-5}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$KIT/runs/profiles/release-$STAMP"
say() { printf '\n== %s\n' "$*"; }
die() { printf '\n!!!!!!!! %s\n' "$*" >&2; exit 2; }

# 0. ARENA_DATA: the package the agent loads (env wins, else starter-kit/.env; relative = to starter-kit/)
if [ -z "${ARENA_DATA:-}" ] && [ -f .env ]; then
  ARENA_DATA="$(grep -E '^ARENA_DATA=' .env | tail -1 | cut -d= -f2- | tr -d "\"'" || true)"
fi
[ -n "${ARENA_DATA:-}" ] || die "ARENA_DATA is not set (env or starter-kit/.env). The agent would run WITHOUT data."
case "$ARENA_DATA" in /*) ;; *) ARENA_DATA="$KIT/$ARENA_DATA" ;; esac
[ -f "$ARENA_DATA/facts.json" ] || die "ARENA_DATA=$ARENA_DATA has no facts.json. Fix ARENA_DATA in starter-kit/.env
(e.g. ARENA_DATA=/abs/path/to/data/package) or run 'uv run arena data' first. The agent needs it at runtime."
export ARENA_DATA
echo "ARENA_DATA=$ARENA_DATA (facts.json ok)"
INSTALL="$ARENA_DATA/release-sunday"  # DataPackage looks in <root>/release-sunday (or a sibling)

# 1. download + unpack into a fresh folder (never over the package)
if [ -z "${RELEASE_DIR:-}" ]; then
  say "1/5 arena data (GET /v1/data, no key needed)"
  curl -fsS https://arena.tacto.ai/v1/data || true
  echo
  DL="$KIT/runs/download-$STAMP"
  mkdir -p "$DL"
  uv run arena data --out "$DL"
  FOUND="$(find "$DL" -name facts.json -path '*release*' | head -1)"
  [ -n "$FOUND" ] || die "NO RELEASE in the download (not public yet?). Nothing changed. Retry in a few minutes."
  RELEASE_DIR="$(dirname "$FOUND")"
fi

# 2. the release must exist; install it next to the package so the agent reads it at runtime
say "2/5 locate + install the release"
[ -f "$RELEASE_DIR/facts.json" ] || die "RELEASE_DIR=$RELEASE_DIR has no facts.json"
RELEASE_DIR="$(cd "$RELEASE_DIR" && pwd)"
if [ "$RELEASE_DIR" != "$INSTALL" ]; then
  [ -e "$INSTALL" ] && mv "$INSTALL" "$INSTALL.bak-$STAMP" && echo "old release moved to $INSTALL.bak-$STAMP"
  cp -R "$RELEASE_DIR" "$INSTALL"
fi
uv run python - "$ARENA_DATA" <<'PY' || die "DataPackage does not see the release under ARENA_DATA"
import sys, json
from arena_kit.data import DataPackage
p = DataPackage(sys.argv[1])
assert p.release, "no release found"
n = len(json.loads((p.release / "facts.json").read_text()))
print(f"DataPackage({sys.argv[1]}).release = {p.release} ({n} new IDs)")
PY

# 3. stage updates for every affected supplier, in parallel, with the strong model
say "3/5 update profiles with $PROFILE_MODEL (staged, NOT applied)"
time uv run --extra anthropic python -m csee.profile_builder --data "$ARENA_DATA" \
  update --release "$INSTALL" --out "$OUT" ${EXTRA_ARGS:-}

# 4. where to review
say "4/5 review"
echo "REPORT:   $OUT/REPORT.md"
echo "per supplier: $OUT/<id>.md   market: $OUT/_market.json"

# 5. smoke test (current, unchanged profiles)
say "5/5 smoke test"
uv run pytest -q tests/test_csee_smoke.py

say "NEXT (human): review, then"
echo "  cd $KIT && uv run python -m csee.profile_builder apply $OUT"
echo "  uv run pytest -q tests/test_csee_smoke.py && git add csee/profiles && git commit -m 'profiles: Sunday release' && git push"
echo "  (the final machine also needs the release at \$ARENA_DATA/release-sunday: rerun steps 0-2 there,"
echo "   or copy $INSTALL)"
