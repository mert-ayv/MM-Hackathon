"""Play cases with the csee agent: every supplier thread of a case in parallel.

The 60-second clock runs per thread from the supplier's reply. The kit's `play()` answers threads one
after another, so in an RFQ a second supplier's clock runs while we wait for the first one's reply
(up to a minute) - a timeout. Here each thread has its own worker that answers as soon as its supplier
has replied; one coordinator closes the case when every thread is ready, or before a wave's cap.

Concurrency: the shared `lock` guards `threads` (the e-mails) and is held only to check, snapshot and
apply. A worker's decision (`agent.thread_move`, which may call an LLM for 10-30 s) and the model's
wording (`msg["_write"]`, within WRITE_BUDGET_S) run outside it on a snapshot of `threads`, so a slow
decision in one thread never holds up the others. `agent.close` runs under the lock. The contract for
agent authors is in `csee/agents/__init__.py`.

Every event of a case goes to the run log (`csee/runlog.py`, `docs/run-log.md`) when a `run` is given.
"""

import functools
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from arena_kit.client import ArenaError
from arena_kit.cost import must_haves_ok
from arena_kit.docs import standard_terms
from arena_kit.play import (
    CLOSE_BEFORE_CAP_S,
    MOVE_LIMIT_S,
    ROUND_MARGIN_S,
    RemoteTable,
    closing_move,
    fetch_documents,
    quota_used_up,
)

from . import levers, runlog
from .agent import live_threads

log = logging.getLogger("csee")


def snapshot(threads):
    """A private copy for a decision outside the lock: a new dict of new lists. Messages are never
    changed once they are in `threads` (attachments are read before they go in), so lists of the
    same message dicts are enough."""
    return {s: list(ev) for s, ev in threads.items()}


def play_case(table, case_id, agent, deadline=None, run=None):
    """Play one case to its end. `deadline`: a Live Final wave's cap (time.time(), or a function returning
    it). `run`: a `runlog.Run` to log every event of this case to (None: no log)."""
    clog = run.case(case_id) if run else runlog.NULL
    try:
        return _play_case(table, case_id, agent, deadline, clog)
    except Exception as e:
        _quiet(clog.event, "error", supplier_id=None, status=getattr(e, "status", None), detail=repr(e))
        raise


def _quiet(fn, *args, **kwargs):
    """Logging must never break or stop a negotiation."""
    try:
        fn(*args, **kwargs)
    except Exception as e:
        log.warning("run log: %s", e)


