"""Words for the e-mail. The numbers are already decided (term sheets, claims); the writer only
explains them. TemplateWriter needs no model; LLMWriter lets a model write in the supplier's
register and falls back to the template if it is slow or fails. Claim sentences are always kept
verbatim, so the arena can check them.
"""

import json
import logging
import time

from arena_kit.agents.llm import ID_RE
from arena_kit.play import latest

log = logging.getLogger("csee")
SIGN = "Best regards\nHollerau Pumpenwerke GmbH, Purchasing"
OPENERS = {
    "price_increase": "Thank you for your letter. We cannot accept an increase of this size.",
    "raw_material": "Thank you for your offer. We have reviewed the base price and the surcharge carefully.",
    "renewal": "Thank you for your offer for the renewal. We value our cooperation and want to continue it on competitive terms.",
    "rfq": "Thank you for your quote.",
    "bundling": "Thank you for your offer for the bundle.",
    "capacity": "Thank you for your message on the allocation. We want to find a reliable arrangement with you.",
    "quality": "Thank you for your reply. The quality situation has to improve, and the terms must reflect it.",
}
FIELD_WORDS = {
    "payment_days": lambda v: f"payment at {v} days net",
    "contract_months": lambda v: f"a {v}-month agreement",
    "volume_per_year": lambda v: f"{v:,} units a year",
    "lead_time_days": lambda v: f"{v} days lead time",
    "effective_date": lambda v: f"valid from {v}",
    "incoterm": lambda v: f"{v} delivery",
    "ppm_commitment": lambda v: f"a {v} ppm quality commitment",
    "chargeback_eur_per_complaint": lambda v: f"EUR {v:.0f} chargeback per complaint",
    "tooling_eur": lambda v: f"tooling EUR {v:,.0f}",
}


def describe(sheet, base=None):
    """One sheet in words; with `base`, only what differs from it."""
    parts = [f"EUR {sheet['unit_price']:.2f} per unit"]
    for k, v in sheet.items():
        if k == "unit_price" or v is None or k == "index_clause":
            continue
        if base is not None and base.get(k) == v:
            continue
        if k in FIELD_WORDS:
            parts.append(FIELD_WORDS[k](v))
    return ", ".join(parts)


class TemplateWriter:
    def write(self, case, agent, sid, events, sheets, claims, ask_breakdown):
        first = sum(m.get("from") == "buyer" for m in events) == 0
        lines = ["Good day,", ""]
        if first:
            lines.append(OPENERS.get(case.get("type"), "Thank you for your offer."))
        else:
            lines.append("Thank you for your reply and for the step you made.")
        for c in claims:
            lines.append(c.sentence)
        if len(sheets) == 1:
            lines.append(f"We propose {describe(sheets[0])}.")
        else:
            lines.append(f"We propose {describe(sheets[0])}.")
            for s in sheets[1:]:
                lines.append(f"Alternatively: {describe(s, sheets[0])}.")
        if ask_breakdown:
            lines.append("Could you send us a cost breakdown for this part, so we can understand your position?")
        lines += ["", SIGN]
        return "\n".join(lines)


class LLMWriter:
    """A model writes the body around fixed facts; the template is the safety net."""

    SYSTEM = """You write e-mails for the purchasing team of Hollerau Pumpenwerke, a German pump maker,
to an industrial supplier. The numbers and arguments are decided; you only word them.
Rules: plain text, at most 140 words, polite and firm, no placeholders, no markdown.
Include every CLAIM sentence verbatim (they carry data IDs the supplier checks).
State each proposed package exactly as given. Never reveal urgency, a budget, a deadline, or that we
lack alternatives. Never invent figures. Match the supplier's register (owner of a family firm,
sales rep of a group, etc.) using the PROFILE. If they asked a question, answer it briefly if the
facts allow. Sign as "Hollerau Pumpenwerke GmbH, Purchasing"."""

    def __init__(self, complete, budget_s=25.0):
        self.complete, self.budget_s, self.fallback = complete, budget_s, TemplateWriter()

    def write(self, case, agent, sid, events, sheets, claims, ask_breakdown, focus=""):
        """`focus`: optional, what a strategist wants this e-mail to stress (agents/ege.py); base passes none."""
        draft = self.fallback.write(case, agent, sid, events, sheets, claims, ask_breakdown)
        profile = agent.threads[sid].intel.profile
        last = latest(events)
        user = "\n".join(
            [
                *([f"WHAT TO STRESS (our plan for this e-mail): {focus[:400]}"] if focus else []),
                f"CASE: {case.get('title')} ({case.get('type')}, goal {case['buyer'].get('category_goal')})",
                f"PROFILE: {json.dumps({k: profile.get(k) for k in ('name', 'situation', 'what_it_values', 'persona', 'arguments_to_avoid')}, ensure_ascii=False)[:2500]}",
                f"THEIR LAST E-MAIL:\n{(last.get('body') or '')[:1500]}",
                f"PACKAGES TO PROPOSE: {json.dumps(sheets)}",
                "CLAIMS (verbatim):\n" + "\n".join(c.sentence for c in claims),
                f"ASK FOR COST BREAKDOWN: {ask_breakdown}",
                f"TEMPLATE DRAFT (improve it):\n{draft}",
            ]
        )
        t0 = time.monotonic()
        try:
            text = self.complete(self.SYSTEM, user).strip()
        except Exception as e:
            log.warning("writer model failed (%s): template used", e)
            return draft
        if time.monotonic() - t0 > self.budget_s or not text:
            return draft
        allowed = {i for c in claims for i in c.ids}
        allowed |= {s["term_sheet_id"] for m in events for s in m.get("term_sheets") or [] if s.get("term_sheet_id")}

        def scrub(m):  # any ID the model added on its own is dropped: unknown IDs cost trust
            return m.group(0) if m.group(0) in allowed else ""

        text = ID_RE.sub(scrub, text)
        # claim IDs belong only to the verbatim claim sentences: the model may repeat an ID next to a
        # paraphrased figure, which would read as a wrong figure ("contradicted")
        keep = {f"\x00{i}\x00": c.sentence for i, c in enumerate(claims)}
        for k, sentence in keep.items():
            text = text.replace(sentence, k)
        text = ID_RE.sub("", text)
        for k, sentence in keep.items():
            text = text.replace(k, sentence)
        for c in claims:  # the checked sentences must survive word for word
            if c.sentence not in text:
                text = text.replace(SIGN, "").rstrip() + "\n" + c.sentence + "\n\n" + SIGN
        return text[:8000]
