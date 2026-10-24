"""Team agents: one file per person, so four strategies grow side by side on main without conflicts.

Every agent plays through the same runner, ledger and board, so their scores compare directly.
Subclassing `CseeAgent` and overriding only what you change gives you all of the contract below.

Run one with `--agent NAME` (e.g. `uv run python -m csee --agent ege sim`). `router` plays each
case with the agent that owns its case type (`agents/router.py`, ROUTES), meant for the final.

The runner's contract (`runner.play_case`), in call order:

1. `agent.log = <runlog.CaseLog or runlog.NULL>` - set by the runner before `prepare` (the router passes it
   on to the agent it routes to). API: `self.log.event(type, **fields)` (never raises) and
   `self.log.enabled` (False with --no-runlog and in tests: skip building expensive fields). Event types
   and fields: `docs/run-log.md`. `CseeAgent` emits `plan` (before each send) and `decision` (`send` /
   `wait` per thread move) through `note_plan` / `note_decision`. Logging observes; it must never change
   a decision.
2. `prepare(case, threads)` - once, single-threaded, before any worker starts. Then the runner sets
   `agent.cap_at` (Live Final: a function returning when the safety close happens; else None).
3. `thread_move(case, threads, sid) -> message | None` - one worker per supplier calls it, so calls for
   DIFFERENT suppliers run concurrently, and never two at once for the same `sid`. It runs WITHOUT the
   runner's lock, so it may be slow (LLM strategy or writer calls, 10-30 s) without stalling other threads.
   - `threads` is a snapshot: a fresh dict of list copies, taken under the lock just before the call.
     Read it freely (including other suppliers' e-mails, e.g. for `leader_cost`); don't mutate it - the
     runner appends the sent message and the reply to its own copy.
   - Mutate freely: `self.threads[sid]` (this supplier's own `ThreadState`).
   - Read only: other suppliers' `self.threads[s]` (their worker may be updating it).
   - Anything shared across suppliers that you check-and-update (e.g. `self.used_ids`, so two threads never
     cite the same data ID; a cross-thread cache) only inside `with self.shared_lock:` (an RLock made in
     `CseeAgent.__init__`; call `super().__init__`). Keep that block short: never an LLM or network call in it.
   - Optional `msg["_write"]`: a no-argument function returning the e-mail body. The runner pops it and
     calls it with a time budget (`runner.WRITE_BUDGET_S`), keeping `msg["body"]` (the template) if it is
     slow or fails. Use it for the model's wording so a hung model can't make the reply late.
   - Return None to stop writing to this supplier; set `self.threads[sid].ready = True` then.
   - If the case is closing when the decision returns (wave cap near, or another thread ended the case),
     the runner drops the message.
4. `close(case, threads, force) -> {"supplier_id", "message": {"action": accept | walk_away}}` - called
   UNDER the runner's lock with the live `threads`: as a probe while workers still run (is an idle thread
   holding the best deal?), and for the real close when every thread is ready, an idle thread holds the
   best deal, or the wave's cap is near (`max(CLOSE_BEFORE_CAP_S, slowest round + ROUND_MARGIN_S)` before
   it). It may run while other threads' `thread_move` calls are in flight: keep it fast and read-only
   (no logging; set `self.close_reason` to a short string - the runner logs the real close as a
   `decision` with that reason). Workers still deciding at the real close are not waited for.
5. `self.threads[sid].ready` and `self.threads[sid].round_s` - the runner reads the first and sets it True
   when a thread's worker fails; it appends each round's seconds (our move + the reply) to the second.
"""

from ..agent import CseeAgent
from .annika import AnnikaAgent
from .ege import EgeAgent
from .emre import EmreAgent
from .mert import (
    AnchorCapAgent,
    FinalCandidateAgent,
    GatedPushAgent,
    MertAgent,
    MertAnchorAgent,
    MertClauseAgent,
    MertConsistentAgent,
    MertDialogueAgent,
    MertHedgeAgent,
    MertHedgeLateAgent,
    MertLeverAgent,
    MertLeverRawAgent,
    MertRawAgent,
)
from .router import RouterAgent

AGENTS = {
    "base": CseeAgent,
    "annika": AnnikaAgent,
    "ege": EgeAgent,
    "emre": EmreAgent,
    "mert": MertAgent,
    "mert-dialogue": MertDialogueAgent,
    "mert-anchor": MertAnchorAgent,
    "mert-consistent": MertConsistentAgent,
    "mert-clause": MertClauseAgent,
    "mert-raw": MertRawAgent,
    "mert-hedge": MertHedgeAgent,
    "mert-hedge-late": MertHedgeLateAgent,
    "mert-lever": MertLeverAgent,
    "mert-lever-raw": MertLeverRawAgent,
    "mert-anchorcap": AnchorCapAgent,
    "mert-gatedpush": GatedPushAgent,  # rejected: P18 afada094 walked after a push inside the gate
    "mert-final": FinalCandidateAgent,
    "router": RouterAgent,
}


def get(name):
    if name not in AGENTS:
        raise SystemExit(f"unknown agent {name!r}; known: {', '.join(AGENTS)}")
    return AGENTS[name]