def _play_case(table, case_id, agent, deadline, clog):
    case, threads = table.open(case_id)
    clog.session_id = table.session_id
    if getattr(table, "done", None):  # resumed a case that had already ended
        if clog.enabled:
            _quiet(log_result, clog, table, case, threads, table.done, None, None, resumed=True)
        return table.done
    for events in threads.values():
        for m in events:
            fetch_documents(table, m)
    agent.log = clog
    try:
        agent.prepare(case, threads)
        prepared = True
    except Exception:  # never leave a session open: no negotiation, but a safe close (kit's closing move)
        log.exception("%s: prepare failed - closing safely", case_id)
        prepared = False
    if clog.enabled:
        _quiet(log_opened, clog, case, threads, agent)
    lock, ended, closing, result = threading.Lock(), threading.Event(), threading.Event(), {}
    slowest = [0.0]  # the longest round so far, any thread: decision + the supplier's reply

    def margin():  # close this long before the cap, as the kit: longer if rounds are slow
        return max(CLOSE_BEFORE_CAP_S, slowest[0] + ROUND_MARGIN_S)

    def near_cap():
        cap = deadline() if callable(deadline) else deadline
        return bool(cap) and time.time() > cap - margin()

    # when the safety close happens, for a time-aware concession pace (practice and sandbox: none)
    agent.cap_at = (lambda: (deadline() if callable(deadline) else deadline) - margin()) if deadline else None

    def stop():
        return ended.is_set() or closing.is_set() or near_cap()

    def worker(sid):
        while not ended.is_set():
            with lock:  # check and snapshot only
                if sid not in live_threads(threads) or stop():
                    return
                view = snapshot(threads)
            t0 = time.monotonic()
            msg = agent.thread_move(case, view, sid)  # slow (LLM): outside the lock
            took = time.monotonic() - t0
            if took > MOVE_LIMIT_S * 0.75:
                log.warning("%s %s: decision took %.0fs", case_id, sid, took)
            if msg is None:
                return
            write = msg.pop("_write", None)
            if write:  # the model's wording, within its budget; the template body otherwise
                msg["body"] = timed_write(write, msg["body"], case_id, sid)
            with lock:
                if stop():  # the coordinator is closing the case: this message is too late
                    log.info("%s %s: closing - message dropped", case_id, sid)
                    return
                n_sent = sum(m.get("from") == "buyer" for m in threads[sid])
            if clog.enabled:
                _quiet(log_sent, clog, case, view, agent, sid, msg, n_sent + 1)
            t_send = time.monotonic()
            try:
                reply = table.send(sid, msg)
            except ArenaError as e:
                _quiet(clog.event, "error", supplier_id=sid, status=e.status, detail=e.detail)
                if e.status != 409:
                    log.error("%s %s: %s %s", case_id, sid, e.status, e.detail)
                    agent.threads[sid].ready = True
                    return
                reply = table.missed(sid, e)
            latency = time.monotonic() - t_send
            if "result" in reply:
                result.update(reply["result"])
                ended.set()
                return
            fetch_documents(table, reply)
            with lock:
                threads[sid] += [{**msg, "from": "buyer"}, reply]
                took = time.monotonic() - t0  # our move + its reply
                slowest[0] = max(slowest[0], took)
                agent.threads[sid].round_s.append(took)
                events = list(threads[sid])
            if clog.enabled:
                _quiet(log_reply, clog, case, events, agent, sid, reply, n_sent + 1, latency)
            log.info(
                "%s %s %s %s", case_id, sid, reply.get("status"), (reply.get("term_sheets") or [{}])[0].get("terms")
            )

    def safe(sid):
        try:
            worker(sid)
        except Exception as e:  # one broken thread must not stop the case
            log.exception("%s %s: worker failed", case_id, sid)
            _quiet(clog.event, "error", supplier_id=sid, status=None, detail=repr(e))
            try:
                agent.threads[sid].ready = True
            except Exception:
                pass

    sids = live_threads(threads) if prepared else []
    workers = {sid: threading.Thread(target=safe, args=(sid,), daemon=True) for sid in sids}
    for w in workers.values():
        w.start()
    idle_since = {}  # thread -> when its worker stopped (its last supplier reply)
    while any(w.is_alive() for w in workers.values()) and not ended.is_set() and not near_cap():
        time.sleep(0.5)
        now = time.monotonic()
        for sid, w in workers.items():
            if not w.is_alive():
                idle_since.setdefault(sid, now)
        # A finished thread's 60 s clock keeps running while others negotiate: after IDLE_CLOSE_S the arena
        # re-issues its offer (P05: a stale accept), three such timeouts end the thread. If the thread that
        # waits holds our best deal, close now rather than risk it.
        waiting = [sid for sid, t in idle_since.items() if now - t > IDLE_CLOSE_S]
        if waiting:
            with lock:
                try:
                    best = agent.close(case, threads, force=True)
                except Exception:
                    best = None
            if best and best["supplier_id"] in waiting and best["message"]["action"]["type"] == "accept":
                log.info(
                    "%s: %s waited %ss holding the best deal - closing now", case_id, best["supplier_id"], IDLE_CLOSE_S
                )
                break
    if result:
        out = {**result, "session_id": table.session_id}
        if clog.enabled:
            with lock:
                view = snapshot(threads)
            _quiet(log_result, clog, table, case, view, out, None, None)
        return out
    t_close = time.monotonic()
    with lock:
        closing.set()  # a worker still deciding drops its message
        try:
            decision = agent.close(case, threads, force=True)
            reason = getattr(agent, "close_reason", "") or "agent.close"
        except Exception as e:
            log.exception("%s: agent.close failed - kit closing move", case_id)
            _quiet(clog.event, "error", supplier_id=None, status=None, detail=f"agent.close failed: {e!r}")
            decision, reason = closing_move(case, threads), "kit closing_move (agent.close failed)"
    out = None
    for attempt in range(3):
        sid, msg = decision["supplier_id"], decision["message"]
        log.info("%s: closing %s %s", case_id, sid, msg["action"])
        if clog.enabled:
            _quiet(log_close, clog, threads, sid, msg["action"], reason, t_close, attempt, near_cap())
        try:
            out = table.close(sid, msg)
            break
        except ArenaError as e:
            # e.g. a stale sheet after a late supplier reply: re-read the threads, decide again
            log.warning("%s: close failed (%s %s), attempt %d", case_id, e.status, e.detail, attempt + 1)
            _quiet(clog.event, "error", supplier_id=sid, status=e.status, detail=e.detail)
            if e.status not in (409, 422) or not hasattr(table, "client"):
                break
            try:
                state = table.client.session(table.session_id)
                if state.get("status") == "ended":
                    break
                for s in state.get("threads") or {}:
                    threads[s] = table.client.thread(table.session_id, s).get("messages", threads[s])
                    for m in threads[s]:
                        fetch_documents(table, m)
                decision = agent.close(case, threads, force=True)
                reason = (getattr(agent, "close_reason", "") or "agent.close") + " (threads re-read)"
                if attempt >= 1:  # still refused: the thread's own standing offer, nothing clever
                    t = table.client.thread(table.session_id, decision["supplier_id"])
                    if t.get("offer_id") and decision["message"]["action"]["type"] == "accept":
                        decision["message"]["action"]["term_sheet_id"] = t["offer_id"]
                        reason += "; its thread's standing offer"
            except Exception:
                log.exception("%s: re-reading the threads failed", case_id)
                break
        except Exception as e:  # a dropped connection: the same decision again (the client reuses its move id)
            log.warning("%s: close transport error %r, attempt %d", case_id, e, attempt + 1)
            time.sleep(1.0)
    if out is None and hasattr(table, "client"):
        # still open after the retries (an open session scores like a walk-away at the wave cap): the kit's
        # closing move, then a plain walk-away
        for last in ("kit closing_move", "walk_away"):
            try:
                if table.client.session(table.session_id).get("status") == "ended":
                    break
                d = closing_move(case, threads) if last == "kit closing_move" else {
                    "supplier_id": sid, "message": {"action": {"type": "walk_away"}}}
                log.warning("%s: last resort %s", case_id, last)
                out = table.close(d["supplier_id"], d["message"])
                break
            except Exception as e:
                log.warning("%s: last resort %s failed: %r", case_id, last, e)
    if out is None:
        try:
            out = table.result()
        except Exception:
            log.exception("%s: reading the result failed", case_id)
            out = {"deal": False, "end_reason": "unknown"}
    out = {**out, "session_id": table.session_id}
    if clog.enabled:
        _quiet(log_result, clog, table, case, threads, out, msg["action"], sid)
    return out


