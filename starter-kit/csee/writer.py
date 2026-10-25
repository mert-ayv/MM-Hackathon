"""Words for the e-mail. The numbers are already decided (term sheets, claims); the writer only
explains them. TemplateWriter needs no model; LLMWriter lets a model write in the supplier's
register and falls back to the template if it is slow or fails. Claim sentences are always kept
verbatim, so the arena can check them.
"""

import json
import logging
import re
import time

from arena_kit.agents.llm import ID_RE
from arena_kit.play import latest

log = logging.getLogger("csee")
SIGN = "Best regards\nHollerau Pumpenwerke GmbH, Purchasing"
GREETING_RE = re.compile(r"^(best|kind|warm|with best|many thanks|thanks|yours|sincerely|regards|mit freundlichen)", re.I)


def before_signature(body, text):
    """Insert `text` before the closing greeting, whatever greeting the model chose ("Kind regards" ...). Lever and
    pledge lines used to land after an AI-written signature (7 logged e-mails; the jury reads every replay)."""
    lines = body.rstrip().split("\n")
    sign = max((i for i, ln in enumerate(lines) if "Hollerau Pumpenwerke" in ln), default=None)
    if sign is None:
        return body.rstrip() + "\n\n" + text
    at = sign - 1 if sign > 0 and GREETING_RE.match(lines[sign - 1].strip()) else sign
    head = "\n".join(lines[:at]).rstrip()
    return head + "\n\n" + text + "\n\n" + "\n".join(lines[at:])
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
    parts = [f"EUR {sheet['unit_price']:.2f} per unit"] if sheet.get("unit_price") is not None else []
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


NOTE_START = re.compile(
    r"^\s*(-{3,}|_{3,}|\*{3,})\s*$|"
    r"^\s*\**\s*(internal note|note for the (purchasing )?team|note to the (purchasing )?team|"
    r"notes? (for|to) (the )?(purchasing |internal |our )?team|notes? for (the )?(purchasing|internal)|"
    r"for the purchasing team)\b|\(not part of the e-?mail\)",
    re.I,
)


# a closing line the model writes in place of ours ("Kind regards", "Best wishes", ...)
CLOSING = re.compile(r"^\s*((best|kind|warm|warmest|many)\s+(regards|wishes)|regards|sincerely|yours sincerely|"
                     r"with (best|kind) regards|mit freundlichen grüßen|viele grüße|best)\s*,?\s*$", re.I)


def insert_before_signature(text, line):
    """`line` above the sign-off, whatever closing the model wrote: replacing only our own "Best regards" block put
    checked claims under a "Kind regards" signature, followed by a second signature (15 e-mails, P02/P08)."""
    lines = text.rstrip().splitlines()
    company = SIGN.splitlines()[-1]
    end = next((i for i in range(len(lines) - 1, -1, -1) if company in lines[i]), None)
    if end is None:
        return text.rstrip() + "\n" + line + "\n\n" + SIGN
    start = end
    for i in range(end - 1, max(end - 3, -1), -1):  # the closing line sits just above the company line
        if CLOSING.match(lines[i]):
            start = i
            break
    head = "\n".join(lines[:start]).rstrip()
    return head + "\n" + line + "\n\n" + "\n".join(lines[start:])


def strip_notes(text):
    """The model sometimes appends a note to our own team after the e-mail ("--- Internal note for the purchasing
    team (not part of the e-mail): ... the profile says the MD cannot sign margin cuts", P11 v18 R1/R4) or starts
    with a "Subject:" line. Both went to the supplier verbatim. Keep the e-mail only."""
    lines = text.splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    for i, ln in enumerate(lines):
        if NOTE_START.search(ln) and i > 0:
            lines = lines[:i]
            break
    return "\n".join(lines).rstrip()


FIXED_WORDS = {  # a term the case fixes, as the model would name it (xc_answer: never promise movement on it)
    "payment_days": r"payment",
    "volume_per_year": r"volume|quantit",
    "lead_time_days": r"lead[- ]time",
    "contract_months": r"contract (?:term|length|duration)|term of the (?:contract|agreement)",
    "effective_date": r"effective date|start date|validity",
    "index_clause": r"index clause|escalat|preisgleit|indexation",
    "incoterm": r"incoterm|delivery terms",
    "ppm_commitment": r"\bppm\b",
}
PROMISE_RE = re.compile(  # a promise of movement later, not the package sentence ("We propose EUR ..., 14 days lead time")
    r"come back|revert|get back|follow up|return to (?:you|this)|separately|(?:open|willing|prepared|happy|glad|ready) to "
    r"(?:discuss|look|talk|explore|consider|review)|will (?:address|reply|respond|look|review|consider|discuss|explore)|"
    r"concrete proposal|welcome your (?:concrete )?proposal|revisit",
    re.I,
)
FIXED_SAID_RE = re.compile(r"\bfixed\b|not part of|not open|not negotiable|cannot (?:be )?chang|stays? (?:at|as)", re.I)


