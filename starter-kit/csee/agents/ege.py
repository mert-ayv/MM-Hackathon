"""Ege's agent: Claude negotiates RFQ, bundling and price-increase cases through a typed move; code checks
it, sets the minimum pressure and writes every figure. Every other case type, and any run without an LLM
(--no-llm, no ANTHROPIC_API_KEY), plays exactly like base. Only Ege edits this file.

Each supplier reply starts one agent turn (Anthropic SDK tool runner). The brief holds the case, the
supplier's profile, the whole thread, the rivals' offers with their cost C, the verified arguments, the
playbook for this case type (agents/playbooks/<type>.md), the plan Claude committed to for this supplier and
base's rule move. Tools: `price_package` (exact C of any package), `lookup` (a data row) and `submit_move`,
which takes a typed `Move` and answers an invalid one with the exact error, so Claude fixes it in the turn.

What reaches the supplier is safe by construction:
- Claude never writes a figure, a term or a data ID. Its text is two short paragraphs (opening, closing)
  checked for digits, IDs, term words and forbidden statements; failing text is replaced by the template's.
  Code writes the e-mail: opening, the chosen verified arguments word for word, every package described
  from the final sheets (index clauses included), closing.
- Arguments: only keys from the verified list, at most one per data family per message (the arena pools
  several `sc:` rows into one mean - P01's "contradicted").
- Sheets: snapped to the allowed options, must-haves kept, none dearer than the supplier's own offer, the
  main ask never softer than base's rule move nor below our last ask, alternatives never dearer than the main.
- While the rules would still counter an open thread, "ready" / "accept" / "walk_away" become the rule move.
- Walk risk: a supplier holding its price (twice the same, or "remains" / "stands" / "final") gets
  exactly the rule ask, and no push after a final offer. Otherwise a push after
  "agreed"/"final_offer" needs a backup bidder (RFQ) or is one step of at most 1 % (one supplier).
- Accept only the standing offer and only if it beats the alternative; walk away only if no offer does.
A turn that fails or runs past MOVE_BUDGET_S falls back to base's move with a template e-mail.

    uv run python -m csee --agent ege --variant v9 run --set sandbox --cases case:D02 --parallel 1   free
    uv run python -m csee --agent ege --variant v9 play case:P01 --confirm      practice: 1 session
"""

import functools
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from anthropic import beta_tool
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from arena_kit.cost import complete_offer, must_haves_ok, total_cost
from arena_kit.docs import standard_terms
from arena_kit.play import ENDED, latest, live_threads, moves_left, standing

from .. import intel as intel_mod
from .. import levers
from ..agent import CseeAgent, avoided
from ..writer import ID_RE, OPENERS, SIGN, LLMWriter, describe

log = logging.getLogger("csee")

AGENT_TYPES = {"rfq", "bundling", "price_increase"}
PLAYBOOKS = Path(__file__).parent / "playbooks"
MOVE_BUDGET_S = 40  # one whole agent turn; the arena allows 60 s per message
MAX_TURNS = 5  # model calls per move (each tool round trip is one)
MAX_ARGUMENTS = 3  # the arena checks at most 3 per message
RFQ_PUSHES, SOLO_PUSHES, SOLO_PUSH_MAX = 2, 1, 0.01  # after "agreed"/"final_offer"
BACKUP_WITHIN = 1.10  # a rival's offer is a backup if it costs us at most this much more
OPENING_WORDS, CLOSING_WORDS = 60, 35

# Free text may set the tone and make the point; it may not carry a figure, a term, an ID or a statement
# that leaks our position or promises something no sheet holds.
FORBIDDEN_TEXT = re.compile(
    r"\d|%|€|\$|\beur\b|\b(?:clause|deadband|index|indexed|payment|days?|net|incoterms?|dap|exw|fca|lead[- ]?time|"
    r"tooling|months?|years?|volume|effective|valid from|alternative|alternatively|option|package|propos\w*|"
    r"budget|deadline|urgent\w*|asap|limit\w*|maximum|at most|cannot accept more|no alternatives?|only supplier|"
    r"sole supplier|single source|we accept|agreed|confirm\w*|walk away|terminate)\b",
    re.I,
)
HOLD_WORDS = re.compile(r"\b(?:remains?|stands?|final|no further|cannot go (?:any )?lower|last word|unchanged)\b", re.I)

