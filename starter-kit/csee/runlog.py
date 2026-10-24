"""The run log: one folder per run, one JSONL file per case session. Format: `docs/run-log.md` (the dashboard
reads it). Ported from `feat/shared-core:agent/hollerau/runlog.py`.

    run = Run("base", "sim")            # runs/<YYYYMMDD-HHMMSS>-base-sim/run.json
    clog = run.case("case:P01")         # runs/.../case_P01.jsonl
    clog.event("reply", supplier_id=..., status=...)
    run.end()

Agents get a `CaseLog` (or `NULL`, same API, does nothing) as `agent.log`. Logging never raises: a full disk
or an odd value must not break a negotiation. Check `log.enabled` before building expensive fields.
"""

import json
import logging
import os
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from arena_kit.cost import cost_breakdown

RUNS = Path(os.environ.get("CSEE_RUNS") or Path(__file__).resolve().parents[2] / "runs")
# the IDs the arena checks in a message (as arena_kit.sim.ID_RE): refs first, then IDs in the body
ID_RE = re.compile(r"\b(?:idx|quote|offer|sc|qn|po|cost|fc|news|doc|ctr):[\w.:@#/-]*\w")

_log = logging.getLogger("csee")


def now():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def git_sha():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=Path(__file__).parent
        )
        return out.stdout.strip() or None
    except OSError:
        return None


def priced(case, terms, standard=None, supplier=None):
    """A term sheet with its C and breakdown, as the log stores it."""
    try:
        breakdown = {k: round(v, 2) for k, v in cost_breakdown(case, terms, standard, supplier).items()}
    except (ValueError, KeyError, TypeError, ZeroDivisionError):
        return {"terms": terms, "c": None, "breakdown": None}
    return {"terms": terms, "c": round(sum(breakdown.values()), 2), "breakdown": breakdown}


def finite(x):
    """JSON has no infinity: inf/nan -> None."""
    return x if isinstance(x, int | float) and x == x and abs(x) != float("inf") else None


def message_claims(message):
    """[{"id", "text"}] in the order the arena indexes a message's data IDs (refs, then IDs in the body);
    text = the line of the body that cites the ID."""
    body = message.get("body") or ""
    ids = list(dict.fromkeys(list(message.get("refs") or []) + ID_RE.findall(body)))
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    return [{"id": i, "text": next((ln for ln in lines if i in ln), None)} for i in ids]


class Run:
    def __init__(self, agent, set_, notes="", root=None, **meta):
        self.agent = agent
        root = Path(root or RUNS)
        stamp = f"{datetime.now():%Y%m%d-%H%M%S}-{agent}-{set_}"
        self.id, n = stamp, 1
        while (root / self.id).exists():  # two runs in the same second
            n += 1
            self.id = f"{stamp}-{n}"
        self.dir = root / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta = {
            "run_id": self.id,
            "agent": agent,
            "agent_version": git_sha(),
            "set": set_,
            "started_at": now(),
            "ended_at": None,
            "cases": [],
            "notes": notes,
            **meta,
        }
        self._lock = threading.Lock()
        self._files = set()
        self._write_meta()

    def _write_meta(self):
        try:
            (self.dir / "run.json").write_text(json.dumps(self.meta, indent=2, ensure_ascii=False, default=str))
        except OSError as e:
            _log.warning("run log: %s", e)

    def case(self, case_id):
        """A log for one case session. The same case played again in this run (sim seeds, bench repeats)
        gets its own file: case_P01.jsonl, case_P01~2.jsonl, ... (the dashboard's convention)"""
        with self._lock:
            name, n = case_id.replace(":", "_"), 1
            while name in self._files:
                n += 1
                name = f"{case_id.replace(':', '_')}~{n}"
            self._files.add(name)
            if case_id not in self.meta["cases"]:
                self.meta["cases"].append(case_id)
                self._write_meta()
        return CaseLog(self, case_id, self.dir / f"{name}.jsonl")

    def end(self):
        self.meta["ended_at"] = now()
        self._write_meta()


class CaseLog:
    enabled = True

    def __init__(self, run, case_id, path):
        self.run, self.case_id, self.session_id, self.seq, self.path = run, case_id, None, 0, path
        self._lock = threading.Lock()  # RFQ threads log from several threads at once

    def event(self, type_, **fields):
        try:
            with self._lock:
                line = {
                    "ts": now(),
                    "seq": self.seq,
                    "run_id": self.run.id,
                    "agent": self.run.agent,
                    "case_id": self.case_id,
                    "session_id": self.session_id,
                    "type": type_,
                    **fields,
                }
                text = json.dumps(line, ensure_ascii=False, default=str)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(text + "\n")
                self.seq += 1
        except Exception as e:  # never break a negotiation
            _log.warning("run log %s: %s", type_, e)


class NullLog:
    """`CaseLog`'s API, doing nothing: the default `agent.log` and the runner's log with --no-runlog."""

    enabled = False
    session_id = None

    def event(self, type_, **fields):
        pass


NULL = NullLog()