def fixed_term_words(case):
    """{field: value} of the terms the case fixes (fixed_terms, not negotiable)."""
    fixed = case.get("fixed_terms") or {}
    return {f: v for f, v in fixed.items() if f not in case.get("negotiable", []) and v is not None and f in FIXED_WORDS}


def strip_fixed_promises(text, case, keep=()):
    """Drop every sentence that promises movement on a term the case fixes ("we will come back to you with a concrete
    proposal on payment timing": P11 v18, three times on a fixed payment term; the bot waited and held). Sentences in
    `keep` (claims, answers) stay as they are; a sentence that states the term as fixed stays too."""
    fields = fixed_term_words(case)
    if not fields or not text:
        return text
    rx = re.compile("|".join(FIXED_WORDS[f] for f in fields), re.I)
    out = []
    for para in text.split("\n"):
        sents = re.split(r"(?<=[.!?])\s+", para)
        kept = [
            s for s in sents
            if not s or s in keep or not rx.search(s) or not PROMISE_RE.search(s) or FIXED_SAID_RE.search(s)
        ]
        out.append(" ".join(kept))
    return "\n".join(out)


class LLMWriter:
    """A model writes the body around fixed facts; the template is the safety net."""

    SYSTEM = """You write e-mails for the purchasing team of Hollerau Pumpenwerke, a German pump maker,
to an industrial supplier. The numbers and arguments are decided; you only word them.
Rules: plain text, at most 140 words, polite and firm, no placeholders, no markdown.
Include every CLAIM sentence verbatim (they carry data IDs the supplier checks).
State each proposed package exactly as given. Never reveal urgency, a budget, a deadline, or that we
lack alternatives. Never invent figures. Match the supplier's register (owner of a family firm,
sales rep of a group, etc.) using the PROFILE. If they asked a question, answer it briefly if the
facts allow. Sign as "Hollerau Pumpenwerke GmbH, Purchasing". Output only the e-mail body: no subject line,
no notes or comments to our own team - everything you write is sent to the supplier."""

    def __init__(self, complete, budget_s=25.0):
        self.complete, self.budget_s, self.fallback = complete, budget_s, TemplateWriter()

    def write(self, case, agent, sid, events, sheets, claims, ask_breakdown, focus=""):
        """`focus`: optional, what a strategist wants this e-mail to stress (agents/ege.py); base passes none."""
        draft = self.fallback.write(case, agent, sid, events, sheets, claims, ask_breakdown)
        profile = agent.threads[sid].intel.profile
        last = latest(events)
        # the same on every move of this thread: first, so it can be a cached prompt prefix (csee/llm.py)
        stable = "\n".join(
            [
                f"CASE: {case.get('title')} ({case.get('type')}, goal {case['buyer'].get('category_goal')})",
                f"PROFILE: {json.dumps({k: profile.get(k) for k in ('name', 'situation', 'what_it_values', 'persona', 'arguments_to_avoid')}, ensure_ascii=False)[:2500]}",
            ]
        )
        xc_answer = bool(getattr(getattr(agent, "p", None), "xc_answer", False))
        fixed = fixed_term_words(case) if xc_answer else {}
        user = "\n".join(
            [
                *([f"WHAT TO STRESS (our plan for this e-mail): {focus[:400]}"] if focus else []),
                *(
                    [
                        "FIXED TERMS (set by the case, not negotiable; state them as fixed if asked, never offer to come "
                        "back with a proposal on them): " + ", ".join(f"{k}={v}" for k, v in fixed.items())
                    ]
                    if fixed
                    else []
                ),
                f"THEIR LAST E-MAIL:\n{(last.get('body') or '')[:1500]}",
                f"PACKAGES TO PROPOSE: {json.dumps(sheets)}",
                "CLAIMS (verbatim):\n" + "\n".join(c.sentence for c in claims),
                f"ASK FOR COST BREAKDOWN: {ask_breakdown}",
                f"TEMPLATE DRAFT (improve it):\n{draft}",
            ]
        )
        t0 = time.monotonic()
        try:
            if getattr(self.complete, "parts", False):
                text = self.complete(self.SYSTEM, [stable, user]).strip()
            else:
                text = self.complete(self.SYSTEM, stable + "\n" + user).strip()
        except Exception as e:
            log.warning("writer model failed (%s): template used", e)
            return draft
        if time.monotonic() - t0 > self.budget_s or not text:
            return draft
        text = strip_notes(text)
        if SIGN.splitlines()[-1] not in text:  # the note was after the signature or swallowed it: sign again
            text = text.rstrip() + "\n\n" + SIGN
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
        # an ID the model added and we dropped can leave "the washer award ()." behind (3 of 337 practice e-mails;
        # the jury reads every replay): drop empty brackets and the space before them
        text = re.sub(r"\s*\(\s*[,;]?\s*\)", "", text)
        if fixed:  # xc_answer: no "we will come back to you on payment" when payment is fixed
            text = strip_fixed_promises(text, case, keep={c.sentence for c in claims})
        for c in claims:  # the checked sentences must survive word for word
            if c.sentence not in text:
                text = insert_before_signature(text, c.sentence)
        return text[:8000]