# a case whose play failed (open 429 while sessions are still closing, network) is retried while its wave runs:
# 2 retries were ~6 s of polling - a 30 s network blip lost the case (an open session scores no deal at the cap)
MAX_RETRIES = 40
IDLE_CLOSE_S = 40  # a ready thread holding the best deal must not wait out its 60 s clock
WRITE_BUDGET_S = 15  # the model's share of our 60 s per message; the template is the fallback
_writers = ThreadPoolExecutor(max_workers=16, thread_name_prefix="writer")


def timed_write(write, draft, case_id, sid):
    """The model's wording within WRITE_BUDGET_S, else the template draft - a reply is never late."""
    future = _writers.submit(write)
    try:
        return future.result(timeout=WRITE_BUDGET_S) or draft
    except Exception as e:  # timeout or model error
        log.warning("%s %s: writer %s - template used", case_id, sid, type(e).__name__)
        return draft


# ---------- run-log events (docs/run-log.md); each call is wrapped in _quiet ----------


def _estimate(agent, case, sid, std):
    try:
        return agent.supplier_estimate(case, sid, std)
    except Exception:
        return None


def _name(agent, sid):
    try:
        return agent.threads[sid].intel.profile.get("name") or sid
    except Exception:
        return sid


def log_opened(clog, case, threads, agent):
    opening = {}
    for sid, ev in threads.items():
        first = next((m for m in ev if m.get("from") != "buyer"), {})
        sheet = (first.get("term_sheets") or [{}])[0]
        std = standard_terms(ev)
        opening[sid] = {
            "offer_id": sheet.get("term_sheet_id"),
            "supplier_name": _name(agent, sid),
            "priced": runlog.priced(case, sheet.get("terms") or {}, std, _estimate(agent, case, sid, std)),
            "standard_terms": std,
            "body": first.get("body"),
        }
    clog.event("case_opened", case=case, opening=opening, c_alt=runlog.finite(levers.alternative_cost(case)))


