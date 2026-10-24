"""The experiment ledger: one line per finished case, tagged with who ran which agent version.

The arena's session list does not know our variants, so every run writes its own record to
`experiments/<date>-<author>.jsonl` at the repo root (one file per person: no merge conflicts).
Commit and push it; `python -m csee board` compares every variant across the whole team.
"""

import getpass
import json
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
    name = _git("config", "user.name") or getpass.getuser()
    return "".join(ch for ch in name.lower().replace(" ", "-") if ch.isalnum() or ch == "-") or "unknown"


def commit():
    head = _git("rev-parse", "--short", "HEAD") or "nogit"
    dirty = bool(_git("status", "--porcelain", "--", "starter-kit/csee"))
    return head + ("+dirty" if dirty else "")


def record(case_id, set_, result, variant, params, llm, note=""):
    FOLDER.mkdir(exist_ok=True)
    now = datetime.now(UTC)
    row = {
        "ts": now.isoformat(timespec="seconds"),
        "author": author(),
        "variant": variant,
        "commit": commit(),
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
        "note": note,
    }
    path = FOLDER / f"{now:%Y-%m-%d}-{row['author']}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return row


def load():
    rows = []
    for p in sorted(FOLDER.glob("*.jsonl")):
        for line in p.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def board(rows, house=None, set_="practice"):
    """Variant x case: mean score (runs). Label = variant@commit[+llm]."""
    rows = [r for r in rows if r.get("set") == set_ and r.get("score") is not None]
    house = house or {}
    cases = sorted({r["case_id"] for r in rows} | set(house if set_ == "practice" else []))
    labels = sorted({f"{r['variant']}@{r['commit']}{'+llm' if r.get('llm') else ''}" for r in rows})
    head = "| Variant | Mean | " + " | ".join(c.replace("case:", "") for c in cases) + " |"
    out = [head, "|" + "---|" * (len(cases) + 2)]
    if house:
        hs = [house.get(c) for c in cases]
        out.append(
            "| *house agent* | "
            + f"{statistics.mean([h for h in hs if h is not None]):.3f} | "
            + " | ".join(f"{h:.2f}" if h is not None else "-" for h in hs)
            + " |"
        )
    for label in labels:
        mine = [r for r in rows if f"{r['variant']}@{r['commit']}{'+llm' if r.get('llm') else ''}" == label]
        cells, means = [], []
        for c in cases:
            s = [r["score"] for r in mine if r["case_id"] == c]
            if s:
                means.append(statistics.mean(s))
                cells.append(f"{statistics.mean(s):.2f}" + (f" ({len(s)})" if len(s) > 1 else ""))
            else:
                cells.append("-")
        mean = f"{statistics.mean(means):.3f}" if means else "-"
        out.append(f"| {label} | {mean} | " + " | ".join(cells) + " |")
    return "\n".join(out)
