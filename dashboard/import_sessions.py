"""Import the team's real arena games into the run-log format (docs/run-log.md) for the dashboard.

    uv run --project starter-kit python dashboard/import_sessions.py            # from saved sessions only
    uv run --project starter-kit python dashboard/import_sessions.py --fetch    # + read-only GETs on the arena

Sources, merged by session id:
  a) starter-kit/runs/sessions/<sid>.json written by `csee eval` (state, result, trace, back office)
  b) --fetch: GET /v1/sessions?set=..., /sessions/{sid}, /threads/{supplier}, /backoffice and the quote
     PDF attachments, with the team key from starter-kit/.env. GET only: no quota, no moves. Fetched
     sessions are cached in runs/.arena-cache/ so later imports work offline.

Every term sheet is priced with arena_kit.cost and the supplier's standard terms (from its quote PDF),
and checked against the arena's c_open / c_deal. Sessions are grouped into runs by the experiment
ledger (experiments/*.jsonl: author, agent, variant, commit); sessions without a ledger row go into
one run per set and day. Imported runs are written to runs/<run_id>/ with "source": "imported" and
are replaced on every import. runs/ is git-ignored.
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from runlog_lite import priced, write_run  # noqa: E402

try:
    from arena_kit.cost import must_haves_ok
except ImportError:  # run it with `uv run --project starter-kit`
    raise SystemExit("arena_kit not importable: run with `uv run --project starter-kit python dashboard/import_sessions.py`")

KIT = REPO / "starter-kit"
SAVED = KIT / "runs" / "sessions"
CASES = KIT / "csee" / "cases"
LEDGER = REPO / "experiments"
RUNS = REPO / "runs"
CACHE = RUNS / ".arena-cache"
GAP = timedelta(minutes=15)  # ledger rows further apart than this start a new run
TOLERANCE = 1.0  # € difference that counts as a C mismatch


# ------------------------------------------------------------------------------------------------
# The arena, read-only
# ------------------------------------------------------------------------------------------------

def load_env(path=KIT / ".env"):
    env = {}
    try:
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


class ReadOnlyArena:
    """Only GETs. There is deliberately no method that could POST."""

    def __init__(self, url, key):
        import httpx

        self.url = url.rstrip("/")
        self.http = httpx.Client(base_url=f"{self.url}/v1", headers={"X-API-Key": key}, timeout=60)
        self.calls = 0

    def get(self, path, params=None, raw=False):
        for attempt in range(4):
            time.sleep(0.12)  # stay under 10 calls/s
            r = self.http.get(path, params=params)
            self.calls += 1
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(1.0 * 2**attempt)
                continue
            break
        if r.status_code >= 400:
            raise RuntimeError(f"GET {path}: HTTP {r.status_code}")
        return r.content if raw else r.json()


def quote_standard(arena, sid, messages):
    """The supplier's standard (and enquiry-fixed) terms from the first quote PDF in its thread."""
    from arena_kit.docs import quote_terms, read_document

    for m in messages:
        for att in m.get("attachments") or []:
            if att.get("name", "").startswith("quote") and att.get("attachment_id"):
                data = arena.get(f"/sessions/{sid}/attachments/{att['attachment_id']}", raw=True)
                terms = quote_terms(read_document(att["name"], data))
                clean = lambda d: {k: (None if v == "none" else v) for k, v in (d or {}).items()}  # noqa: E731
                return {"standard": clean(terms.get("standard")), "fixed": clean(terms.get("fixed"))}
    return None


def fetch(arena, sets, cache=CACHE, refresh_std=()):
    """Save every ended session not cached yet; add the quote terms of sessions from `refresh_std`."""
    cache.mkdir(parents=True, exist_ok=True)
    listed, new = 0, 0
    for set_ in sets:
        rows = arena.get("/sessions", params={"set": set_})
        rows = rows.get("sessions", rows) if isinstance(rows, dict) else rows
        for row in rows:
            listed += 1
            sid = row["session_id"]
            path = cache / f"{sid}.json"
            if row.get("status") != "ended" or (path.exists() and sid not in refresh_std):
                continue
            state = arena.get(f"/sessions/{sid}")
            state["messages"] = {s: arena.get(f"/sessions/{sid}/threads/{s}").get("messages", [])
                                 for s in state.get("threads") or {}}
            try:
                state["backoffice"] = arena.get(f"/sessions/{sid}/backoffice")
            except RuntimeError as e:
                state["backoffice"] = {"error": str(e)}
            state["listing"] = {**row, "set": set_}
            state["quote_terms"] = {}
            for s, msgs in state["messages"].items():
                try:
                    q = quote_standard(arena, sid, msgs)
                except Exception as e:  # a broken PDF must not stop the import
                    q = {"error": str(e)}
                if q:
                    state["quote_terms"][s] = q
            path.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str))
            new += 1
    return listed, new


