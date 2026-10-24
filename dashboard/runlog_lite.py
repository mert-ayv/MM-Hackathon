"""A minimal run-log writer (format: docs/run-log.md) for the dashboard's own tools: the fixture
generator, sim_log.py and import_sessions.py. Needs only `arena_kit.cost`; the agent's writer lives in
starter-kit/csee/runlog.py.
"""

import json
from datetime import datetime
from pathlib import Path

from arena_kit.cost import cost_breakdown

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "runs"


def now():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def priced(case, terms, standard=None, supplier=None):
    """A term sheet with its C and breakdown. Pass the supplier's standard terms, or C won't match the arena's."""
    try:
        breakdown = {k: round(v, 2) for k, v in cost_breakdown(case, terms or {}, standard, supplier).items()}
    except (ValueError, KeyError, TypeError, ZeroDivisionError):
        return {"terms": terms, "c": None, "breakdown": None}
    return {"terms": terms, "c": round(sum(breakdown.values()), 2), "breakdown": breakdown}


def write_run(folder: Path, meta: dict, cases: dict[str, list[dict]]):
    """Write run.json and one JSONL per case. `cases`: {key: [event dicts with ts and type]}; the key names
    the file (":" -> "_"; a repeat of a case in the same run is "case:D01~2"), an event's own `case_id`
    (default: the key) is the real case. Common fields and seq are filled in here."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "run.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    for key, events in cases.items():
        with (folder / f"{key.replace(':', '_')}.jsonl").open("w", encoding="utf-8") as f:
            for seq, ev in enumerate(events):
                line = {"ts": ev.pop("ts"), "seq": seq, "run_id": meta["run_id"], "agent": meta["agent"],
                        "case_id": ev.pop("case_id", key), "session_id": ev.pop("session_id", None), "type": ev.pop("type"), **ev}
                f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")


class Run:
    """Streaming writer for a live run (used by sim_log.py)."""

    def __init__(self, agent, set_, notes="", root=RUNS):
        self.agent = agent
        self.id = f"{datetime.now():%Y%m%d-%H%M%S}-{agent}"
        self.dir = Path(root) / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta = {"run_id": self.id, "agent": agent, "agent_version": None, "set": set_,
                     "started_at": now(), "ended_at": None, "cases": [], "notes": notes}
        self._write_meta()

    def _write_meta(self):
        (self.dir / "run.json").write_text(json.dumps(self.meta, indent=2, ensure_ascii=False))

    def case(self, case_id):
        if case_id not in self.meta["cases"]:
            self.meta["cases"].append(case_id)
            self._write_meta()
        return CaseLog(self, case_id)

    def end(self):
        self.meta["ended_at"] = now()
        self._write_meta()


class CaseLog:
    def __init__(self, run, case_id):
        self.run, self.case_id, self.session_id, self.seq = run, case_id, None, 0
        self.path = run.dir / f"{case_id.replace(':', '_')}.jsonl"

    def event(self, type_, **fields):
        line = {"ts": now(), "seq": self.seq, "run_id": self.run.id, "agent": self.run.agent,
                "case_id": self.case_id, "session_id": self.session_id, "type": type_, **fields}
        self.seq += 1
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
