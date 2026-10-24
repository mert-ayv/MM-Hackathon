"""Ege's agent: a model plans the strategy for RFQ and bundling cases; code keeps every number safe.
Every other case type, and every case without an LLM (--no-llm, no ANTHROPIC_API_KEY), plays exactly like
base. Only Ege edits this file.

Per move, base computes its rule-based ask first. Then Claude reads the case, the supplier's profile, the
whole thread and (RFQ) the rival offers, and returns a small JSON plan: counter or stop, how far below
the supplier's price to ask, one term to trade for price, and what the e-mail should stress. Code then
clamps the ask (never below our last ask or near the cost-floor estimate, never above its price; in
stabilise / secure_supply never far below base), builds and checks the term sheets, and passes the focus
to the writer. When a bidder answers "agreed" or "final_offer", the model may push once more: in an RFQ
only while another bidder's offer is our backup, alone only by at most 1 %. A slow or failed model call
(STRATEGY_BUDGET_S) falls back to base's move.

    uv run python -m csee --agent ege bench --agents base ege --variants v9      sandbox, free (D02 = RFQ)
    uv run python -m csee --agent ege --variant v9 play case:P05 --confirm        practice: 1 session
"""

import functools
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from arena_kit.cost import RELATIONSHIP_GOALS, complete_offer, must_haves_ok, total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import latest, live_threads, moves_left, standing

from .. import levers
from ..agent import CseeAgent
from ..writer import LLMWriter, TemplateWriter

log = logging.getLogger("csee")

MY_TYPES = {"rfq", "bundling"}
STRATEGY_BUDGET_S = 20  # the strategist's share of our 60 s per message (the writer has its own 15)
MAX_ASK_BELOW = 35.0  # % below the supplier's price we ask at most
RFQ_PUSHES, RFQ_PUSH_MAX = 2, 6.0  # pushes after "agreed"/"final_offer" in an RFQ, % below its price at most
SOLO_PUSHES, SOLO_PUSH_MAX = 1, 1.0  # a single supplier, no backup: one small push (a far push walked, D02)
BACKUP_WITHIN = 1.10  # a rival's offer is a backup if it costs us at most this much more

SYSTEM = """You plan the next move of Hollerau Pumpenwerke's buyer, who negotiates by e-mail with an \
industrial supplier. The score is the total cost C of the accepted deal (price, payment days, freight, lead \
time, coverage of the need, quality, ...), measured between the opening offer and the best deal the supplier \
would ever accept. Code computes every cost and writes the binding term sheets; you choose the strategy.

What we have learned from real games against these suppliers:
- They converge on our anchor, so the first ask matters most. A bidder that answers "agreed" at once took \
our ask as it stood and probably had room left.
- They turn to a final offer around their 4th reply. Steady, visible concessions keep them conceding longer \
than stubbornness; a far push after a final offer can make them walk away, a small one sometimes works.
- In an RFQ the bidders compete: a lower rival price is our strongest argument.
- In stabilise and secure_supply cases, squeezing a supplier below a sustainable margin costs us as well.
- Its pressures (cash, idle capacity, volume, energy, quality) show what it will give price for.

Return:
- action: "counter" to send a new ask, or "stop" when nothing more is worth winning (we then accept the best \
offer on the table). If the supplier's status is agreed or final_offer, "counter" means pushing once more.
- ask_pct_below_their_price: our main ask in % below the supplier's current price (0-35).
- trade_lever: one term to offer as an alternative package in exchange for a lower price, or "none".
- message_focus: one or two sentences on what the e-mail should stress for this supplier. Use no figures \
or data IDs that are not in the input.
- reason: one sentence, for our log."""


def schema(case):
    trades = ["none"] + [f for f in case["negotiable"] if f != "unit_price" and levers.options(case, f)]
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["counter", "stop"]},
            "ask_pct_below_their_price": {"type": "number"},
            "trade_lever": {"type": "string", "enum": trades},
            "message_focus": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["action", "ask_pct_below_their_price", "trade_lever", "message_focus", "reason"],
        "additionalProperties": False,
    }


