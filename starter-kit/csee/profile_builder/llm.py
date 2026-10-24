"""One JSON-returning Claude call with cost accounting. Model from --model, else PROFILE_MODEL."""

import json
import os
import threading
import time

DEFAULT_MODEL = "claude-haiku-5-5"
# USD per million tokens (input, output), from the claude-api skill's model table (2026-10).
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-fable-5-1": (10.0, 50.0),
}


def model_from(arg=None):
    return arg or os.environ.get("PROFILE_MODEL") or DEFAULT_MODEL


class Ledger:
    """Thread-safe token and cost tally across parallel calls."""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls = []

    def add(self, label, model, usage, seconds):
        pin, pout = PRICES.get(model, (5.0, 25.0))
        tin = (usage.input_tokens or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * 1.25
        tin += (getattr(usage, "cache_read_input_tokens", 0) or 0) * 0.1
        cost = tin / 1e6 * pin + (usage.output_tokens or 0) / 1e6 * pout
        row = {
            "label": label,
            "model": model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "usd": round(cost, 5),
            "seconds": round(seconds, 1),
        }
        with self.lock:
            self.calls.append(row)
        return row

    @property
    def usd(self):
        return sum(c["usd"] for c in self.calls)


LEDGER = Ledger()
_client = None


def client():
    global _client
    if _client is None:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise SystemExit("ANTHROPIC_API_KEY is not set (starter-kit/.env is loaded automatically)")
        import anthropic

        _client = anthropic.Anthropic(timeout=300.0, max_retries=4)
    return _client


def call_json(system, user, schema, model, label="", effort=None, max_tokens=16000):
    """Strict JSON back: structured outputs (json_schema); if the API refuses the schema, plain JSON."""
    import anthropic

    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    oc = {"format": {"type": "json_schema", "schema": schema}}
    if effort:
        oc["effort"] = effort
    t0 = time.time()
    try:
        with client().messages.stream(**kwargs, output_config=oc) as stream:
            msg = stream.get_final_message()
    except anthropic.BadRequestError as e:  # schema feature not available: fall back to prompt-only JSON
        if "schema" not in str(e).lower() and "output_config" not in str(e).lower():
            raise
        kwargs["system"] = system + "\n\nReturn ONLY one JSON object matching this schema:\n" + json.dumps(schema)
        oc.pop("format")
        with client().messages.stream(**kwargs, **({"output_config": oc} if oc else {})) as stream:
            msg = stream.get_final_message()
    row = LEDGER.add(label, model, msg.usage, time.time() - t0)
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"{label}: model refused")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError(f"{label}: output truncated at max_tokens")
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    return json.loads(text), row
