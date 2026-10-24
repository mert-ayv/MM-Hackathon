"""Annika's agent. Starts identical to base: override any CseeAgent method (next_terms, sheets,
pick_claims, close, ...) to try another strategy. Only Annika edits this file.

    uv run python -m csee --agent annika sim    free, offline
    uv run python -m csee --agent annika bench  free, sandbox
"""

from ..agent import CseeAgent


class AnnikaAgent(CseeAgent):
    pass
