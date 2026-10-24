#!/usr/bin/env bash
# PreToolUse guard (Bash): Tacto's own `arena play` / `arena run` on practice cases spend our shared quota
# WITHOUT logging to experiments/ - nobody can tell afterwards who ran what. Practice goes through
# `python -m csee play|run ... --confirm` (logged: author, variant, commit, score). Sandbox (D01/D02, free)
# and a local arena-sim (ARENA_URL=http://127.0.0.1...) stay allowed.
python3 -c '
import json, re, sys
try:
    cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "")
except Exception:
    sys.exit(0)
# an invocation only: at the start of a command, after ; & | ( or `uv run` - not the words inside text/heredocs
kit = re.search(r"(?:^|[\n;&|(]\s*|\buv\s+run\s+(?:--\S+\s+\S+\s+)*)arena\s+(play|run)\b", cmd)
free = re.search(r"--set\s+sandbox|case:D\d|127\.0\.0\.1|localhost", cmd)
if kit and not free:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            "Team rule (CLAUDE.md): practice runs go through `uv run python -m csee play|run ... --confirm` "
            "so they are logged in experiments/ (who, which agent/variant, commit, score). Tacto’s "
            "`arena play/run` spends the shared quota without a log. Ask the human first, then use csee."),
    }}))
'