def log_close(clog, threads, sid, action, reason, t0, attempt, cap_near):
    clog.event(
        "decision",
        round=sum(m.get("from") == "buyer" for m in threads.get(sid, [])) + 1,
        supplier_id=sid,
        kind=action.get("type"),
        candidate_id=action.get("term_sheet_id"),
        reason=reason + (" - wave cap near" if cap_near else "") + (f" - retry {attempt}" if attempt else ""),
        decided_in_s=round(time.monotonic() - t0, 3),
    )


def log_sent(clog, case, view, agent, sid, msg, round_):
    std = standard_terms(view[sid])
    supplier = _estimate(agent, case, sid, std)
    clog.event(
        "message_sent",
        round=round_,
        supplier_id=sid,
        subject=msg.get("subject"),
        body=msg.get("body"),
        sheets=[runlog.priced(case, s.get("terms", s), std, supplier) for s in msg.get("term_sheets") or []],
        refs=msg.get("refs") or [],
        claims=runlog.message_claims(msg),
    )


def log_reply(clog, case, events, agent, sid, reply, round_, latency):
    std = standard_terms(events)
    sheet = (reply.get("term_sheets") or [{}])[0]
    clog.event(
        "reply",
        round=round_,
        supplier_id=sid,
        **{"from": reply.get("from")},
        status=reply.get("status"),
        subject=reply.get("subject"),
        body=reply.get("body"),
        standing={
            "offer_id": sheet.get("term_sheet_id"),
            "priced": runlog.priced(case, sheet.get("terms") or {}, std, _estimate(agent, case, sid, std))
            if sheet.get("terms")
            else None,
        },
        claim_results=reply.get("claim_results") or [],
        missing_fields=reply.get("missing_fields") or [],
        signals=reply.get("signals"),
        attachments=[
            {"attachment_id": a.get("attachment_id"), "name": a.get("name"), "type": a.get("type")}
            for a in reply.get("attachments") or []
        ],
        latency_s=round(latency, 3),
    )


