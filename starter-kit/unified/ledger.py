"""The experiment ledger: one line per finished case, tagged with who ran which agent version.

The arena's session list does not know our variants, so every run writes its own record to
`experiments/<date>-<author>.jsonl` at the repo root (one file per person: no merge conflicts).
Commit and push it; `python -m csee board` compares every agent across the whole team.
"""

import getpass
import hashlib
import json
import os
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "experiments"


def _git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def author():
    """CSEE_AUTHOR (e.g. in .env) if set, else the git user name."""
    name = os.environ.get("CSEE_AUTHOR") or _git("config", "user.name") or getpass.getuser()
    return "".join(ch for ch in name.lower().replace(" ", "-") if ch.isalnum() or ch == "-") or "unknown"


def _snapshot():
    """(tag, patch path, on origin) of the agent code this run executes. Uncommitted edits under
    starter-kit/unified (tracked and new files) are saved as experiments/patches/<hash>.diff, so any run
    is reproducible: `git checkout <commit> && git apply experiments/patches/<hash>.diff`."""
    head = _git("rev-parse", "--short", "HEAD") or "nogit"
    diff = _git("diff", "HEAD", "--", "starter-kit/unified")
    for f in _git("ls-files", "--others", "--exclude-standard", "--", "starter-kit/unified").split():
        diff += "\n" + _git("diff", "--no-index", "--", "/dev/null", f)
    try:
        on_origin = (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"], cwd=ROOT, timeout=5
            ).returncode
            == 0
        )
    except Exception:
        on_origin = False
    if not diff.strip():
        return head, None, on_origin
    digest = hashlib.sha1(diff.encode()).hexdigest()[:8]
    patch = FOLDER / "patches" / f"{digest}.diff"
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_text(diff.strip() + "\n")
    return f"{head}+{digest}", str(patch.relative_to(ROOT)), on_origin


_SNAP = None


def snapshot():
    """(tag, patch, on origin), taken once when a logged command starts (play/run/final): edits made while it
    runs do not belong to it. Not on import, so the simulator never writes patch files."""
    global _SNAP
    if _SNAP is None:
        _SNAP = _snapshot()
    return _SNAP


def commit():
    """The commit a logged run uses (its snapshot), else just HEAD (the simulator)."""
    return _SNAP[0] if _SNAP else (_git("rev-parse", "--short", "HEAD") or "nogit")


def record(case_id, set_, result, variant, params, llm, note="", agent="base"):
    tag, patch, on_origin = snapshot()
    FOLDER.mkdir(exist_ok=True)
    if "arena.tacto.ai" not in os.environ.get("ARENA_URL", "https://arena.tacto.ai"):
        set_ = f"sim-{set_}"  # a local arena-sim run (e.g. the final rehearsal) never counts as the real set
    now = datetime.now(UTC)
    row = {
        "ts": now.isoformat(timespec="seconds"),
        "author": author(),
        "agent": agent,  # "unified" for this package
        "variant": variant,
        "commit": tag,
        "patch": patch,  # uncommitted agent edits this run used (None = exactly the commit)
        "on_origin": on_origin,  # the commit was already on origin/main (others can check it out)
        "host": socket.gethostname(),
        "llm": llm,
        "set": set_,
        "case_id": case_id,
        "session_id": result.get("session_id") if isinstance(result, dict) else None,
        "deal": result.get("deal") if isinstance(result, dict) else None,
        "score": result.get("score") if isinstance(result, dict) else None,
        "c_open": result.get("c_open") if isinstance(result, dict) else None,
        "c_deal": result.get("c_deal") if isinstance(result, dict) else None,
        "c_best": result.get("c_best") if isinstance(result, dict) else None,
        "error": None if isinstance(result, dict) else str(result)[:300],
        "final_est": {},  # csee's board reads it; unified has no final estimate
        "params": params,
        "variant_desc": _desc(variant),
        "note": note,
    }
    path = FOLDER / f"{now:%Y-%m-%d}-{row['author']}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return row


DESCRIPTION = (
    "Unified agent (starter-kit/unified): one shared flow - v14 defaults plus per-type settings, walk-risk guard "
    "(never counters a final offer), risk-sharing clause sheet on the blamed index, cost-first claims, patience "
    "while the supplier still concedes."
)


def _desc(variant):
    return DESCRIPTION

