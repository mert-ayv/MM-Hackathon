"""Ege's agent: Claude negotiates RFQ and bundling cases itself, through tools; code keeps it safe.
Every other case type, and any run without an LLM (--no-llm, no ANTHROPIC_API_KEY), plays exactly like
base. Only Ege edits this file.

Each supplier reply starts one agent turn (Anthropic SDK tool runner). Claude gets the case, the
supplier's profile, the whole thread, the rivals' offers with their cost C, the arguments the arena will
verify, and base's rule-based ask as a reference. It can price any package exactly (`price_package`),
look up a data row (`lookup`), and ends the turn with `submit_move`: counter (1-3 term sheets and the
e-mail it writes), ready (stop writing to this supplier), accept its offer now, or walk away.

Code checks every move: sheets snapped to the allowed options with the must-haves kept, none dearer than
the supplier's own offer, our main ask never below our last one (except a push), a push after "agreed" /
"final_offer" only with a backup bidder (RFQ) or by at most 1 % (one supplier), accept only the standing
offer and only if it beats the alternative, walk away only if no offer does, data IDs it did not get
removed, chosen arguments kept word for word. A turn that fails or runs past MOVE_BUDGET_S falls back to
base's move with a template e-mail, so we are never late (the arena gives 60 s per message).

    uv run python -m csee --agent ege bench --agents base ege --variants v9      sandbox, free (D02 = RFQ)
    uv run python -m csee --agent ege --variant v9 play case:P05 --confirm        practice: 1 session
"""

import functools
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from anthropic import beta_tool

from arena_kit.cost import complete_offer, must_haves_ok, total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import ENDED, latest, live_threads, moves_left, standing

from .. import intel as intel_mod
from .. import levers
from ..agent import CseeAgent, avoided
from ..writer import ID_RE, SIGN, LLMWriter, TemplateWriter, describe

log = logging.getLogger("csee")

AGENT_TYPES = {"rfq", "bundling"}
MOVE_BUDGET_S = 40  # one whole agent turn; the arena allows 60 s per message
MAX_TURNS = 5  # model calls per move (each tool round trip is one)
MAX_ARGUMENTS = 3  # the arena checks at most 3 per message
RFQ_PUSHES, SOLO_PUSHES, SOLO_PUSH_MAX = 2, 1, 0.01  # after "agreed"/"final_offer"
BACKUP_WITHIN = 1.10  # a rival's offer is a backup if it costs us at most this much more

SYSTEM = """You are the buyer of Hollerau Pumpenwerke, a German pump maker, negotiating by e-mail with \
industrial suppliers. Each turn you decide our next move toward ONE supplier, then call submit_move once.

Score: the total cost C of the deal we finally accept (price, payment days, freight, lead time, coverage \
of our need, quality, ...; lower is better), measured between the opening offer and the best deal any \
supplier would ever accept. price_package gives the exact C of any package - use it instead of estimating.

What we have learned from real games against these suppliers:
- They converge on our anchor, so the first ask matters most. A bidder that answers "agreed" at once took \
our ask as it stood and probably had room left.
- They turn to a final offer around their 4th reply. Steady, visible concessions keep them conceding; a \
far push after a final offer can make them walk away, a small one sometimes works.
- In an RFQ the bidders compete; a lower rival price is our strongest argument.
- In stabilise and secure_supply cases, squeezing a supplier below a sustainable margin raises our C too \
(price_package includes it).
- Read the supplier: its pressures (cash, idle capacity, volume, energy, quality) show what it will give \
price for. Faster payment costs us little (8 % a year) and can be worth much more to a cash-short firm.
- Only the FIRST sheet of a supplier's reply can be accepted. To take one of its other sheets, send it back \
as your counter word for word; it will agree.
- Every term sheet binds exactly as sent; prose never binds.

submit_move actions:
- counter: 1-3 term sheets (main ask first) and the e-mail. Plain text, at most 150 words, polite and \
firm, signed "Hollerau Pumpenwerke GmbH, Purchasing". Include each chosen argument sentence word for word. \
Never reveal urgency, a budget, a deadline or that we lack alternatives. Use no figures or data IDs that \
are not in the input.
- ready: stop writing to this supplier; its offer stands, and we accept the best offer once every bidder \
is done. Choose it when pushing further is not worth the risk.
- accept: accept this supplier's current offer now (ends the whole case).
- walk_away: end the case without a deal (only right if no offer beats our alternative).

Be quick: this turn has about 30 seconds. One or two price_package calls, then submit_move."""


