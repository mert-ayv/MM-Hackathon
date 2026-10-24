"""Play the kit's naive agent against the LOCAL simulator and write a real run log (docs/run-log.md).

Local only: refuses any URL that is not 127.0.0.1/localhost, so it never touches the hosted arena.

    # terminal 1 (starter-kit/):  uv run arena-sim serve --no-clock --data ../data
    # terminal 2 (agent/):        uv run python ../dashboard/fixtures/sim_log.py case:S01 case:S03

By default the log goes to dashboard/fixtures/runs/ (use --out ../runs for the real runs folder).
"""

import argparse
import csv
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from arena_kit.agents.naive import NaiveAgent
from arena_kit.client import ArenaClient
from arena_kit.docs import standard_terms
from arena_kit.play import RemoteTable, latest, play
from hollerau.runlog import Run, priced

HERE = Path(__file__).resolve().parent
SUPPLIERS_CSV = HERE.parents[1] / "data" / "data" / "suppliers.csv"


def supplier_names():
    try:
        with SUPPLIERS_CSV.open(encoding="utf-8") as f:
            return {r["id"]: r["name"] for r in csv.DictReader(f)}
    except OSError:
        return {}


NAMES = supplier_names()


class LoggedTable(RemoteTable):
    """RemoteTable that writes case_opened / message_sent / reply / result events."""

    def __init__(self, client, log, rounds):
        super().__init__(client)
        self.log, self.rounds, self.threads = log, rounds, {}

    def open(self, case_id):
        case, threads = super().open(case_id)
        self.log.session_id = self.session_id
        self.case, self.threads = case, threads
        opening = {}
        for sid, events in threads.items():
            m = latest(events)
            sheets = m.get("term_sheets") or [{}]
            std = standard_terms(events)
            opening[sid] = {"offer_id": sheets[0].get("term_sheet_id"), "supplier_name": NAMES.get(sid, m.get("from")),
                            "priced": priced(case, sheets[0].get("terms") or {}, std), "standard_terms": std,
                            "body": m.get("body")}
        alt = case["buyer"].get("alternative") or {}
        c_alt = priced(case, alt["terms"])["c"] if alt.get("terms", {}).get("unit_price") else None
        self.log.event("case_opened", case=case, opening=opening, c_alt=c_alt)
        return case, threads

    def send(self, sid, message):
        r = self.rounds[sid] = self.rounds.get(sid, 0) + 1
        sheets = [priced(self.case, s["terms"]) for s in message.get("term_sheets") or []]
        self.log.event("message_sent", round=r, supplier_id=sid, subject=message.get("subject"),
                       body=message.get("body"), sheets=sheets, refs=message.get("refs", []))
        t0 = time.monotonic()
        reply = super().send(sid, message)
        sheet = (reply.get("term_sheets") or [None])[0]
        self.log.event("reply", round=r, supplier_id=sid, **{"from": reply.get("from")}, status=reply.get("status"),
                       subject=reply.get("subject"), body=reply.get("body"),
                       standing={"offer_id": sheet["term_sheet_id"], "priced": priced(self.case, sheet["terms"])}
                       if sheet else None,
                       claim_results=reply.get("claim_results", []), missing_fields=reply.get("missing_fields", []),
                       signals=reply.get("signals", {}), attachments=reply.get("attachments", []),
                       latency_s=round(time.monotonic() - t0, 2))
        return reply


class LoggedAgent:
    def __init__(self, log, rounds):
        self.inner, self.log, self.rounds = NaiveAgent(), log, rounds

    def decide(self, case, threads):
        t0 = time.monotonic()
        d = self.inner.decide(case, threads)
        sid, msg = d["supplier_id"], d["message"]
        action = (msg.get("action") or {}).get("type")
        self.log.event("decision", round=self.rounds.get(sid, 0) + 1, supplier_id=sid, kind=action or "send",
                       candidate_id=None, reason="naive: anchor 10 % low, split the difference, accept a final offer",
                       decided_in_s=round(time.monotonic() - t0, 3))
        time.sleep(1.5)  # a little pacing so the replay has something to compress
        return d


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cases", nargs="+")
    p.add_argument("--url", default=os.environ.get("ARENA_URL", "http://127.0.0.1:8000"))
    p.add_argument("--key", default=os.environ.get("ARENA_API_KEY"))
    p.add_argument("--out", default=str(HERE / "runs"))
    a = p.parse_args()
    if urlparse(a.url).hostname not in ("127.0.0.1", "localhost"):
        raise SystemExit(f"refusing {a.url}: this script only talks to the local simulator")
    client = ArenaClient(a.url, a.key)
    if not a.key:
        client = ArenaClient(a.url, client.register(f"Dashboard fixtures {time.time():.0f}", "sim")["api_key"])
    run = Run("sim-naive", "sim", notes="Real log: kit's naive agent vs the local arena-sim", root=a.out)
    for cid in a.cases:
        log, rounds = run.case(cid), {}
        table = LoggedTable(client, log, rounds)
        result = play(table, cid, LoggedAgent(log, rounds))
        if not result.get("end_reason"):  # the closing reply's result leaves it out; the session has it
            result = {**result, "end_reason": client.session(table.session_id).get("end_reason")}
        log.event("result", **{k: result.get(k) for k in ("deal", "supplier_id", "offer_id", "terms", "c_open",
                                                          "c_deal", "c_alt", "c_best", "score", "cost_breakdown",
                                                          "end_reason", "replay_url", "must_haves_ok")})
        print(cid, result.get("end_reason"), result.get("score"))
    run.end()
    print("wrote", run.dir)


if __name__ == "__main__":
    main()