def anthropic_ready():
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("LLM_PROVIDER", "anthropic") == "anthropic"


@functools.cache
def client():
    import anthropic

    return anthropic.Anthropic(timeout=STRATEGY_BUDGET_S, max_retries=0)  # a retry would overrun the budget


def ask_model(user, case):
    r = client().beta.messages.create(
        model=os.environ.get("LLM_MODEL") or "claude-opus-5-5",
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={
            "effort": os.environ.get("LLM_EFFORT") or "low",
            "format": {"type": "json_schema", "schema": schema(case)},
        },
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # a declined request is re-run on a fallback model inside the same call
    )
    if r.stop_reason in ("refusal", "max_tokens"):
        raise ValueError(f"strategist stopped: {r.stop_reason}")
    return json.loads(next(b.text for b in r.content if b.type == "text"))


_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="strategist")


class FocusWriter:
    """The team's LLM writer, told what this agent's strategist wants each e-mail to stress."""

    def __init__(self, inner, focus):
        self.inner, self.focus = inner, focus

    def write(self, case, agent, sid, events, sheets, claims, ask_breakdown):
        return self.inner.write(case, agent, sid, events, sheets, claims, ask_breakdown, focus=self.focus.get(sid, ""))


class EgeAgent(CseeAgent):
    def __init__(self, package=None, writer=None, params=None):
        super().__init__(package, writer, params)
        self.llm = isinstance(writer, LLMWriter) and anthropic_ready()
        self.focus, self.current, self.decisions, self.pushes = {}, {}, {}, {}
        self.local = threading.local()  # per worker thread: base's nothing_to_win() probes next_terms
        if isinstance(writer, LLMWriter):
            self.writer = FocusWriter(writer, self.focus)

    def mine(self, case):
        return self.llm and case.get("type") in MY_TYPES

    # ---------- the plan ----------
    def plan(self, case, threads, sid, theirs, std, supplier, left, proposal, push=False):
        """Claude's plan for this move (cached per thread length), or None: base's move stands."""
        key = (sid, len(threads[sid]), push)
        if key not in self.decisions:
            try:
                user = self.brief(case, threads, sid, theirs, std, supplier, left, proposal, push)
                d = _pool.submit(ask_model, user, case).result(timeout=STRATEGY_BUDGET_S)
                if d.get("action") not in ("counter", "stop"):
                    raise ValueError(f"bad plan {d}")
                d["ask_pct_below_their_price"] = float(d["ask_pct_below_their_price"])
            except Exception as e:  # timeout, API or JSON error: base decides
                log.warning("%s %s: strategist failed (%s) - base move", case["case_id"], sid, type(e).__name__)
                d = None
            self.decisions[key] = d
            if d:
                log.info("%s %s: plan %s", case["case_id"], sid, d)
                try:
                    self.log.event("strategy", supplier_id=sid, push=push, **d)
                except Exception:
                    pass
        d = self.decisions[key]
        self.current[sid] = d
        self.focus[sid] = (d or {}).get("message_focus", "")
        return d

    def brief(self, case, threads, sid, theirs, std, supplier, left, proposal, push):
        b, st, ev = case["buyer"], self.threads[sid], threads[sid]
        profile = st.intel.profile
        keys = ("name", "situation", "pressures", "what_it_values", "likely_tradeables", "persona")
        keys += ("arguments_to_avoid", "negotiation_history")
        c_theirs = total_cost(case, theirs, std, supplier)
        c_prop = total_cost(case, proposal, std, supplier)
        p_s = theirs["unit_price"]
        out = [
            f"CASE: {case['title']} - type {case['type']}, goal {b.get('category_goal')}",
            f"Need {b['need_per_year']} per year for {b['horizon_years']} years. Current price "
            f"{b.get('current_unit_price')}, fallback price {b.get('fallback_unit_price')}, must-haves "
            f"{b.get('must_haves')}. Negotiable: {case['negotiable']}, options {case.get('term_options')}.",
            f"Our alternative without a deal: C = {levers.alternative_cost(case):,.0f}",
            f"SUPPLIER {sid}: {json.dumps({k: profile.get(k) for k in keys}, ensure_ascii=False)[:3000]}",
            f"Rough full-cost estimate per unit (should-cost based, often off by 5 %): {self.floor_price(st)}",
            "THREAD, oldest first:",
        ]
        bodies = [i for i, m in enumerate(ev) if m.get("from") != "buyer"][-3:]
        for i, m in enumerate(ev[-12:], start=max(len(ev) - 12, 0)):
            sheets = [s.get("terms", s) for s in m.get("term_sheets") or []]
            line = f"- {'we' if m.get('from') == 'buyer' else 'supplier'}"
            line += f" [{m.get('status')}]" if m.get("status") else ""
            line += f" sheets {json.dumps(sheets)}"
            if i in bodies:
                line += f"\n  e-mail: {(m.get('body') or '')[:500]!r}"
            out.append(line)
        out += [
            f"NOW: status {latest(ev).get('status')}, its best offer for us {json.dumps(theirs)} "
            f"-> C = {c_theirs:,.0f}",
            f"Base rule's ask: {json.dumps(proposal)} -> C = {c_prop:,.0f} "
            f"({(1 - proposal['unit_price'] / p_s) * 100:.1f} % below its price)",
            f"Messages we can still send in this thread: {left}",
        ]
        for s in case["suppliers"]:
            if s != sid and threads.get(s):
                sheet_id, t = standing(threads[s])
                price = t.get("unit_price")
                out.append(f"RIVAL {s}: status {latest(threads[s]).get('status')}, price {price}")
        if push:
            cap = RFQ_PUSH_MAX if len(case["suppliers"]) > 1 else SOLO_PUSH_MAX
            out.append(
                f"The supplier said '{latest(ev).get('status')}'. 'counter' pushes once more (code allows at most "
                f"{cap} % below its price); 'stop' takes the best offer on the table."
            )
        return "\n".join(out)

    # ---------- base's move, with the plan applied ----------
    def nothing_to_win(self, *args, **kwargs):
        self.local.probing = True
        try:
            return super().nothing_to_win(*args, **kwargs)
        finally:
            self.local.probing = False

    def next_terms(self, case, threads, sid, theirs, std, supplier, left):
        ours = super().next_terms(case, threads, sid, theirs, std, supplier, left)
        if ours is None or not self.mine(case) or getattr(self.local, "probing", False):
            return ours
        d = self.plan(case, threads, sid, theirs, std, supplier, left, ours)
        if not d:
            return ours
        if d["action"] == "stop":
            return None
        st, p_s = self.threads[sid], theirs["unit_price"]
        p = p_s * (1 - min(max(d["ask_pct_below_their_price"], 0.0), MAX_ASK_BELOW) / 100)
        p = min(p, p_s * 0.995)
        if st.our_prices:
            p = max(p, st.our_prices[-1])  # never step back below our own last ask
        floor = self.floor_price(st)
        if floor and floor < p_s * 0.97:
            p = max(p, floor * 0.95)
        if case["buyer"].get("category_goal") in RELATIONSHIP_GOALS:
            p = max(p, ours["unit_price"] * 0.98)  # squeezing a strategic supplier costs us too
        return {**ours, "unit_price": round(p, 2)}

    def sheets(self, case, sid, ours, std, supplier):
        out = super().sheets(case, sid, ours, std, supplier)
        d = self.current.get(sid) if self.mine(case) else None
        if not d or d.get("trade_lever") in (None, "none"):
            return out
        t = self.lever_sheet(case, out[0], d["trade_lever"], std, supplier)
        if t and t not in out:
            out = [out[0], t] + out[1:]
        return out[:3]

    def lever_sheet(self, case, main, field, std, supplier):
        """The main sheet with `field` one step toward what the supplier prefers, at a price that saves us."""
        opts = levers.options(case, field)
        if field not in main or not opts:
            return None
        here = levers._supplier_rank(field, main[field], case)
        better = [v for v in opts if levers._supplier_rank(field, v, case) > here]
        if not better:
            return None
        t = complete_offer(case, {**main, field: min(better, key=lambda v: levers._supplier_rank(field, v, case))})
        if not must_haves_ok(case, t, std):
            return None
        target = total_cost(case, main, std, supplier) * (1 - self.p.trade_gain)
        t["unit_price"] = levers.price_for(case, t, target, std, supplier)
        return t if 0 < t["unit_price"] < main["unit_price"] * 1.2 else None

    # ---------- after "agreed" / "final_offer" ----------
    def thread_move(self, case, threads, sid):
        if self.case_id != case["case_id"]:
            self.prepare(case, threads)
        self.current.pop(sid, None)
        self.focus[sid] = ""
        msg = super().thread_move(case, threads, sid)
        if msg is not None or not self.mine(case):
            return msg
        return self.push(case, threads, sid)

    def backup_cost(self, case, threads, sid):
        """The cheapest valid standing offer of any other live bidder (None if there is none)."""
        best = None
        for s in live_threads(threads):
            if s == sid:
                continue
            sheet_id, terms = standing(threads[s])
            std = standard_terms(threads[s])
            if sheet_id and terms.get("unit_price") is not None and must_haves_ok(case, terms, std):
                c = total_cost(case, terms, std)
                best = c if best is None else min(best, c)
        return best

    def push(self, case, threads, sid):
        """One more ask after the supplier agreed or made its final offer, if the plan says so."""
        st, ev = self.threads[sid], threads[sid]
        if latest(ev).get("status") not in ("agreed", "final_offer"):
            return None
        rfq = len(case["suppliers"]) > 1
        limit, cap = (RFQ_PUSHES, RFQ_PUSH_MAX) if rfq else (SOLO_PUSHES, SOLO_PUSH_MAX)
        left = moves_left(case, ev)
        if self.pushes.get(sid, 0) >= limit or self.rounds_left(sid, left) <= self.p.reserve_moves:
            return None
        sheet_id, terms = standing(ev)
        std = standard_terms(ev)
        if not sheet_id or terms.get("unit_price") is None or not must_haves_ok(case, terms, std):
            return None
        if rfq:
            backup = self.backup_cost(case, threads, sid)
            if backup is None or backup > total_cost(case, terms, std) * BACKUP_WITHIN:
                return None
        d = self.plan(case, threads, sid, terms, std, self.supplier_estimate(case, sid, std), left, terms, push=True)
        if not d or d["action"] != "counter":
            return None
        pct = min(max(d["ask_pct_below_their_price"], 0.3), cap)
        price = terms["unit_price"] * (1 - pct / 100)
        floor = self.floor_price(st)
        if floor and floor < terms["unit_price"] * 0.97:
            price = max(price, floor)
        ask = complete_offer(case, {**terms, "unit_price": round(price, 2)})
        if ask["unit_price"] >= terms["unit_price"]:
            return None
        self.pushes[sid] = self.pushes.get(sid, 0) + 1
        st.ready = False
        st.our_prices.append(ask["unit_price"])
        claims = self.pick_claims(case, threads, sid)
        msg = {
            "subject": f"Re: {case['title']}"[:300],
            "body": TemplateWriter().write(case, self, sid, ev, [ask], claims, False),
            "term_sheets": [{"terms": ask}],
            "refs": [i for c in claims for i in c.ids][:20],
        }
        if not isinstance(self.writer, TemplateWriter):
            events = list(ev)
            msg["_write"] = lambda: self.writer.write(case, self, sid, events, [ask], claims, False)
        return msg