SYSTEM = """You are the buyer of Hollerau Pumpenwerke, a German pump maker, negotiating by e-mail with \
industrial suppliers. Each turn you decide our next move toward ONE supplier and call submit_move once.

Score: the total cost C of the deal we finally accept (price, payment days, freight, lead time, coverage \
of our need, quality, ...; lower is better), measured between the opening offer and the best deal any \
supplier would ever accept. price_package gives the exact C of any package - use it, do not estimate.

Hard numbers from our team's real games against these suppliers:
- Deals land 2-8 % above our FIRST ask: the anchor decides most of the score.
- 0 walk-aways in about 630 supplier replies to steady rule-based moves. The walk-aways we did cause came \
from e-mails the supplier could not trust (claims it could not verify, packages that did not match the \
sheets) and from far pushes after a supplier held its price.
- Suppliers turn to a final offer around their 4th reply. Small, steady steps keep them conceding.
- A supplier that answers "agreed" at once took our ask as it stood and had room left.
- Only the FIRST sheet of a supplier's reply can be accepted. To take one of its other sheets, send it back \
as your main sheet unchanged; it will agree.
- Every term sheet binds exactly as sent; prose never binds.

Our rule engine's next ask is in the brief: the minimum pressure. Code never sends a main sheet that costs \
us more, and while the rules would still counter, it overrides ready / accept / walk_away. Add what the \
rules cannot: a harder ask when the thread shows room, the right alternative sheet, the right arguments, \
a push after "agreed", and a tone that fits this supplier.

The PLAN: on your first move toward a supplier, set plan = {"anchor", "target", "walk_away"} as unit \
prices (anchor <= target <= walk_away; walk_away = the most we would ever pay it). Later moves keep it; \
revise only when the supplier gave new information, and say why in the reason.

How the e-mail is built: code writes the packages from your sheets and inserts the arguments you pick, \
word for word. You write only two short plain-text paragraphs:
- opening (at most 60 words): the tone and the point for this supplier.
- closing (at most 35 words): what we expect next.
They must contain NO digits, prices, percentages, dates, data IDs or terms (no "payment", "days", \
"clause", "lead time", "alternative", "propose"...), and never mention a budget, a deadline, urgency, a \
limit we cannot back with data, or that we lack alternatives. Text that breaks this is replaced by a \
standard sentence.

submit_move actions:
- counter: 1-3 term sheets (main ask first), argument keys (at most one per data family: one scorecard, \
one index series, one notice pair, one rival offer), opening, closing.
- ready: stop writing to this supplier; its offer stands and we accept the best offer once every bidder \
is done.
- accept: accept this supplier's current offer now (ends the whole case).
- walk_away: end the case without a deal (only right if no offer beats our alternative).

Be quick: this turn has about 30 seconds. At most one or two price_package calls, then submit_move."""


# ---------- the typed move ----------
class Plan(BaseModel):
    anchor: float = Field(gt=0)
    target: float = Field(gt=0)
    walk_away: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if not self.anchor <= self.target <= self.walk_away:
            raise ValueError("plan needs anchor <= target <= walk_away")
        return self


def clean_text(text, max_words):
    """A paragraph Claude wrote, or "" when it is too long or carries a figure, a term or a forbidden phrase."""
    text = " ".join((text or "").split())
    if not text or len(text.split()) > max_words or FORBIDDEN_TEXT.search(text) or ID_RE.search(text):
        return ""
    return text


