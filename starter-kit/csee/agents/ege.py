"""Ege's agent. Starts identical to base: override any CseeAgent method (next_terms, sheets,
pick_claims, close, ...) to try another strategy. Only Ege edits this file.

    uv run python -m csee --agent ege sim       free, offline
    uv run python -m csee --agent ege bench     free, sandbox
"""

from ..agent import CseeAgent


class EgeAgent(CseeAgent):
    pass
