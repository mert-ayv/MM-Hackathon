"""Emre's agent. Starts identical to base: override any CseeAgent method (next_terms, sheets,
pick_claims, close, ...) to try another strategy. Only Emre edits this file.

    uv run python -m csee --agent emre sim      free, offline
    uv run python -m csee --agent emre bench    free, sandbox
"""

from ..agent import CseeAgent


class EmreAgent(CseeAgent):
    pass
