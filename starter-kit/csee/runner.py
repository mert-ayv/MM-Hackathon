"""Play cases with the csee agent: every supplier thread of a case in parallel.

The 60-second clock runs per thread from the supplier's reply. The kit's `play()` answers threads one
after another, so in an RFQ a second supplier's clock runs while we wait for the first one's reply
(up to a minute) - a timeout. Here each thread has its own worker that answers as soon as its supplier
has replied; one coordinator closes the case when every thread is ready, or before a wave's cap.
"""

import functools
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from arena_kit.client import ArenaError
from arena_kit.play import (
    CLOSE_BEFORE_CAP_S,
    RemoteTable,
    closing_move,
    fetch_documents,
    live_threads,
    quota_used_up,
)

log = logging.getLogger("csee")


def play_case(table, case_id, agent, deadline=None):
    case, threads = table.open(case_id)
    if getattr(table, "done", None):  # resumed a case that had already ended
        return table.done
    for events in threads.values():
        for m in events:
            fetch_documents(table, m)
    agent.prepare(case, threads)
    lock, ended, result = threading.Lock(), threading.Event(), {}

    def near_cap():
        cap = deadline() if callable(deadline) else deadline
        return bool(cap) and time.time() > cap - CLOSE_BEFORE_CAP_S

    def worker(sid):
        while not ended.is_set():
            with lock:
                if sid not in live_threads(threads) or near_cap():
                    return
                t0 = time.monotonic()
                msg = agent.thread_move(case, threads, sid)
                took = time.monotonic() - t0
            if took > 40:
                log.warning("%s %s: decision took %.0fs", case_id, sid, took)
            if msg is None:
                return
            try:
                reply = table.send(sid, msg)
            except ArenaError as e:
                if e.status != 409:
                    log.error("%s %s: %s %s", case_id, sid, e.status, e.detail)
                    agent.threads[sid].ready = True
                    return
                reply = table.missed(sid, e)
            if "result" in reply:
                result.update(reply["result"])
                ended.set()
                return
            fetch_documents(table, reply)
            with lock:
                threads[sid] += [{**msg, "from": "buyer"}, reply]
            log.info(
                "%s %s %s %s", case_id, sid, reply.get("status"), (reply.get("term_sheets") or [{}])[0].get("terms")
            )

    def safe(sid):
        try:
            worker(sid)
        except Exception:  # one broken thread must not stop the case
            log.exception("%s %s: worker failed", case_id, sid)
            agent.threads[sid].ready = True

    workers = [threading.Thread(target=safe, args=(sid,), daemon=True) for sid in live_threads(threads)]
    for w in workers:
        w.start()
    while any(w.is_alive() for w in workers) and not ended.is_set() and not near_cap():
        time.sleep(0.5)
    if result:
        return {**result, "session_id": table.session_id}
    with lock:
        try:
            decision = agent.close(case, threads, force=True)
        except Exception:
            log.exception("%s: agent.close failed - kit closing move", case_id)
            decision = closing_move(case, threads)
    sid, msg = decision["supplier_id"], decision["message"]
    log.info("%s: closing %s %s", case_id, sid, msg["action"])
    try:
        out = table.close(sid, msg)
    except ArenaError as e:
        log.warning("%s: close failed (%s %s)", case_id, e.status, e.detail)
        out = table.result()
    return {**out, "session_id": table.session_id}


def play_all(client, case_ids, new_agent, parallel=8):
    used_up = threading.Event()

    def one(case_id):
        if used_up.is_set():
            return case_id, ArenaError(429, "not started: the practice quota is used up")
        try:
            return case_id, play_case(RemoteTable(client), case_id, new_agent())
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


def play_waves(client, new_agent, waves=5, parallel=10, poll=3.0):
    """The Live Final, as the kit's `play_waves`, with the parallel-thread `play_case`."""
    started, closed, caps = {}, set(), {}

    def one(case, deadline):
        try:
            return play_case(RemoteTable(client, case), case["case_id"], new_agent(), deadline)
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
                if case["case_id"] not in started and case.get("seconds_left"):
                    log.warning("wave %s: starting %s (%s)", case["wave"], case["case_id"], case.get("theme"))
                    started[case["case_id"]] = pool.submit(one, case, functools.partial(caps.get, case["wave"]))
            time.sleep(poll)
    return {cid: f.result() for cid, f in started.items()}