@functools.cache
def client():
    import anthropic

    return anthropic.Anthropic(max_retries=0)  # a retry would overrun the move budget


def llm_ready():
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("LLM_PROVIDER", "anthropic") == "anthropic"


_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="ege-agent")


class EgeAgent(CseeAgent):
    def __init__(self, package=None, writer=None, params=None):
        super().__init__(package, writer, params)
        self.llm = isinstance(writer, LLMWriter) and llm_ready()
        self.pushes = {}

    def mine(self, case):
        return self.llm and case.get("type") in AGENT_TYPES

    # ---------- one move ----------
    def thread_move(self, case, threads, sid):
        if self.case_id != case["case_id"]:
            self.prepare(case, threads)
        if not self.mine(case):
            return super().thread_move(case, threads, sid)
        st, ev = self.threads[sid], threads[sid]
        st.events = ev
        self.bookkeep(case, sid, ev)
        if latest(ev).get("status") in ENDED or moves_left(case, ev) <= 0:
            st.ready = True
            return None
        decision = self.ask_agent(case, threads, sid)
        if decision is not None:
            try:
                return self.apply(case, threads, sid, decision)
            except Exception:
                log.exception("%s %s: agent move invalid - base move", case["case_id"], sid)
        msg = super().thread_move(case, threads, sid)
        if msg:
            msg.pop("_write", None)  # the agent used the time: template wording
        return msg

    def bookkeep(self, case, sid, ev):
        """What base's thread_move records from a reply: a cost breakdown, the supplier's price path."""
        st, last = self.threads[sid], latest(ev)
        for att in last.get("attachments") or []:
            if "breakdown" in (att.get("name") or "").lower() and att.get("text"):
                parsed = intel_mod.parse_cost_breakdown(att["text"])
                price = (standing(ev)[1] or {}).get("unit_price")
                if parsed and parsed.get("full_cost") and (not price or parsed["full_cost"] <= 0.98 * price):
                    st.breakdown = parsed
        price = standing(ev)[1].get("unit_price")
        if price is not None and (not st.their_prices or st.their_prices[-1] != price):
            st.their_prices.append(price)

    # ---------- the agent turn ----------
    def ask_agent(self, case, threads, sid):
        """Claude's move for this thread, or None (failed, or over MOVE_BUDGET_S)."""
        t0, stop, decision = time.monotonic(), {"now": False}, {}
        try:
            arguments = self.arguments(case, threads, sid)
            brief = self.brief(case, threads, sid, arguments)
            tools = self.tools(case, threads, sid, decision)
            future = _pool.submit(self.run_turns, brief, tools, decision, stop, t0)
            future.result(timeout=MOVE_BUDGET_S)
        except Exception as e:
            stop["now"] = True
            log.warning("%s %s: agent failed (%s) - base move", case["case_id"], sid, type(e).__name__)
            return None
        if not decision:
            log.warning("%s %s: agent made no move - base move", case["case_id"], sid)
            return None
        decision["_arguments"] = arguments
        took = time.monotonic() - t0
        log.info(
            "%s %s: agent %s in %.1fs: %s", case["case_id"], sid, decision.get("action"), took, decision.get("reason")
        )
        try:
            self.log.event(
                "agent_move",
                supplier_id=sid,
                seconds=round(took, 1),
                **{k: v for k, v in decision.items() if not k.startswith("_")},
            )
        except Exception:
            pass
        return decision

    def run_turns(self, brief, tools, decision, stop, t0):
        runner = (
            client()
            .with_options(timeout=MOVE_BUDGET_S)
            .beta.messages.tool_runner(
                model=os.environ.get("LLM_MODEL") or "claude-opus-5-5",
                max_tokens=16000,
                system=SYSTEM,
                tools=tools,
                messages=[{"role": "user", "content": brief}],
                max_iterations=MAX_TURNS,
                output_config={"effort": os.environ.get("LLM_EFFORT") or "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",  # a declined request is re-run on a fallback model inside the same call
            )
        )
        for message in runner:
            for block in message.content:
                if block.type == "tool_use" and block.name == "submit_move":
                    decision.update(block.input)  # the move is in the call itself: no further round trip
                    return
            if stop["now"] or time.monotonic() - t0 > MOVE_BUDGET_S:
                return

    def tools(self, case, threads, sid, decision):
        ev = threads[sid]
        std = standard_terms(ev)
        supplier = self.supplier_estimate(case, sid, std)
        _, theirs = standing(ev)

        @beta_tool
        def price_package(terms: dict) -> str:
            """Exact total cost C (EUR, lower is better for us) of a term sheet for this supplier.

            Args:
                terms: values for the case's negotiable fields, e.g. {"unit_price": 28.5, "payment_days": 30}.
                    Missing fields take the supplier's current values; all are snapped to the allowed options.
            """
            t = complete_offer(case, {**theirs, **terms})
            c = total_cost(case, t, std, supplier)
            return json.dumps(
                {
                    "terms": t,
                    "C": round(c),
                    "must_haves_ok": must_haves_ok(case, t, std),
                    "beats_alternative": c < levers.alternative_cost(case),
                    "vs_its_current_offer": round(c - total_cost(case, theirs, std, supplier)),
                }
            )

        @beta_tool
        def lookup(data_id: str) -> str:
            """One row of our procurement data by its ID, e.g. "sc:70210@2026Q3" or "po:4500010001-10".

            Args:
                data_id: the citable data ID.
            """
            fact = self.fact_row(case, data_id)
            return json.dumps(fact, ensure_ascii=False, default=str)[:1500] if fact else "unknown ID"

        @beta_tool
        def submit_move(
            action: str,
            term_sheets: list[dict] | None = None,
            argument_keys: list[str] | None = None,
            email_body: str = "",
            reason: str = "",
        ) -> str:
            """Our move toward this supplier. Call exactly once, as the last step.

            Args:
                action: "counter", "ready", "accept" or "walk_away".
                term_sheets: counter only: 1-3 packages over the negotiable fields, main ask first.
                argument_keys: counter only: up to 3 keys of the verified arguments to use, e.g. ["A1"].
                email_body: counter only: the e-mail, plain text, signed.
                reason: one sentence on why, for our log.
            """
            decision.update(
                action=action,
                term_sheets=term_sheets,
                argument_keys=argument_keys,
                email_body=email_body,
                reason=reason,
            )
            return "Recorded."

        return [price_package, lookup, submit_move]

    def fact_row(self, case, data_id):
        return case.get("facts", {}).get(data_id) or (self.pkg.lookup(data_id) if self.pkg else None)

    def arguments(self, case, threads, sid):
        """{key: Claim}: the arguments still unused in this case that the arena will verify."""
        st = self.threads[sid]
        claims = list(st.intel.claims)
        if len(case["suppliers"]) > 1:
            claims = intel_mod.rival_claims(case, {s: standing(threads[s]) for s in threads}, sid) + claims
        avoid = " ".join(
            f"{a.get('argument', '')} {a.get('why', '')}" for a in st.intel.profile.get("arguments_to_avoid", [])
        ).lower()
        out = {}
        for c in claims:
            key = tuple(c.ids) if c.kind != "rival" else (sid, *c.ids)
            if key in self.used_ids or any(i in self.used_ids for i in c.ids if c.kind != "rival"):
                continue
            if not avoided(c, avoid):
                out[f"A{len(out) + 1}"] = c
            if len(out) >= 10:
                break
        return out

    def brief(self, case, threads, sid, arguments):
        b, st, ev = case["buyer"], self.threads[sid], threads[sid]
        std = standard_terms(ev)
        supplier = self.supplier_estimate(case, sid, std)
        profile = st.intel.profile
        keys = ("name", "situation", "pressures", "what_it_values", "likely_tradeables", "persona")
        keys += ("arguments_to_avoid", "negotiation_history")
        out = [
            f"CASE: {case['title']} - type {case['type']}, goal {b.get('category_goal')}. {case.get('briefing', '')}",
            f"Need {b['need_per_year']} per year for {b['horizon_years']} years. Current price "
            f"{b.get('current_unit_price')}, fallback price {b.get('fallback_unit_price')}. Must-haves: "
            f"{b.get('must_haves')}. Negotiable: {case['negotiable']}, allowed options "
            f"{case.get('term_options')}; fixed: {case.get('fixed_terms')}.",
            f"Our alternative without a deal: C = {levers.alternative_cost(case):,.0f}",
            f"SUPPLIER {sid}: {json.dumps({k: profile.get(k) for k in keys}, ensure_ascii=False)[:3000]}",
            f"Its standard terms (apply to anything a sheet leaves out): {json.dumps(std)}",
            f"Rough full-cost estimate per unit (should-cost based, often 5 % off): {self.floor_price(st)}",
            "THREAD WITH THIS SUPPLIER, oldest first:",
        ]
        bodies = {i for i, m in enumerate(ev) if m.get("from") != "buyer"}
        bodies = set(sorted(bodies)[-3:])
        for i, m in enumerate(ev):
            line = f"- {'we' if m.get('from') == 'buyer' else 'supplier'}"
            line += f" [{m.get('status')}]" if m.get("status") else ""
            for s in m.get("term_sheets") or []:
                t = s.get("terms", s)
                c = total_cost(case, t, std, supplier) if t.get("unit_price") is not None else None
                line += f"\n    sheet {json.dumps(t)}" + (f" -> C {c:,.0f}" if c is not None else "")
            if m.get("claim_results"):
                line += f"\n    our arguments checked: {m['claim_results']}"
            if i in bodies:
                line += f"\n    e-mail: {(m.get('body') or '')[:600]!r}"
            out.append(line)
        out.append(f"Messages we can still send to it: {moves_left(case, ev)}")
        for s in case["suppliers"]:
            if s != sid and threads.get(s):
                _, t = standing(threads[s])
                rstd = standard_terms(threads[s])
                c = total_cost(case, t, rstd) if t.get("unit_price") is not None else None
                out.append(
                    f"RIVAL {s}: status {latest(threads[s]).get('status')}, offer {json.dumps(t)}"
                    + (f" -> C {c:,.0f}" if c is not None else "")
                )
        try:
            _, theirs = self.their_sheet(case, ev, std, supplier)
            hint = super().next_terms(case, threads, sid, theirs, std, supplier, moves_left(case, ev))
            if hint:
                out.append(f"Our rule-based engine would ask: {json.dumps(hint)} (a reference, not an order)")
        except Exception:
            pass
        out.append("VERIFIED ARGUMENTS (cite by key; the sentence must appear word for word):")
        out += [f"{k}: {c.sentence}" for k, c in arguments.items()] or ["(none left)"]
        return "\n".join(out)

    # ---------- checking and sending the move ----------
    def apply(self, case, threads, sid, d):
        st, ev = self.threads[sid], threads[sid]
        action = d.get("action")
        std = standard_terms(ev)
        supplier = self.supplier_estimate(case, sid, std)
        sheet_id, theirs = standing(ev)
        status = latest(ev).get("status")
        c_alt = levers.alternative_cost(case)
        if action == "accept":
            if (
                sheet_id
                and theirs.get("unit_price") is not None
                and must_haves_ok(case, theirs, std)
                and (total_cost(case, theirs, std) < c_alt)
            ):
                st.ready = True
                return {"action": {"type": "accept", "term_sheet_id": sheet_id}}
            action = "ready"
        if action == "walk_away":
            if not any(self.valid_offer_beats(case, threads, s, c_alt) for s in live_threads(threads)):
                st.ready = True
                return {"action": {"type": "walk_away"}}
            action = "ready"
        if action != "counter":
            st.ready = True
            return None
        pushing = status in ("agreed", "final_offer")
        if pushing and not self.may_push(case, threads, sid):
            st.ready = True
            return None
        c_theirs = total_cost(case, theirs, std, supplier) if theirs.get("unit_price") is not None else float("inf")
        sheets = []
        for raw in (d.get("term_sheets") or [])[:3]:
            t = complete_offer(case, {**theirs, **(raw.get("terms", raw) if isinstance(raw, dict) else {})})
            if t.get("unit_price") is None or t["unit_price"] <= 0 or not must_haves_ok(case, t, std):
                continue
            if total_cost(case, t, std, supplier) >= c_theirs or t in sheets:
                continue  # dearer than what it already offers: pointless
            sheets.append(t)
        if not sheets:
            st.ready = True
            return None
        main = sheets[0]
        if pushing and len(case["suppliers"]) == 1:
            main["unit_price"] = round(max(main["unit_price"], theirs["unit_price"] * (1 - SOLO_PUSH_MAX)), 2)
        elif not pushing and st.our_prices:
            main["unit_price"] = round(max(main["unit_price"], st.our_prices[-1]), 2)  # never step back
        if pushing:
            self.pushes[sid] = self.pushes.get(sid, 0) + 1
        claims = [d["_arguments"][k] for k in (d.get("argument_keys") or []) if k in d["_arguments"]]
        claims = claims[:MAX_ARGUMENTS]
        for c in claims:
            key = tuple(c.ids) if c.kind != "rival" else (sid, *c.ids)
            self.used_ids.add(key)
            self.used_ids.update(i for i in c.ids if c.kind != "rival")
        st.ready = False
        st.our_prices.append(main["unit_price"])
        return {
            "subject": f"Re: {case['title']}"[:300],
            "body": self.body(case, sid, ev, d.get("email_body") or "", sheets, claims, threads),
            "term_sheets": [{"terms": t} for t in sheets],
            "refs": [i for c in claims for i in c.ids][:20],
        }

    def body(self, case, sid, ev, text, sheets, claims, threads):
        """The agent's e-mail, made safe: only data IDs it was given, every argument and package stated."""
        if not text.strip():
            return TemplateWriter().write(case, self, sid, ev, sheets, claims, False)
        allowed = {i for c in claims for i in c.ids}
        allowed |= {
            s["term_sheet_id"]
            for e in threads.values()
            for m in e
            for s in m.get("term_sheets") or []
            if s.get("term_sheet_id")
        }
        text = ID_RE.sub(lambda m: m.group(0) if m.group(0) in allowed else "", text)
        missing = [c.sentence for c in claims if c.sentence not in text]
        missing += [f"Our proposal: {describe(t)}." for t in sheets if f"{t['unit_price']:.2f}" not in text]
        sign = text.rfind("Hollerau Pumpenwerke GmbH")
        if sign >= 0:  # keep the agent's own sign-off last
            start = text.rfind("\n\n", 0, sign)
            text, closing = (text[:start], text[start:]) if start >= 0 else (text[:sign], text[sign:])
        else:
            closing = "\n\n" + SIGN
        if missing:
            text = text.rstrip() + "\n\n" + "\n".join(missing)
        return (text.rstrip() + closing)[:8000]

    def valid_offer_beats(self, case, threads, s, c_alt):
        sheet_id, terms = standing(threads[s])
        std = standard_terms(threads[s])
        return (
            bool(sheet_id)
            and terms.get("unit_price") is not None
            and must_haves_ok(case, terms, std)
            and (total_cost(case, terms, std) < c_alt)
        )

    def may_push(self, case, threads, sid):
        """After "agreed"/"final_offer": an RFQ bidder only with a backup bidder, a lone supplier once."""
        if len(case["suppliers"]) == 1:
            return self.pushes.get(sid, 0) < SOLO_PUSHES
        if self.pushes.get(sid, 0) >= RFQ_PUSHES:
            return False
        ev = threads[sid]
        _, terms = standing(ev)
        mine = total_cost(case, terms, standard_terms(ev)) if terms.get("unit_price") is not None else None
        backups = [
            total_cost(case, standing(threads[s])[1], standard_terms(threads[s]))
            for s in live_threads(threads)
            if s != sid and self.valid_offer_beats(case, threads, s, float("inf"))
        ]
        return mine is not None and bool(backups) and min(backups) <= mine * BACKUP_WITHIN