def fetch_cases(arena, sets):
    out = {}
    for set_ in sets:
        try:
            rows = arena.get("/cases", params={"set": set_})
        except RuntimeError:
            continue
        rows = rows.get("cases", rows) if isinstance(rows, dict) else rows
        for c in rows:
            if isinstance(c, dict) and c.get("case_id"):
                out[c["case_id"]] = c
    return out


# ------------------------------------------------------------------------------------------------
# Inputs
# ------------------------------------------------------------------------------------------------

def load_sessions():
    """{sid: state} from csee eval's folder and our cache (the cache wins: it has the quote terms)."""
    out = {}
    for folder in (SAVED, CACHE):
        for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                s = json.loads(p.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            sid = s.get("session_id") or p.stem
            if sid in out and not s.get("quote_terms"):
                continue
            out[sid] = s
    return out


def load_cases():
    cases = {}
    for p in sorted(CASES.glob("*.json")) if CASES.is_dir() else []:
        try:
            rows = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for c in rows if isinstance(rows, list) else rows.get("cases", []):
            cases[c["case_id"]] = c
    cache = CACHE / "cases.json"
    if cache.exists():
        for cid, c in json.loads(cache.read_text()).items():
            cases.setdefault(cid, c)
    return cases


def load_ledger():
    rows = {}
    for p in sorted(LEDGER.glob("*.jsonl")) if LEDGER.is_dir() else []:
        for line in p.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("session_id"):
                rows[r["session_id"]] = r
    return rows


# ------------------------------------------------------------------------------------------------
# One session -> events
# ------------------------------------------------------------------------------------------------

def _ts(t: datetime):
    return t.astimezone().isoformat(timespec="milliseconds")


def _when(x):
    if isinstance(x, int | float):
        return datetime.fromtimestamp(x).astimezone()
    if isinstance(x, str) and x:
        try:
            return datetime.fromisoformat(x.replace("Z", "+00:00")).astimezone()
        except ValueError:
            return None
    return None


def started(state, ledger_row):
    return (_when((state.get("listing") or {}).get("created_at")) or _when(state.get("created_at"))
            or _when((ledger_row or {}).get("ts")) or datetime.now().astimezone())


def standard_for(state, sup, case):
    """Standard terms for pricing: the quote PDF's, else inferred from the deal's closing terms."""
    q = (state.get("quote_terms") or {}).get(sup) or {}
    std = {k: (None if v == "none" else v) for k, v in {**(q.get("standard") or {}), **(q.get("fixed") or {})}.items()}
    if std:
        return std, "quote"
    r = state.get("result") or {}
    if r.get("deal") and r.get("supplier_id") == sup and r.get("terms"):
        accepted = next((s["terms"] for m in (state.get("messages") or {}).get(sup, [])
                         for s in m.get("term_sheets") or [] if s.get("term_sheet_id") == r.get("offer_id")), {})
        return {k: v for k, v in r["terms"].items() if k not in accepted}, "deal terms"
    return None, "none"


def claim_text(c):
    refs = ", ".join(c.get("refs") or [])
    asserted = ", ".join(f"{k} {v}" for k, v in (c.get("asserted") or {}).items())
    return f"{c.get('type', 'claim').replace('_', ' ')}: {refs}" + (f" ({asserted})" if asserted else "")


def convert(state, case, ledger_row, arena_url):
    """Events for one session, plus a C-check report."""
    sid = state.get("session_id")
    msgs = state.get("messages") or {}
    result = state.get("result") or {}
    trace = result.get("trace") or state.get("trace") or []
    t0 = started(state, ledger_row)
    t_end = _when((ledger_row or {}).get("ts"))
    n_moves = sum(len(v) for v in msgs.values()) + 2
    step = 6.0
    if t_end and t_end > t0:
        step = min(30.0, max(1.0, (t_end - t0).total_seconds() / n_moves))
    clock = [t0]

    def tick(s=1.0):
        clock[0] += timedelta(seconds=step * s)
        return _ts(clock[0])

    std, std_src = {}, {}
    for sup in msgs:
        std[sup], std_src[sup] = standard_for(state, sup, case)

    def price(sup, terms):
        if not case:
            return {"terms": terms, "c": None, "breakdown": None}
        return priced(case, terms, std.get(sup))

    # the supplier's reasons and the claims the arena read from our e-mails, from the trace
    reasons, interpreted = {}, defaultdict(list)
    order = []  # supplier per move, in the global order of the trace
    for st in trace:
        mv = st.get("move") or {}
        actor = st.get("actor")
        sup = mv.get("supplier_id") if actor == "buyer" else actor
        if actor != "buyer":
            reasons[(sup, st.get("round"))] = st.get("reasons")
        elif mv.get("type") == "message":
            interpreted[sup].append((mv.get("interpreted") or {}).get("claims") or [])
        order.append(sup)

    events = []
    opening = {}
    for sup, ms in msgs.items():
        first = next((m for m in ms if m.get("from") != "buyer"), None)
        if not first:
            continue
        sheets = first.get("term_sheets") or [{}]
        name = (first.get("from_name") or "").split(", ", 1)[-1] or sup
        opening[sup] = {"offer_id": sheets[0].get("term_sheet_id"), "supplier_name": name,
                        "priced": price(sup, sheets[0].get("terms") or {}), "standard_terms": std.get(sup) or {},
                        "standard_terms_source": std_src.get(sup), "body": first.get("body"),
                        "reasons": reasons.get((sup, 0))}
    alt = (case or {}).get("buyer", {}).get("alternative") or {}
    c_alt = result.get("c_alt")
    if c_alt is None and case and alt.get("terms", {}).get("unit_price"):
        c_alt = priced(case, alt["terms"])["c"]
    events.append({"ts": _ts(t0), "type": "case_opened", "session_id": sid,
                   "case": case or {"case_id": state.get("case_id"), "suppliers": list(msgs)},
                   "opening": opening, "c_alt": c_alt})

    # walk the threads in trace order (fallback: round-robin), skipping each opening quote
    pos = {sup: 1 for sup in msgs}
    sent = defaultdict(int)
    claims_i = defaultdict(int)
    if not order:
        longest = max((len(v) for v in msgs.values()), default=0)
        order = [sup for i in range(longest) for sup in msgs]
    order = order + [sup for sup in msgs for _ in range(len(msgs[sup]))]  # leftovers, e.g. order confirmations

    def emit(sup, m):
        if m.get("from") == "buyer":
            action = m.get("action") or {}
            if action.get("type") in ("accept", "walk_away"):
                events.append({"ts": tick(0.5), "type": "decision", "session_id": sid, "round": sent[sup] + 1,
                               "supplier_id": sup, "kind": action["type"], "candidate_id": None,
                               "reason": None, "decided_in_s": None, "offer_id": action.get("term_sheet_id")})
                return
            sent[sup] += 1
            arena_claims = interpreted[sup][claims_i[sup]] if claims_i[sup] < len(interpreted[sup]) else []
            claims_i[sup] += 1
            events.append({"ts": tick(1.0), "type": "message_sent", "session_id": sid, "round": sent[sup],
                           "supplier_id": sup, "subject": m.get("subject"), "body": m.get("body"),
                           "sheets": [price(sup, s.get("terms") or {}) for s in m.get("term_sheets") or []],
                           "refs": m.get("refs") or [],
                           "claims": [{"id": (c.get("refs") or [""])[0], "text": claim_text(c)} for c in arena_claims]})
            return
        sheets = m.get("term_sheets") or []
        r = sent[sup] if m.get("status") != "agreed" or not any(
            e["type"] == "decision" and e["supplier_id"] == sup for e in events) else sent[sup] + 1
        events.append({"ts": tick(1.5), "type": "reply", "session_id": sid, "round": max(r, 1), "supplier_id": sup,
                       "from": m.get("from"), "status": m.get("status"), "subject": m.get("subject"),
                       "body": m.get("body"),
                       "standing": {"offer_id": sheets[0].get("term_sheet_id"), "priced": price(sup, sheets[0].get("terms") or {})}
                       if sheets else None,
                       "alternatives": [{"offer_id": s.get("term_sheet_id"), "priced": price(sup, s.get("terms") or {})}
                                        for s in sheets[1:]],
                       "claim_results": m.get("claim_results") or [], "missing_fields": m.get("missing_fields") or [],
                       "signals": m.get("signals") or {}, "attachments": [
                           {k: a.get(k) for k in ("attachment_id", "name", "type")} for a in m.get("attachments") or []],
                       "latency_s": None, "reasons": reasons.get((sup, sent[sup]))})

    for sup in order:
        ms = msgs.get(sup) or []
        if pos.get(sup, 0) < len(ms):
            emit(sup, ms[pos[sup]])
            pos[sup] += 1

    end_reason = state.get("end_reason") or result.get("end_reason")
    replay = state.get("replay_url") or result.get("replay_url")
    res = {k: result.get(k) for k in ("deal", "supplier_id", "offer_id", "terms", "c_open", "c_deal", "c_alt",
                                      "c_best", "score", "cost_breakdown", "must_haves_ok")}
    res.update(end_reason=end_reason, replay_url=f"{arena_url}{replay}" if replay and replay.startswith("/") else replay)
    events.append({"ts": tick(0.5), "type": "result", "session_id": sid, **res})
    if trace:
        events.append({"ts": tick(0.1), "type": "trace", "session_id": sid, "trace": trace})
    bo = state.get("backoffice")
    if isinstance(bo, list) or (isinstance(bo, dict) and "messages" in bo):
        events.append({"ts": tick(0.1), "type": "backoffice", "session_id": sid,
                       "messages": bo if isinstance(bo, list) else bo["messages"]})

    # C check against the arena. Its c_open is the cheapest opening that keeps the must-haves.
    check = {"sid": sid, "case_id": state.get("case_id"), "std": std_src, "open": None, "deal": None, "why": {}}
    ours_open = [o["priced"]["c"] for s_, o in opening.items() if o["priced"]["c"] is not None
                 and (not case or must_haves_ok(case, o["priced"]["terms"], std.get(s_)))]
    if ours_open and result.get("c_open") is not None:
        check["open"] = (min(ours_open), result["c_open"])
    if result.get("deal") and result.get("c_deal") is not None:
        sup = result.get("supplier_id")
        accepted = next((s["terms"] for m in msgs.get(sup, []) for s in m.get("term_sheets") or []
                         if s.get("term_sheet_id") == result.get("offer_id")), None)
        if accepted is not None and case:
            p = price(sup, accepted)
            check["deal"] = (p["c"], result["c_deal"])
            arena_bd = result.get("cost_breakdown") or {}
            off = sorted(k for k, v in (p["breakdown"] or {}).items() if abs(v - (arena_bd.get(k) or 0)) > 0.5)
            check["why"]["deal"] = off
    return events, check


# ------------------------------------------------------------------------------------------------
# Runs
# ------------------------------------------------------------------------------------------------

def group_runs(states, ledger):
    """[(meta, [sid, ...])]: ledger runs (author, agent, variant, commit, set, close in time), then the rest."""
    keyed = defaultdict(list)
    for sid, s in states.items():
        row = ledger.get(sid)
        t = started(s, row)
        set_ = (row or {}).get("set") or s.get("set") or (s.get("listing") or {}).get("set") or "practice"
        if row:
            key = ("ledger", row.get("author") or "unknown", row.get("agent") or "base", row.get("variant") or "base",
                   row.get("commit") or "", set_)
        else:
            key = ("arena", "unknown", "unknown", "", "", f"{set_}|{t:%Y%m%d}")
        keyed[key].append((t, sid))
    runs = []
    for key, items in keyed.items():
        items.sort()
        chunk = [items[0]]
        for prev, cur in zip(items, items[1:], strict=False):
            if key[0] == "ledger" and cur[0] - prev[0] > GAP:
                runs.append((key, chunk))
                chunk = []
            chunk.append(cur)
        runs.append((key, chunk))
    out = []
    for key, chunk in runs:
        kind, author, agent, variant, commit, set_ = key
        t = chunk[0][0]
        if kind == "ledger":
            label = variant if agent == "base" else f"{agent}.{variant}"
            run_id = f"{t:%Y%m%d-%H%M%S}-{author}-{label}"
            notes = (ledger.get(chunk[0][1]) or {}).get("variant_desc") or (ledger.get(chunk[0][1]) or {}).get("note")
            meta = {"run_id": run_id, "agent": label, "agent_version": commit or None, "set": set_,
                    "author": author, "variant": variant, "agent_name": agent, "commit": commit or None,
                    "notes": notes}
        else:
            s, day = set_.split("|")
            run_id = f"{t:%Y%m%d-%H%M%S}-arena-{s}"
            meta = {"run_id": run_id, "agent": "arena", "agent_version": None, "set": s, "author": None,
                    "variant": None, "agent_name": None, "commit": None,
                    "notes": "Sessions without an experiment-ledger row"}
        out.append((meta, [sid for _, sid in chunk]))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fetch", action="store_true", help="also fetch from the arena (GET only)")
    p.add_argument("--sets", default="practice,sandbox")
    p.add_argument("--out", default=str(RUNS))
    p.add_argument("--refresh", action="store_true", help="re-fetch sessions already cached")
    a = p.parse_args(argv)
    sets = [s for s in a.sets.split(",") if s]
    out = Path(a.out)

    env = load_env()
    arena_url = env.get("ARENA_URL", "https://arena.tacto.ai").rstrip("/")
    if a.fetch:
        if not env.get("ARENA_API_KEY"):
            raise SystemExit("--fetch needs ARENA_API_KEY in starter-kit/.env")
        arena = ReadOnlyArena(arena_url, env["ARENA_API_KEY"])
        refresh = set(load_sessions()) if a.refresh else {sid for sid, s in load_sessions().items()
                                                          if not s.get("quote_terms")}
        listed, new = fetch(arena, sets, refresh_std=refresh)
        cases = fetch_cases(arena, sets)
        if cases:
            (CACHE / "cases.json").write_text(json.dumps(cases, ensure_ascii=False))
        print(f"fetched: {listed} sessions listed, {new} saved/updated, {arena.calls} GET calls")

    states = {sid: s for sid, s in load_sessions().items() if s.get("status", "ended") == "ended" and s.get("result")}
    if a.sets:
        states = {sid: s for sid, s in states.items()
                  if (s.get("set") or (s.get("listing") or {}).get("set") or "practice") in sets}
    cases = load_cases()
    ledger = load_ledger()

    # replace earlier imports
    if out.is_dir():
        for d in out.iterdir():
            try:
                if d.is_dir() and json.loads((d / "run.json").read_text()).get("source") == "imported":
                    for f in d.iterdir():
                        f.unlink()
                    d.rmdir()
            except (OSError, json.JSONDecodeError):
                continue

    checks, n_events = [], defaultdict(int)
    runs = group_runs(states, ledger)
    for meta, sids in runs:
        per_case, t_first, t_last = {}, None, None
        for sid in sorted(sids, key=lambda x: started(states[x], ledger.get(x))):
            st = states[sid]
            cid = st.get("case_id")
            events, check = convert(st, cases.get(cid), ledger.get(sid), arena_url)
            checks.append(check)
            for e in events:
                n_events[e["type"]] += 1
            n = 1 + sum(1 for k in per_case if k.split("~")[0] == cid)
            key = cid if n == 1 else f"{cid}~{n}"  # the same case again in this run: its own file
            for e in events:
                e["case_id"] = cid
            per_case[key] = events
            t_first = t_first or events[0]["ts"]
            t_last = events[-1]["ts"]
        meta = {"run_id": meta["run_id"], "agent": meta["agent"], "agent_version": meta["agent_version"],
                "set": meta["set"], "started_at": t_first, "ended_at": t_last, "cases": sorted({k.split("~")[0] for k in per_case}),
                "notes": meta["notes"], "source": "imported", "author": meta["author"], "variant": meta["variant"],
                "agent_name": meta["agent_name"], "commit": meta["commit"], "sessions": sids}
        write_run(out / meta["run_id"], meta, per_case)

    # report
    mism, rel_only = [], []
    for c in checks:
        for what in ("open", "deal"):
            if c[what] and c[what][0] is not None and abs(c[what][0] - c[what][1]) > TOLERANCE:
                row = (c["case_id"], c["sid"], what, c[what][0], c[what][1], c["std"])
                # the arena prices the relationship term with the true supplier; we have no estimate
                (rel_only if c["why"].get(what) == ["relationship"] else mism).append(row)
    std_from = defaultdict(int)
    for c in checks:
        for v in c["std"].values():
            std_from[v] += 1
    print(f"imported {len(states)} sessions into {len(runs)} runs under {out}")
    print("events:", dict(sorted(n_events.items())))
    print("standard terms from:", dict(std_from))
    print(f"C checks: {sum(1 for c in checks if c['open'])} openings, {sum(1 for c in checks if c['deal'])} deals; "
          f"{len(mism)} mismatches > €{TOLERANCE:.0f}, plus {len(rel_only)} deals off only in the relationship term "
          f"(max Δ €{max((abs(r[3] - r[4]) for r in rel_only), default=0):,.0f}; the arena knows the supplier's true cost)")
    for m in mism[:30]:
        print(f"  {m[0]} {m[1]} {m[2]}: ours {m[3]:,.2f} vs arena {m[4]:,.2f} (Δ {m[3] - m[4]:+,.2f}; std {m[5]})")
    missing = sorted({c["case_id"] for c in checks if c["case_id"] not in cases})
    if missing:
        print("no case file (unpriced):", ", ".join(map(str, missing)))


if __name__ == "__main__":
    main()
