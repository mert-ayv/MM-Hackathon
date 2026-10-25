"""Voice copilot ("Ask the negotiator"): the ElevenLabs side, server only.

The browser never sees the API key: it asks this router for a signed conversation URL and runs the
agent's client tools itself (the run logs are local, ElevenLabs' cloud can't reach them). Without a key
the routes answer `configured: false` and the dashboard plays its offline demo instead.

Key and agent id come from the environment or `starter-kit/.env`: ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID
(or `dashboard/voice/.agent_id`, written by `dashboard/voice/provision.py`).
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ENV_FILE = REPO / "starter-kit" / ".env"
AGENT_ID_FILE = REPO / "dashboard" / "voice" / ".agent_id"
API = "https://api.elevenlabs.io"


def _dotenv(path: Path) -> dict[str, str]:
    out = {}
    try:
        for line in path.read_text().splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and not k.startswith("#"):
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def settings() -> tuple[str | None, str | None]:
    """(api key, agent id), read fresh each call so a key added while the server runs is picked up."""
    env = _dotenv(ENV_FILE)
    key = os.environ.get("ELEVENLABS_API_KEY") or env.get("ELEVENLABS_API_KEY") or None
    agent = os.environ.get("ELEVENLABS_AGENT_ID") or env.get("ELEVENLABS_AGENT_ID") or None
    if not agent and AGENT_ID_FILE.is_file():
        agent = AGENT_ID_FILE.read_text().strip() or None
    return key, agent


def call(method: str, path: str, key: str, body: dict | None = None, timeout: float = 15) -> dict:
    req = urllib.request.Request(API + path, method=method, headers={"xi-api-key": key, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


router = APIRouter(prefix="/api/voice")


@router.get("/status")
def status():
    key, agent = settings()
    return {"configured": bool(key and agent), "has_key": bool(key), "agent_id": agent}


@router.get("/session")
def session():
    key, agent = settings()
    if not (key and agent):
        raise HTTPException(503, "voice not configured: add ELEVENLABS_API_KEY to starter-kit/.env and run "
                                 "dashboard/voice/provision.py")
    q = urllib.parse.urlencode({"agent_id": agent})
    try:
        data = call("GET", f"/v1/convai/conversation/get-signed-url?{q}", key)
    except urllib.error.HTTPError as e:
        raise HTTPException(502, f"ElevenLabs {e.code}: {e.read()[:300].decode(errors='replace')}") from None
    except OSError as e:
        raise HTTPException(502, f"ElevenLabs unreachable: {e}") from None
    return {"signed_url": data["signed_url"], "agent_id": agent}