def log_result(clog, table, case, threads, out, action, closed_sid, resumed=False):
    """The result, then - after the end only, GETs, no quota - end_reason, trace and back office.
    `action`/`closed_sid`: our closing move, if we closed the case."""
    accepted = (action or {}).get("type") == "accept"
    sid = out.get("supplier_id") or (closed_sid if accepted else None)
    terms = out.get("terms")
    std = standard_terms(threads.get(sid, [])) if sid else {}
    state, client = {}, getattr(table, "client", None)
    if client and table.session_id:
        try:
            state = client.session(table.session_id) or {}
        except Exception:  # e.g. 403 in the final
            state = {}
    res_state = state.get("result") or {}
    fields = {
        "deal": out.get("deal"),
        "supplier_id": sid,
        "offer_id": out.get("offer_id") or (action or {}).get("term_sheet_id"),
        "terms": terms,
        "c_open": out.get("c_open"),
        "c_deal": out.get("c_deal"),
        "c_alt": runlog.finite(out.get("c_alt", levers.alternative_cost(case))),
        "c_best": out.get("c_best"),
        "score": out.get("score"),
        "cost_breakdown": runlog.priced(case, terms, std)["breakdown"] if terms else None,
        "end_reason": out.get("end_reason") or state.get("end_reason") or res_state.get("end_reason"),
        "replay_url": out.get("replay_url") or res_state.get("replay_url") or state.get("replay_url"),
        "must_haves_ok": must_haves_ok(case, terms, std) if terms else None,
    }
    if resumed:
        fields["resumed"] = True
    clog.event("result", **fields)
    trace = res_state.get("trace") or state.get("trace")
    if trace:
        clog.event("trace", trace=trace)
    if client and table.session_id:
        try:
            clog.event("backoffice", messages=client.backoffice(table.session_id))
        except Exception:  # 403 in the final: expected
            pass


def play_all(client, case_ids, new_agent, parallel=8, run=None):
    used_up = threading.Event()

    def one(case_id):
        if used_up.is_set():
            return case_id, ArenaError(429, "not started: the practice quota is used up")
        try:
            return case_id, play_case(RemoteTable(client), case_id, new_agent(), run=run)
        except ArenaError as e:
            if quota_used_up(e):
                used_up.set()
            log.warning("%s: %s %s", case_id, e.status, e.detail)
            return case_id, e
        except Exception as e:
            log.exception("%s failed", case_id)
            return case_id, e

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        return dict(pool.map(one, case_ids))


def play_waves(client, new_agent, waves=5, parallel=10, poll=3.0, run=None):
    """The Live Final, as the kit's `play_waves`, with the parallel-thread `play_case`."""
    started, closed, caps, retries = {}, set(), {}, {}

    def one(case, deadline):
        try:
            return play_case(RemoteTable(client, case), case["case_id"], new_agent(), deadline, run=run)
        except Exception as e:
            log.exception("%s failed", case["case_id"])
            return e

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        while len(closed) < waves or not all(f.done() for f in started.values()):
            try:
                cases = client.cases("final")
            except ArenaError as e:
                if e.status != 403:  # 403: no wave has started yet
                    log.warning("case list: %s %s", e.status, e.detail)
                cases = []
            except Exception as e:  # network: keep polling
                log.warning("case list failed: %s", e)
                cases = []
            for case in cases:
                if not case.get("open"):
                    if case["wave"] not in closed:
                        log.warning("wave %s closed (%d of %d)", case["wave"], len(closed) + 1, waves)
                    closed.add(case["wave"])
                    continue
                if case.get("seconds_left") is not None:
                    caps[case["wave"]] = time.time() + case["seconds_left"]
                f = started.get(case["case_id"])
                if f and f.done() and isinstance(f.result(), Exception) and retries.get(case["case_id"], 0) < MAX_RETRIES:
                    # it failed before closing (open or attachments after the client's retries): play it again,
                    # the open answers 409 and the session resumes
                    retries[case["case_id"]] = retries.get(case["case_id"], 0) + 1
                    log.warning("wave %s: retrying %s", case["wave"], case["case_id"])
                    del started[case["case_id"]]
                if case["case_id"] not in started and case.get("seconds_left"):
                    log.warning("wave %s: starting %s (%s)", case["wave"], case["case_id"], case.get("theme"))
                    started[case["case_id"]] = pool.submit(one, case, functools.partial(caps.get, case["wave"]))
            time.sleep(poll)
    return {cid: f.result() for cid, f in started.items()}
