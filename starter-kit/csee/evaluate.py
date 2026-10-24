"""Pull every finished session of a set - result, trace with the supplier's reasons, back office -
into runs/, and report how each case went against Tacto's house agent.

    uv run python -m csee eval                 # practice: fetch new sessions, print the report
    uv run python -m csee show <session_id>    # one negotiation, move by move, for reading
"""

import json
import logging
import statistics
from pathlib import Path

import httpx

from arena_kit.client import ArenaError

log = logging.getLogger("csee")
RUNS = Path("runs")


def house_scores(base_url):
    """Tacto's reference agent per practice case, from the public build page (for people, not agents)."""
    try:
        live = httpx.get(f"{base_url.rstrip('/')}/v1/live", timeout=20).json()
        return {b["case_id"]: b.get("house") for b in live.get("bots", [])}
    except Exception:  # the simulator has no build page
        return {}


def fetch(client, set_="practice", out=RUNS):
    """Save each ended session once: runs/sessions/<sid>.json with state, result, trace, back office."""
    folder = out / "sessions"
    folder.mkdir(parents=True, exist_ok=True)
    rows = client.sessions(set_)
    rows = rows.get("sessions", rows) if isinstance(rows, dict) else rows
    new = 0
    for row in rows:
        sid = row["session_id"]
        path = folder / f"{sid.replace('/', '_')}.json"
        if row.get("status") != "ended" or path.exists():
            continue
        state = client.session(sid)
        # the e-mails in both directions live in the threads, not in the session state
        state["messages"] = {s: client.thread(sid, s).get("messages", []) for s in state.get("threads") or {}}
        try:
            state["backoffice"] = client.backoffice(sid)
        except ArenaError as e:
            state["backoffice"] = {"error": e.status, "detail": e.detail}
        state["listing"] = row
        path.write_text(json.dumps(state, ensure_ascii=False, indent=1, default=str))
        new += 1
    log.info("%d sessions listed, %d new saved to %s", len(rows), new, folder)
    return [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))]


def report(sessions, house):
    """Markdown table per case: best and latest score, house agent, where the money went."""
    by_case = {}
    for s in sessions:
        by_case.setdefault(s.get("case_id"), []).append(s)
    lines = [
        "| Case | Runs | Best | Last | House | Gap | Last deal | Rounds | Biggest cost items (last) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    bests = []
    for case_id in sorted(by_case, key=str):
        runs = sorted(by_case[case_id], key=lambda s: s["listing"].get("created_at") or "")
        scores = [(r.get("result") or {}).get("score") or 0.0 for r in runs]
        last = runs[-1].get("result") or {}
        best, h = max(scores), house.get(case_id)
        bests.append(best)
        breakdown = last.get("cost_breakdown") or {}
        top = sorted(((k, v) for k, v in breakdown.items() if v), key=lambda kv: -abs(kv[1]))[:3]
        deal = (
            f"{last.get('supplier_id', '-')} {json.dumps(last.get('terms') or {})}" if last.get("deal") else "no deal"
        )
        house_col = f"{h:.2f}" if h is not None else "-"
        gap = f"{best - h:+.2f}" if h is not None else "-"
        costs = ", ".join(f"{k} {v:,.0f}" for k, v in top)
        lines.append(
            f"| {case_id} | {len(runs)} | {best:.2f} | {scores[-1]:.2f} | {house_col} | {gap} | "
            f"{deal[:120]} | {runs[-1].get('rounds', '-')} | {costs} |"
        )
    if bests:
        lines.append(f"\nMean best score: **{statistics.mean(bests):.3f}** over {len(bests)} cases played")
    hs = [v for v in house.values() if v is not None]
    if hs:
        lines.append(f"House agent mean: {statistics.mean(hs):.3f} over {len(hs)} cases")
    return "\n".join(lines)


def show(state):
    """One negotiation as readable text: every move, the terms, the supplier's reasons, the back office."""
    r = state.get("result") or {}
    out = [
        f"# {state.get('case_id')} · {state.get('session_id')} · {state.get('end_reason')}",
        f"score {r.get('score')} · c_open {r.get('c_open')} · c_deal {r.get('c_deal')} · c_best {r.get('c_best')} · c_alt {r.get('c_alt')}",
        f"deal {r.get('supplier_id')} {json.dumps(r.get('terms'))}",
        f"cost breakdown {json.dumps(r.get('cost_breakdown'))}",
        "",
    ]
    reasons = {}  # (supplier, round) -> the supplier's reasons in words
    for step in r.get("trace") or []:
        reasons[(step.get("actor"), step.get("round"))] = step.get("reasons")
    for sup, messages in (state.get("messages") or {}).items():
        out.append(f"# thread {sup}")
        supplier_round = 0
        for m in messages:
            buyer = m.get("from") == "buyer"
            supplier_round += 0 if buyer else 1
            sheets = [t.get("terms", t) for t in m.get("term_sheets") or []]
            out.append(f"## {m.get('from')} · {m.get('status') or ''}")
            if m.get("body"):
                out.append(m["body"].strip())
            if sheets:
                out.append(f"term sheets: {json.dumps(sheets)}")
            if m.get("claim_results"):
                out.append(f"claims: {json.dumps(m['claim_results'])}")
            if m.get("missing_fields"):
                out.append(f"missing (close on standard terms): {m['missing_fields']}")
            if m.get("action"):
                out.append(f"action: {json.dumps(m['action'])}")
            if not buyer and (why := reasons.get((sup, supplier_round - 1))):
                out.append(f"REASONS: {json.dumps(why, ensure_ascii=False)}")
            out.append("")
    bo = state.get("backoffice")
    if bo:
        out.append("# back office")
        out.append(json.dumps(bo, ensure_ascii=False, indent=1)[:12000])
    return "\n".join(out)