class Move(BaseModel):
    action: Literal["counter", "ready", "accept", "walk_away"]
    term_sheets: list[dict] = Field(default_factory=list, max_length=3)
    argument_keys: list[str] = Field(default_factory=list, max_length=MAX_ARGUMENTS)
    opening: str = ""
    closing: str = ""
    plan: Plan | None = None
    reason: str = ""

    @field_validator("opening")
    @classmethod
    def opening_text(cls, v):
        return clean_text(v, OPENING_WORDS)

    @field_validator("closing")
    @classmethod
    def closing_text(cls, v):
        return clean_text(v, CLOSING_WORDS)

    @model_validator(mode="after")
    def counter_has_sheets(self):
        if self.action == "counter" and not self.term_sheets:
            raise ValueError("a counter needs at least one term sheet")
        return self


def family(claim):
    """The arena checks some data together: all `sc:` rows of a message as one mean, a letter with its
    contract, two months of one index series. One argument per family per message."""
    first = claim.ids[0] if claim.ids else claim.kind
    prefix = first.split(":", 1)[0]
    if prefix in ("sc", "qn"):
        return "scorecard"
    if prefix == "idx":
        return "idx:" + first.split(":", 1)[1].split("@")[0]
    if prefix in ("doc", "ctr"):
        return "notice"
    if prefix in ("offer", "quote") or claim.kind == "rival":
        return "rival"
    return prefix


def check_move(case, raw, arguments):
    """(Move, None) or (None, the errors to tell Claude)."""
    try:
        move = Move.model_validate(raw)
    except ValidationError as e:
        return None, "; ".join(f"{'.'.join(map(str, x['loc'])) or 'move'}: {x['msg']}" for x in e.errors())
    errors = []
    allowed = set(case["negotiable"])
    for i, sheet in enumerate(move.term_sheets):
        unknown = set(sheet) - allowed
        if unknown:
            errors.append(f"term_sheets[{i}]: {sorted(unknown)} are not negotiable here ({sorted(allowed)})")
        price = sheet.get("unit_price")
        if not isinstance(price, int | float) or price <= 0:
            errors.append(f"term_sheets[{i}]: unit_price must be a positive number")
    bad = [k for k in move.argument_keys if k not in arguments]
    if bad:
        errors.append(f"argument_keys {bad} are not in the verified list")
    families = [family(arguments[k]) for k in move.argument_keys if k in arguments]
    if len(families) != len(set(families)):
        errors.append("two arguments from the same data family: pick one of them")
    return (None, "; ".join(errors)) if errors else (move, None)


# ---------- the model ----------
@functools.cache
def client():
    import anthropic

    return anthropic.Anthropic(max_retries=0)  # a retry would overrun the move budget


@functools.cache
def playbook(case_type):
    path = PLAYBOOKS / f"{case_type}.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def llm_ready():
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and os.environ.get("LLM_PROVIDER", "anthropic") == "anthropic"


_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="ege-agent")


def terms_text(case, sheet, base=None):
    """A sheet in words, index clause included (the template's describe() leaves clauses out)."""
    text = describe(sheet, base)
    if "index_clause" in case["negotiable"] and (base is None or base.get("index_clause") != sheet.get("index_clause")):
        c = sheet.get("index_clause")
        if c:
            text += (
                f", a price clause on {c['series']} ({c['material_share']:.0%} material share, "
                f"{c['deadband_pct']:g} % deadband, base {c.get('base_month')})"
            )
        else:
            text += ", a fixed price without index clause"
    return text


