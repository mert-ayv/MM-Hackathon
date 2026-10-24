"""Team agents: one file per person, so four strategies grow side by side on main without conflicts.

Every agent plays through the same runner, ledger and board, so their scores compare directly.
It must offer what `runner.play_case` calls: `prepare(case, threads)`, `thread_move(case, threads,
sid)` -> message or None, `close(case, threads, force)` -> accept/walk, and `threads[sid].ready`.
Subclassing `CseeAgent` and overriding only what you change gives you all of that.

Run one with `--agent NAME` (e.g. `uv run python -m csee --agent ege sim`); `base` is the champion
that runs in the final unless we pick another.
"""

from ..agent import CseeAgent
from .annika import AnnikaAgent
from .ege import EgeAgent
from .emre import EmreAgent
from .mert import MertAgent

AGENTS = {
    "base": CseeAgent,
    "annika": AnnikaAgent,
    "ege": EgeAgent,
    "emre": EmreAgent,
    "mert": MertAgent,
}


def get(name):
    if name not in AGENTS:
        raise SystemExit(f"unknown agent {name!r}; known: {', '.join(AGENTS)}")
    return AGENTS[name]
