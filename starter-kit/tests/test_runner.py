"""Free runner tests: slow decisions don't serialise threads, the wave cap drops late messages, and the run
log is written in the docs/run-log.md shape. No arena calls, no quota, no LLM."""

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from arena_kit.client import ArenaError
from arena_kit.play import CLOSE_BEFORE_CAP_S, standing
from csee import agents, runlog
from csee.runner import play_case, refreshed_thread

SUPPLIERS = ["sup:1", "sup:2", "sup:3"]
CASES = Path(__file__).parents[1] / "csee" / "cases" / "practice.json"


def quote(sid, status="open"):
    return {
        "from": f"sales@{sid}",
        "status": status,
        "body": "Our quote.",
        "term_sheets": [{"term_sheet_id": f"offer:{sid}", "terms": {"unit_price": 10.0}}],
        "attachments": [],
    }


class FakeTable:
    """Three supplier threads; every reply is instant. Records when each message arrived."""

    def __init__(self):
        self.session_id, self.done, self.t0, self.sent, self.closed = "fake-1", None, None, [], None
        self._lock = threading.Lock()

    def open(self, case_id):
        self.t0 = time.monotonic()
        return {"case_id": case_id, "suppliers": SUPPLIERS}, {s: [quote(s)] for s in SUPPLIERS}

    def send(self, sid, msg):
        with self._lock:
            self.sent.append((sid, time.monotonic() - self.t0))
        return quote(sid, "final_offer")

    def close(self, sid, msg):
        self.closed = (sid, msg, time.monotonic() - self.t0)
        return {"deal": True, "supplier_id": sid, "score": 1.0}

    def attachment(self, attachment_id):
        return b""

    def missed(self, sid, error):
        return quote(sid)

    def result(self):
        return {"deal": False}


class SlowAgent:
    """Its first move per thread takes `delay` seconds (an LLM writing), then it is ready."""

    def __init__(self, delay=2.0):
        self.delay, self.threads = delay, {}

    def prepare(self, case, threads):
        self.threads = {s: SimpleNamespace(ready=False) for s in threads}

    def thread_move(self, case, threads, sid):
        if any(m.get("from") == "buyer" for m in threads[sid]):
            self.threads[sid].ready = True
            return None
        time.sleep(self.delay)
        return {"subject": "Re", "body": "Our offer.", "term_sheets": [{"terms": {"unit_price": 9.0}}], "refs": []}

    def close(self, case, threads, force=False):
        return {"supplier_id": SUPPLIERS[0], "message": {"action": {"type": "accept", "term_sheet_id": "offer:sup:1"}}}


def test_slow_decisions_run_in_parallel():
    table = FakeTable()
    out = play_case(table, "case:T", SlowAgent(2.0))
    assert out["deal"]
    assert sorted(s for s, _ in table.sent) == SUPPLIERS
    first_round = max(t for _, t in table.sent)
    # three 2-second decisions side by side: ~2 s; serialised under one lock it would be ~6 s
    assert 1.9 <= first_round < 3.5, table.sent


def test_wave_cap_drops_messages_decided_too_late():
    table = FakeTable()
    deadline = time.time() + CLOSE_BEFORE_CAP_S + 0.6  # the cap is near after 0.6 s; decisions take 2 s
    out = play_case(table, "case:T", SlowAgent(2.0), deadline=deadline)
    assert out["deal"] and table.closed is not None
    assert table.closed[2] < 1.9  # closed without waiting for the slow decisions
    time.sleep(2.2)  # the workers finish deciding after the close ...
    assert table.sent == []  # ... and drop their messages


@pytest.mark.skipif(not CASES.exists(), reason="no case files")
def test_run_log_on_local_sim(tmp_path):
    from csee import localsim

    case = next(c for c in json.loads(CASES.read_text()) if len(c["suppliers"]) > 1)  # an RFQ
    run = runlog.Run("base", "sim", root=tmp_path)
    out = play_case(localsim.LocalTable(case, None, 0), case["case_id"], agents.get("base")(), run=run)
    run.end()
    meta = json.loads((run.dir / "run.json").read_text())
    assert meta["run_id"] == run.id and run.id.endswith("-base-sim") and meta["ended_at"]
    assert meta["cases"] == [case["case_id"]]
    events = [json.loads(line) for line in (run.dir / f"{case['case_id'].replace(':', '_')}.jsonl").open()]
    assert [e["seq"] for e in events] == list(range(len(events)))
    types = [e["type"] for e in events]
    assert types[0] == "case_opened" and types[-1] == "result"
    assert {"plan", "decision", "message_sent", "reply"} <= set(types)
    opened = events[0]
    assert set(opened["opening"]) == set(case["suppliers"])
    assert all(o["priced"]["c"] for o in opened["opening"].values())
    sent = [e for e in events if e["type"] == "message_sent"]
    assert all(e["round"] >= 1 and e["sheets"][0]["breakdown"] for e in sent)
    assert all([c["id"] for c in e["claims"]] == e["refs"] for e in sent)  # refs only: claims as indexed
    kinds = [e["kind"] for e in events if e["type"] == "decision"]
    assert "send" in kinds
    assert sum(k in ("accept", "walk_away") for k in kinds) == 1  # the real close only, not the idle probes
    assert events[-1]["score"] == out["score"]
    # the same case again in this run gets its own file
    play_case(localsim.LocalTable(case, None, 1), case["case_id"], agents.get("base")(), run=run)
    assert (run.dir / f"{case['case_id'].replace(':', '_')}~2.jsonl").exists()


