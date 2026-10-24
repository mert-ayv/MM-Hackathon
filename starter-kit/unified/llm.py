"""The writer's model call, with prompt caching on Anthropic.

Same contract as the kit's `arena_kit.agents.llm.llm_from_env` (`complete(system, user) -> str`, same env
variables), plus: `user` may be a list of parts. Everything before the last part is a stable prefix
(e.g. the case and the supplier's profile, identical on every move of a thread) and gets a cache
breakpoint, so later moves read it at ~0.1x the input price. Prefixes under the model's minimum
(512 tokens on current models) simply don't cache - no error. Other providers get the parts joined.
"""

import os
import threading

from arena_kit.agents.llm import llm_from_env

USAGE = {"calls": 0, "input": 0, "cache_read": 0, "cache_write": 0, "output": 0}
_lock = threading.Lock()


def _count(usage):
    with _lock:
        USAGE["calls"] += 1
        USAGE["input"] += getattr(usage, "input_tokens", 0) or 0
        USAGE["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0
        USAGE["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        USAGE["output"] += getattr(usage, "output_tokens", 0) or 0


def complete_from_env():
    if os.environ.get("LLM_PROVIDER", "openai") != "anthropic":
        joined = llm_from_env()

        def complete(system, user):
            return joined(system, "\n".join(user) if isinstance(user, list) else user)

        complete.parts = True
        return complete

    import anthropic

    client, model = anthropic.Anthropic(timeout=45.0), os.environ["LLM_MODEL"]
    extra = {"output_config": {"effort": e}} if (e := os.environ.get("LLM_EFFORT")) else {}

    def complete(system, user):
        parts = user if isinstance(user, list) else [user]
        content = [{"type": "text", "text": p} for p in parts if p]
        if len(content) > 1:  # cache the stable prefix (system + all parts but the last)
            content[-2]["cache_control"] = {"type": "ephemeral"}
        r = client.messages.create(
            model=model, max_tokens=16000, system=system, messages=[{"role": "user", "content": content}], **extra
        )
        _count(r.usage)
        return "".join(b.text for b in r.content if b.type == "text")

    complete.parts = True
    return complete
