"""What a practice case would have scored under Live-Final time pressure, from its run log.

Practice has no clock; the final gives each wave 8 minutes and the runner closes ~90 s before the cap
(earlier when rounds are slow), taking the cheapest standing sheet that keeps the must-haves and beats
our alternative (the kit's closing move). Replaying the logged supplier replies (timestamped, each with
its standing sheet priced at C) gives the deal we would have closed at each cutoff - so every run shows
both its practice score and its expected final score.

    uv run python -m csee finalest [run_dir ...]      # default: the newest runs under <repo>/runs
"""

import json
import math
from datetime import datetime
from pathlib import Path

from arena_kit.cost import must_haves_ok, score

CUTOFFS = (390, 330, 270)  # 8 min - 90 s safety close; slower rounds close earlier (kit: slowest round + 15 s)


def _ts(s):
    return datetime.fromisoformat(s).timestamp()


def estimate(events, cutoffs=CUTOFFS):
    """{"final_390": score, ..., "elapsed_s": .., "rounds_by_390": ..} from one case's run-log events."""
    opened = next((e for e in events if e.get("type") == "case_opened"), None)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if not opened or not result or result.get("c_open") is None or result.get("c_best") is None:
        return {}
    case, t0 = opened["case"], _ts(opened["ts"])
    c_open, c_best = result["c_open"], result["c_best"]
    c_alt = result.get("c_alt") if result.get("c_alt") is not None else opened.get("c_alt")
    std = {sid: o.get("standard_terms") or {} for sid, o in (opened.get("opening") or {}).items()}
    t_end = _ts(result["ts"])
    replies = sorted((e for e in events if e.get("type") == "reply"), key=lambda e: _ts(e["ts"]))
    out = {"elapsed_s": round(t_end - t0, 1), "practice_score": result.get("score")}
    for cut in cutoffs:
        if t_end - t0 <= cut:  # the case was over before this cutoff: the real outcome stands
            out[f"final_{cut}"] = result.get("score")
            continue
        standing = {sid: (o.get("priced") or {}) for sid, o in (opened.get("opening") or {}).items()}
        rounds = 0
        for r in replies:
            if _ts(r["ts"]) - t0 > cut:
                break
            rounds += 1
            sid = r.get("supplier_id")
            if r.get("status") in ("walked_away", "no_bid"):
                standing.pop(sid, None)
            elif (r.get("standing") or {}).get("priced"):
                standing[sid] = r["standing"]["priced"]
        best = math.inf
        for sid, priced in standing.items():
            c = priced.get("c")
            if c is None or not must_haves_ok(case, priced.get("terms") or {}, std.get(sid)):
                continue
            best = min(best, c)
        if c_alt is not None and best >= c_alt:
            best = c_alt  # the closing move walks away: our alternative scores
        out[f"final_{cut}"] = round(score(c_open, best, c_best), 4) if best < math.inf else 0.0
        out[f"rounds_by_{cut}"] = rounds
    return out


def read_case(path):
    events = []
    for line in Path(path).read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def latest_case_file(run_dir, case_id):
    """The newest log of this case in a run folder (repeats are case_P01~2.jsonl, ...)."""
    name = case_id.replace(":", "_")
    files = sorted(Path(run_dir).glob(f"{name}*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


RUNS_ROOT = Path(__file__).resolve().parents[2] / "runs"


def for_case(agent, variant, case_id):
    """The final-mode estimate of this case from the newest run log of this agent/variant ({} if none)."""
    try:
        dirs = sorted((d for d in RUNS_ROOT.iterdir() if (d / "run.json").exists()), key=lambda d: d.stat().st_mtime)
        for d in reversed(dirs[-40:]):
            meta = json.loads((d / "run.json").read_text())
            if (meta.get("agent_name") or "base") == agent and (meta.get("variant") or "base") == variant:
                f = latest_case_file(d, case_id)
                if f:
                    return estimate(read_case(f))
    except Exception:  # an estimate is never worth a failed ledger row
        return {}
    return {}


def report(run_dirs):
    rows = []
    for d in run_dirs:
        meta = json.loads((Path(d) / "run.json").read_text()) if (Path(d) / "run.json").exists() else {}
        label = f"{meta.get('agent_name') or meta.get('agent', '?')}/{meta.get('variant', '?')}"
        for f in sorted(Path(d).glob("case_*.jsonl")):
            est = estimate(read_case(f))
            if est:
                rows.append((Path(d).name, label, f.stem, est))
    lines = [
        "| Run | Agent/variant | Case | Practice | Final est. 390 s | 330 s | 270 s | Elapsed | Rounds by 390 s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for run, label, case, e in rows:
        fmt = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
        lines.append(
            f"| {run} | {label} | {case} | {fmt(e.get('practice_score'))} | {fmt(e.get('final_390'))} | "
            f"{fmt(e.get('final_330'))} | {fmt(e.get('final_270'))} | {e['elapsed_s']:.0f} s | "
            f"{e.get('rounds_by_390', '-')} |"
        )
    return "\n".join(lines)