def test_no_run_log_by_default_for_agents():
    agent = agents.get("base")()
    assert agent.log is runlog.NULL and not agent.log.enabled
    agent.log.event("decision", kind="send")  # a no-op, never raises


def test_router_passes_log_and_cap_to_the_routed_agent():
    from csee.agents.router import RouterAgent

    case = json.loads(CASES.read_text())[0]
    router = RouterAgent()
    clog = SimpleNamespace(enabled=False, event=lambda *a, **k: None)
    router.log = clog  # the runner: before prepare
    router.prepare(case, {s: [] for s in case["suppliers"]})
    router.cap_at = lambda: 123.0  # the runner: after prepare
    assert router.inner.log is clog and router.inner.cap_at() == 123.0


def test_idle_close_counts_model_decision_time_in_the_reply_deadline(monkeypatch):
    from csee import runner

    monkeypatch.setattr(runner, "IDLE_CLOSE_S", 1)
    released = threading.Event()

    class WaitingAgent(SlowAgent):
        def thread_move(self, case, threads, sid):
            if sid == SUPPLIERS[0]:
                time.sleep(1.2)  # Most of the reply deadline was spent deciding to stop.
            else:
                released.wait(4)
            self.threads[sid].ready = True
            return None

    class WaitingTable(FakeTable):
        def close(self, sid, msg):
            out = super().close(sid, msg)
            released.set()
            return out

    table = WaitingTable()
    try:
        assert play_case(table, "case:T", WaitingAgent())["deal"]
        assert table.closed[2] < 2.2  # Old code added another idle interval: >= 2.5 s.
    finally:
        released.set()


@pytest.mark.parametrize("status", [409, 422])
def test_close_retry_uses_timeout_offer_terms_even_when_message_history_is_old(status):
    class ReadyAgent(SlowAgent):
        def thread_move(self, case, threads, sid):
            self.threads[sid].ready = True
            return None

        def close(self, case, threads, force=False):
            sid = SUPPLIERS[0]
            offer_id, terms = standing(threads[sid])
            if offer_id == "offer:new-timeout":
                assert terms["unit_price"] == 11  # A timeout can change the actual package too.
            return {"supplier_id": sid, "message": {"action": {"type": "accept", "term_sheet_id": offer_id}}}

    class RetryingTable(FakeTable):
        def __init__(self):
            super().__init__()
            self.client, self.attempts = self, []

        def close(self, sid, msg):
            self.attempts.append(msg["action"]["term_sheet_id"])
            if len(self.attempts) == 1:
                raise ArenaError(status, "offer expired")
            assert self.attempts[-1] == "offer:new-timeout"
            return {"deal": True}

        def session(self, session_id):
            return {"status": "open", "threads": {s: {} for s in SUPPLIERS}}

        def thread(self, session_id, sid):
            old = quote(sid)
            current = "offer:new-timeout" if sid == SUPPLIERS[0] else old["term_sheets"][0]["term_sheet_id"]
            return {
                "messages": [old],
                "offer_id": current,
                "status": "open",
                "timeouts": [{"offer_id": current, "terms": {"unit_price": 11}}],
            }

    table = RetryingTable()
    assert play_case(table, "case:T", ReadyAgent())["deal"]
    assert len(table.attempts) == 2


def test_close_falls_back_to_the_threads_own_offer_after_two_refusals():
    """P05, Sat 20:42 (both A/B runs): refused twice as "not a standing offer", closed at retry 2 on the
    thread's own offer_id. The re-read alone cannot surface it when no timeout entry carries its terms."""

    class ReadyAgent(SlowAgent):
        def thread_move(self, case, threads, sid):
            self.threads[sid].ready = True
            return None

        def close(self, case, threads, force=False):
            sid = SUPPLIERS[0]
            return {"supplier_id": sid, "message": {"action": {"type": "accept", "term_sheet_id": f"offer:{sid}"}}}

    class StaleTable(FakeTable):
        def __init__(self):
            super().__init__()
            self.client, self.attempts = self, []

        def close(self, sid, msg):
            self.attempts.append(msg["action"]["term_sheet_id"])
            if self.attempts[-1] != "offer:current":
                raise ArenaError(409, "not a standing offer in this session")
            return {"deal": True}

        def session(self, session_id):
            return {"status": "open", "threads": {s: {} for s in SUPPLIERS}}

        def thread(self, session_id, sid):
            return {"messages": [quote(sid)], "offer_id": "offer:current", "status": "open"}

    table = StaleTable()
    assert play_case(table, "case:T", ReadyAgent())["deal"]
    assert table.attempts == ["offer:sup:1", "offer:sup:1", "offer:current"]


def test_refresh_never_attaches_a_new_offer_id_to_unconfirmed_old_terms():
    old = quote(SUPPLIERS[0])
    events = refreshed_thread({"offer_id": "offer:new-without-terms", "status": "open"}, [old])
    assert standing(events) == (None, {})