class EgeAgent(CseeAgent):
    def __init__(self, package=None, writer=None, params=None):
        super().__init__(package, writer, params)
        self.llm = isinstance(writer, LLMWriter) and llm_ready()
        self.pushes, self.plans = {}, {}

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
        rule = self.rule_move(case, threads, sid)
        arguments = self.arguments(case, threads, sid)
        move = self.ask_agent(case, threads, sid, rule, arguments)
        if move is not None:
            try:
                msg = self.apply(case, threads, sid, move, rule, arguments)
                if msg is not False:
                    return msg
            except Exception:
                log.exception("%s %s: agent move invalid - rule move", case["case_id"], sid)
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

    def rule_move(self, case, threads, sid):
        """Base's next ask for an open thread ({"terms", "C", "sheets"}), or None when the rules would stop."""
        ev = threads[sid]
        if latest(ev).get("status") != "open" or moves_left(case, ev) <= self.p.reserve_moves:
            return None
        std = standard_terms(ev)
        supplier = self.supplier_estimate(case, sid, std)
        sheet_id, theirs = self.their_sheet(case, ev, std, supplier)
        if not sheet_id or theirs.get("unit_price") is None:
            return None
        terms = CseeAgent.next_terms(self, case, threads, sid, theirs, std, supplier, moves_left(case, ev))
        if terms is None:
            return None
        sheets = CseeAgent.sheets(self, case, sid, terms, std, supplier)
        return {"terms": sheets[0], "C": total_cost(case, sheets[0], std, supplier), "sheets": sheets}

    def walk_risk(self, case, sid, ev):
        """Why pushing harder than the rules is unsafe now, or "": the supplier holds its price."""
        prices = [
            (m.get("term_sheets") or [{}])[0].get("terms", {}).get("unit_price")
            for m in ev
            if m.get("from") != "buyer" and m.get("term_sheets")
        ]
        if len(prices) >= 2 and prices[-1] is not None and prices[-1] == prices[-2]:
            return "it held its price"
        if HOLD_WORDS.search(latest(ev).get("body") or ""):
            return "its e-mail says the offer stands"
        return ""  # not the should-cost floor: it often sits above the supplier's own ask (P05, P02)

    # ---------- the agent turn ----------
    def ask_agent(self, case, threads, sid, rule, arguments):
        """Claude's checked Move for this thread, or None (failed, invalid, or over MOVE_BUDGET_S)."""
        t0, stop, out = time.monotonic(), {"now": False}, {}
        try:
            brief = self.brief(case, threads, sid, arguments, rule)
            tools = self.tools(case, threads, sid, arguments)
            _pool.submit(self.run_turns, case, brief, tools, arguments, out, stop, t0).result(timeout=MOVE_BUDGET_S)
        except Exception as e:
            stop["now"] = True
            log.warning("%s %s: agent failed (%s) - rule move", case["case_id"], sid, type(e).__name__)
            return None
        move = out.get("move")
        if move is None:
            log.warning("%s %s: agent made no valid move - rule move", case["case_id"], sid)
            return None
        if move.plan is not None:
            self.plans[sid] = move.plan.model_dump()
        took = time.monotonic() - t0
        log.info(
            "%s %s: agent %s in %.1fs (plan %s): %s",
            case["case_id"],
            sid,
            move.action,
            took,
            self.plans.get(sid),
            move.reason,
        )
        try:
            self.log.event("agent_move", supplier_id=sid, seconds=round(took, 1), **move.model_dump())
        except Exception:
            pass
        return move

    def run_turns(self, case, brief, tools, arguments, out, stop, t0):
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
                    move, _ = check_move(case, block.input, arguments)
                    if move is not None:  # valid: no further round trip; invalid: the tool tells Claude why
                        for name in ("opening", "closing"):
                            if (block.input.get(name) or "").strip() and not getattr(move, name):
                                log.info("%s: %s dropped by the text check: %r", case["case_id"], name,
                                         block.input[name][:300])
                        out["move"] = move
                        return
            if stop["now"] or time.monotonic() - t0 > MOVE_BUDGET_S:
                return

    def tools(self, case, threads, sid, arguments):
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
            fact = case.get("facts", {}).get(data_id) or (self.pkg.lookup(data_id) if self.pkg else None)
            return json.dumps(fact, ensure_ascii=False, default=str)[:1500] if fact else "unknown ID"

        @beta_tool
        def submit_move(
            action: Literal["counter", "ready", "accept", "walk_away"],
            term_sheets: list[dict] | None = None,
            argument_keys: list[str] | None = None,
            opening: str = "",
            closing: str = "",
            plan: dict | None = None,
            reason: str = "",
        ) -> str:
            """Our move toward this supplier. Call exactly once, as the last step; an invalid move is answered
            with the errors to fix.

            Args:
                action: "counter", "ready", "accept" or "walk_away".
                term_sheets: counter only: 1-3 packages over the negotiable fields only, main ask first.
                argument_keys: counter only: up to 3 keys from the verified list, one per data family.
                opening: counter only: at most 60 words of plain text - no digits, IDs or terms.
                closing: counter only: at most 35 words of plain text - no digits, IDs or terms.
                plan: {"anchor", "target", "walk_away"} unit prices, anchor <= target <= walk_away. Required
                    on our first move toward this supplier; afterwards only to revise it.
                reason: one sentence on why, for our log.
            """
            raw = {
                "action": action,
                "term_sheets": term_sheets or [],
                "argument_keys": argument_keys or [],
                "opening": opening,
                "closing": closing,
                "plan": plan,
                "reason": reason,
            }
            _, errors = check_move(case, raw, arguments)
            return f"Invalid move, fix and call submit_move again: {errors}" if errors else "Recorded."

        return [price_package, lookup, submit_move]

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

    def brief(self, case, threads, sid, arguments, rule):
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
            f"PLAYBOOK FOR THIS CASE TYPE:\n{playbook(case.get('type'))}",
            f"SUPPLIER {sid}: {json.dumps({k: profile.get(k) for k in keys}, ensure_ascii=False)[:3000]}",
            f"Its standard terms (apply to anything a sheet leaves out): {json.dumps(std)}",
            f"Rough full-cost estimate per unit (should-cost based, often 5 % off): {self.floor_price(st)}",
            f"YOUR PLAN FOR THIS SUPPLIER: {json.dumps(self.plans.get(sid)) if sid in self.plans else 'not set yet'}",
            "THREAD WITH THIS SUPPLIER, oldest first:",
        ]
        bodies = set(sorted(i for i, m in enumerate(ev) if m.get("from") != "buyer")[-3:])
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
        if rule:
            out.append(
                f"RULE MOVE (minimum pressure): main {json.dumps(rule['terms'])} -> C {rule['C']:,.0f}; "
                f"its alternative sheets {json.dumps(rule['sheets'][1:])}"
            )
        else:
            out.append("RULE MOVE: the rules would stop writing to this supplier now (you may still push).")
        risk = self.walk_risk(case, sid, ev)
        if risk:
            out.append(f"WALK RISK: {risk}. Code will send exactly the rule ask and allow no push.")
        out.append("VERIFIED ARGUMENTS (key, data family, sentence):")
        out += [f"{k} [{family(c)}]: {c.sentence}" for k, c in arguments.items()] or ["(none left)"]
        return "\n".join(out)

    # ---------- checking and sending the move ----------
    def apply(self, case, threads, sid, move, rule, arguments):
        """The checked message, None (thread ready), or False: use the rule move instead."""
        st, ev = self.threads[sid], threads[sid]
        std = standard_terms(ev)
        supplier = self.supplier_estimate(case, sid, std)
        sheet_id, theirs = standing(ev)
        status = latest(ev).get("status")
        c_alt = levers.alternative_cost(case)
        action = move.action
        if action != "counter" and rule is not None:
            log.info("%s %s: agent wanted %s - the rules still counter", case["case_id"], sid, action)
            return False  # stopping while the rules would still counter is a concession: rule move
        if action == "accept":
            if sheet_id and theirs.get("unit_price") is not None and must_haves_ok(case, theirs, std) and (
                total_cost(case, theirs, std) < c_alt
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
        risk = self.walk_risk(case, sid, ev)
        pushing = status in ("agreed", "final_offer")
        if pushing and (risk or not self.may_push(case, threads, sid)):
            st.ready = True
            return None
        c_theirs = total_cost(case, theirs, std, supplier) if theirs.get("unit_price") is not None else float("inf")
        sheets = []
        for raw in move.term_sheets:
            t = complete_offer(case, {**theirs, **raw})
            if t.get("unit_price") is None or t["unit_price"] <= 0 or not must_haves_ok(case, t, std):
                continue
            if total_cost(case, t, std, supplier) >= c_theirs or t in sheets:
                continue  # dearer than what it already offers: pointless
            sheets.append(t)
        if not sheets:
            return False
        main = sheets[0]
        if pushing and len(case["suppliers"]) == 1:
            main["unit_price"] = round(max(main["unit_price"], theirs["unit_price"] * (1 - SOLO_PUSH_MAX)), 2)
        elif not pushing and st.our_prices:
            main["unit_price"] = round(max(main["unit_price"], st.our_prices[-1]), 2)  # never step back
        if rule and (risk or total_cost(case, main, std, supplier) > rule["C"] + 0.01):
            reason = risk or "softer than the rules"
            log.info("%s %s: agent ask replaced by the rule ask (%s)", case["case_id"], sid, reason)
            main = dict(rule["terms"])
        c_main = total_cost(case, main, std, supplier)
        sheets = [main] + [t for t in sheets[1:] if t != main and total_cost(case, t, std, supplier) <= c_main]
        if pushing:
            self.pushes[sid] = self.pushes.get(sid, 0) + 1
        claims, families = [], set()
        for k in move.argument_keys:  # check_move already refused duplicates; kept here as the last line
            c = arguments.get(k)
            if c is not None and family(c) not in families and len(claims) < MAX_ARGUMENTS:
                claims.append(c)
                families.add(family(c))
        for c in claims:
            key = tuple(c.ids) if c.kind != "rival" else (sid, *c.ids)
            self.used_ids.add(key)
            self.used_ids.update(i for i in c.ids if c.kind != "rival")
        ask_breakdown = not st.asked_breakdown and not st.breakdown
        st.asked_breakdown = st.asked_breakdown or ask_breakdown
        st.ready = False
        st.our_prices.append(main["unit_price"])
        return {
            "subject": f"Re: {case['title']}"[:300],
            "body": self.render(case, ev, move, claims, sheets, ask_breakdown),
            "term_sheets": [{"terms": t} for t in sheets],
            "refs": [i for c in claims for i in c.ids][:20],
        }

    @staticmethod
    def render(case, ev, move, claims, sheets, ask_breakdown):
        """The e-mail: Claude's checked paragraphs around everything code states - arguments word for word,
        every package from the final sheets. No figure or ID here comes from the model."""
        first = not any(m.get("from") == "buyer" for m in ev)
        prices = [
            (m.get("term_sheets") or [{}])[0].get("terms", {}).get("unit_price")
            for m in ev
            if m.get("from") != "buyer" and m.get("term_sheets")
        ]
        moved = len(prices) >= 2 and None not in prices[-2:] and prices[-1] < prices[-2]
        if first:
            default = OPENERS.get(case.get("type"), "Thank you for your offer.")
        else:  # thank it for a step only if it made one
            default = "Thank you for your reply and for the step you made." if moved else "Thank you for your reply."
        lines = ["Good day,", "", move.opening or default]
        lines += [c.sentence for c in claims]
        lines.append(f"We propose {terms_text(case, sheets[0])}.")
        lines += [f"Alternatively: {terms_text(case, s, sheets[0])}." for s in sheets[1:]]
        if ask_breakdown:
            lines.append("Could you send us a cost breakdown for this part, so we can understand your position?")
        if move.closing:
            lines.append(move.closing)
        lines += ["", SIGN]
        body = "\n".join(lines)
        allowed = {i for c in claims for i in c.ids}
        stray = [m.group(0) for m in ID_RE.finditer(body) if m.group(0) not in allowed]
        if stray:  # cannot happen (claims carry their own IDs, free text has none): refuse rather than send
            raise ValueError(f"unexpected data IDs in the e-mail: {stray}")
        return body

    def valid_offer_beats(self, case, threads, s, c_alt):
        sheet_id, terms = standing(threads[s])
        std = standard_terms(threads[s])
        return (
            bool(sheet_id)
            and terms.get("unit_price") is not None
            and must_haves_ok(case, terms, std)
            and total_cost(case, terms, std) < c_alt
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
