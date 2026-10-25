"""Set up the ElevenLabs side of the voice copilot from `agent.json` (config as code).

    python3 dashboard/voice/provision.py            # create or update the agent (+ its client tools)
    python3 dashboard/voice/provision.py tts        # voice the offline demo (web/public/voice/demo.json -> mp3)
    python3 dashboard/voice/provision.py check      # signed URL round trip

Needs ELEVENLABS_API_KEY in the environment or starter-kit/.env. Writes the agent id to
dashboard/voice/.agent_id (git-ignored), which the dashboard server reads. Standard library only.
"""

import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ENV_FILE = REPO / "starter-kit" / ".env"
AGENT_ID_FILE = HERE / ".agent_id"
TOOLS_FILE = HERE / ".tool_ids.json"
DEMO = REPO / "dashboard" / "web" / "public" / "voice" / "demo.json"
API = "https://api.elevenlabs.io"


def key() -> str:
    k = os.environ.get("ELEVENLABS_API_KEY")
    if not k and ENV_FILE.is_file():
        for line in ENV_FILE.read_text().splitlines():
            name, sep, v = line.strip().partition("=")
            if sep and name.strip() == "ELEVENLABS_API_KEY":
                k = v.strip().strip('"').strip("'")
    if not k:
        sys.exit("ELEVENLABS_API_KEY missing (env or starter-kit/.env)")
    return k


def call(method: str, path: str, body=None, raw=False):
    req = urllib.request.Request(API + path, method=method,
                                 headers={"xi-api-key": key(), "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    for attempt in range(3):  # ElevenLabs sometimes drops the connection; retry those, not HTTP errors
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            break
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path} -> {e.code}: {e.read()[:800].decode(errors='replace')}") from None
        except (OSError, http.client.HTTPException):
            if attempt == 2:
                raise
            time.sleep(2)
    return data if raw else json.loads(data or b"{}")


def spec() -> dict:
    return json.loads((HERE / "agent.json").read_text())


def pick_voice(s: dict) -> str:
    v = s["voice"]
    try:
        voices = call("GET", "/v1/voices")["voices"]
    except RuntimeError as e:
        print(f"  voices list failed ({e}); using fallback voice")
        return v["fallback_voice_id"]
    for want in v["preferred"]:
        for x in voices:
            if x["name"].split(" ")[0].lower() == want.lower():
                print(f"  voice: {x['name']} ({x['voice_id']})")
                return x["voice_id"]
    return v["fallback_voice_id"]


def tool_config(t: dict) -> dict:
    return {
        "type": "client",
        "name": t["name"],
        "description": t["description"],
        "parameters": {"type": "object", "properties": t.get("parameters", {}), "required": t.get("required", [])},
        "expects_response": True,
        "response_timeout_secs": 20,
    }


def provision_tools(s: dict) -> list[str] | None:
    """Tools as workspace tools (tool_ids); None when the API refuses, then they go inline."""
    known = json.loads(TOOLS_FILE.read_text()) if TOOLS_FILE.is_file() else {}
    ids = {}
    try:
        for t in s["tools"]:
            body = {"tool_config": tool_config(t)}
            if t["name"] in known:
                try:
                    call("PATCH", f"/v1/convai/tools/{known[t['name']]}", body)
                    ids[t["name"]] = known[t["name"]]
                    continue
                except RuntimeError:
                    pass
            ids[t["name"]] = call("POST", "/v1/convai/tools", body)["id"]
    except RuntimeError as e:
        print(f"  tools API failed, falling back to inline tools: {e}")
        return None
    TOOLS_FILE.write_text(json.dumps(ids, indent=1))
    print(f"  tools: {', '.join(ids)}")
    return list(ids.values())


def agent_body(s: dict, voice_id: str, tool_ids: list[str] | None, model_id: str | None) -> dict:
    prompt = {"prompt": "\n".join(s["prompt"]), "llm": s["llm"], "temperature": 0.2}
    if tool_ids is None:
        prompt["tools"] = [tool_config(t) for t in s["tools"]]
    else:
        prompt["tool_ids"] = tool_ids
    v = s["voice"]
    tts = {"voice_id": voice_id, "stability": v["stability"], "speed": v["speed"], "similarity_boost": v.get("similarity_boost", 0.8)}
    if v.get("expressive_mode") and model_id == "eleven_v3_conversational":
        tts["expressive_mode"] = True
    if model_id:
        tts["model_id"] = model_id
    if v.get("text_normalisation_type"):
        tts["text_normalisation_type"] = v["text_normalisation_type"]
    return {
        "name": s["name"],
        "conversation_config": {
            "agent": {
                "first_message": s["first_message"],
                "language": "en",
                "dynamic_variables": {"dynamic_variable_placeholders": s["dynamic_variables"]},
                "prompt": prompt,
            },
            "tts": tts,
        },
        "platform_settings": {
            "overrides": {"conversation_config_override": {"agent": {"first_message": True, "prompt": {"prompt": True}}}},
        },
    }


def provision():
    s = spec()
    voice_id = pick_voice(s)
    tool_ids = provision_tools(s)
    agent_id = AGENT_ID_FILE.read_text().strip() if AGENT_ID_FILE.is_file() else None
    for model_id in (s["voice"].get("model_id"), None):
        body = agent_body(s, voice_id, tool_ids, model_id)
        try:
            if agent_id:
                call("PATCH", f"/v1/convai/agents/{agent_id}", body)
                print(f"updated agent {agent_id}")
            else:
                agent_id = call("POST", "/v1/convai/agents/create", body)["agent_id"]
                AGENT_ID_FILE.write_text(agent_id + "\n")
                print(f"created agent {agent_id} -> {AGENT_ID_FILE.relative_to(REPO)}")
            return
        except RuntimeError as e:
            if model_id and "model" in str(e).lower():
                print(f"  tts model {model_id} refused, retrying with the default: {e}")
                continue
            raise


def tts():
    """Voice every agent line of the offline demo with the agent's own voice."""
    s = spec()
    voice_id = pick_voice(s)
    demo = json.loads(DEMO.read_text())
    chars = 0
    for line in demo["lines"]:
        if line["role"] != "agent" or not line.get("audio"):
            continue
        out = DEMO.parent / Path(line["audio"]).name
        v = s["voice"]
        body = {"text": line["text"], "model_id": v.get("demo_model_id", "eleven_multilingual_v2"),
                "voice_settings": {"stability": max(0.5, v["stability"]), "similarity_boost": v.get("similarity_boost", 0.8),
                                   "style": v.get("style", 0)}}
        for attempt in range(3):  # the TTS endpoint sometimes drops long v3 requests
            try:
                audio = call("POST", f"/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128", body, raw=True)
                break
            except (RuntimeError, OSError) as e:
                if attempt == 2:
                    raise
                print(f"  retry {out.name}: {str(e)[:120]}")
        out.write_bytes(audio)
        chars += len(line["text"])
        print(f"  {out.name}: {len(audio) // 1024} KB")
    print(f"voiced {chars} characters")


def check():
    agent_id = AGENT_ID_FILE.read_text().strip()
    url = call("GET", f"/v1/convai/conversation/get-signed-url?agent_id={agent_id}")["signed_url"]
    print("signed url ok:", url.split("?")[0])


if __name__ == "__main__":
    {"tts": tts, "check": check}.get(sys.argv[1] if len(sys.argv) > 1 else "", provision)()
