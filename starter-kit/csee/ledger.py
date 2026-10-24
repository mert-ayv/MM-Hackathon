"""The experiment ledger: one line per finished case, tagged with who ran which agent version.

The arena's session list does not know our variants, so every run writes its own record to
`experiments/<date>-<author>.jsonl` at the repo root (one file per person: no merge conflicts).
Commit and push it; `python -m csee board` compares every variant across the whole team.
"""

import getpass
import hashlib
import json
import os
import socket
import statistics
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
    starter-kit/csee (tracked and new files) are saved as experiments/patches/<hash>.diff, so any run
    is reproducible: `git checkout <commit> && git apply experiments/patches/<hash>.diff`."""
    head = _git("rev-parse", "--short", "HEAD") or "nogit"
    diff = _git("diff", "HEAD", "--", "starter-kit/csee")
    for f in _git("ls-files", "--others", "--exclude-standard", "--", "starter-kit/csee").split():
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


# taken once, when the run starts: edits made while it runs do not belong to it
COMMIT, PATCH, ON_ORIGIN = _snapshot()


def commit():
    return COMMIT


def record(case_id, set_, result, variant, params, llm, note="", agent="base"):
    FOLDER.mkdir(exist_ok=True)
    if "arena.tacto.ai" not in os.environ.get("ARENA_URL", "https://arena.tacto.ai"):
        set_ = f"sim-{set_}"  # a local arena-sim run (e.g. the final rehearsal) never counts as the real set
    now = datetime.now(UTC)
    row = {
        "ts": now.isoformat(timespec="seconds"),
        "author": author(),
        "agent": agent,  # the team agent from csee/agents/ (rows before the split: base)
        "variant": variant,
        "commit": commit(),
        "patch": PATCH,  # uncommitted agent edits this run used (None = exactly the commit)
        "on_origin": ON_ORIGIN,  # the commit was already on origin/main (others can check it out)
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
        "params": params,
        "variant_desc": _desc(variant),
        "note": note,
    }
    path = FOLDER / f"{now:%Y-%m-%d}-{row['author']}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return row


def _desc(variant):
    from .variants import description

    return description(variant)


def load():
    rows = []
    for p in sorted(FOLDER.glob("*.jsonl")):
        for line in p.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def label(row):
    """[agent/]variant@commit[+llm]; the base agent keeps the bare variant label rows had before the split."""
    agent = row.get("agent") or "base"
    prefix = "" if agent == "base" else f"{agent}/"
    return f"{prefix}{row['variant']}@{row['commit']}{'+llm' if row.get('llm') else ''}"


def board(rows, house=None, set_="practice"):
    """Agent/variant x case: mean score (runs)."""
    rows = [r for r in rows if r.get("set") == set_ and r.get("score") is not None]
    house = house or {}
    cases = sorted({r["case_id"] for r in rows} | set(house if set_ == "practice" else []))
    labels = sorted({label(r) for r in rows})
    head = "| Agent/variant | Mean | " + " | ".join(c.replace("case:", "") for c in cases) + " |"
    out = [head, "|" + "---|" * (len(cases) + 2)]
    if house:
        hs = [house.get(c) for c in cases]
        out.append(
            "| *house agent* | "
            + f"{statistics.mean([h for h in hs if h is not None]):.3f} | "
            + " | ".join(f"{h:.2f}" if h is not None else "-" for h in hs)
            + " |"
        )
    for name in labels:
        mine = [r for r in rows if label(r) == name]
        cells, means = [], []
        for c in cases:
            s = [r["score"] for r in mine if r["case_id"] == c]
            if s:
                means.append(statistics.mean(s))
                cells.append(f"{statistics.mean(s):.2f}" + (f" ({len(s)})" if len(s) > 1 else ""))
            else:
                cells.append("-")
        mean = f"{statistics.mean(means):.3f}" if means else "-"
        out.append(f"| {name} | {mean} | " + " | ".join(cells) + " |")
    return "\n".join(out)
