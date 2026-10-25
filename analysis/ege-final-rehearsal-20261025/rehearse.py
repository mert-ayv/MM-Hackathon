import json
import logging
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
import uvicorn
from arena_kit.client import ArenaError
from arena_kit.sim import Sim, create_app, load_cases
from csee.__main__ import agent_factory, runtime_client
from csee.runner import play_waves

logging.basicConfig(level=logging.WARNING)
state = Sim(load_cases())
state.rehearse(wait=5, cap=90, brk=3)
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
server = uvicorn.Server(uvicorn.Config(create_app(state), host="127.0.0.1", port=port, log_level="error"))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
while not server.started:
    time.sleep(.05)
registration = runtime_client(base_url=f"http://127.0.0.1:{port}", api_key="local-only")
key = registration.register("frontier-rehearsal", "sim")["api_key"]
registration.http.close()
client = runtime_client(base_url=f"http://127.0.0.1:{port}", api_key=key)
try:
    try:
        client.cases("final")
        raise AssertionError("expected the pre-wave wait")
    except ArenaError as error:
        assert error.status == 403
    while time.time() < state.rehearsal[0] + .1:
        time.sleep(.1)
    first = client.cases("final")[0]["case_id"]
    opened = client.open_session(first)
    print("Local rehearsal: verified pre-wave wait; resuming an existing session.", flush=True)
    results = play_waves(client, agent_factory(False, agent="router"), waves=2, parallel=2, poll=.5)
    assert len(results) == len(state.final)
    assert all(isinstance(result, dict) and "deal" in result for result in results.values()), results
    assert all(client.session(result["session_id"])["status"] == "ended" for result in results.values())
    assert results[first]["session_id"] == opened["session_id"]
    report = {"local_only": True, "waves_closed": 2, "resumed_session": True,
              "deals": sum(bool(r.get("deal")) for r in results.values()),
              "cases": {cid: {k: r.get(k) for k in ("deal", "score")}
                                               for cid, r in results.items()}}
    Path("/private/tmp/mm-final-rehearsal-result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
finally:
    client.http.close()
    server.should_exit = True
    thread.join(timeout=5)
