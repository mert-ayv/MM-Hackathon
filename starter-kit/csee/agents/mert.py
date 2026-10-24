"""Mert's agent. Starts identical to base: override any CseeAgent method (next_terms, sheets,
pick_claims, close, ...) to try another strategy. Only Mert edits this file.

    uv run python -m csee --agent mert sim      free, offline
    uv run python -m csee --agent mert bench    free, sandbox
"""

from ..agent import CseeAgent


class MertAgent(CseeAgent):
    pass
