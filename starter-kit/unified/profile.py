"""What we know about a supplier, from the data package, the case file and its opening e-mail only - the same
way for practice suppliers and the final's strangers (no hand-written profiles).

`profile_for(supplier_id, case, package, opening)` returns the fields the agent and the writer use:
name, country, owner_type, staff (the simulator's supplier personality), pressures (keyword rules over its
documents, news, quote remarks and opening e-mail, plus finance and our payment behaviour), quality (latest
scorecard), and for the LLM writer a one-line situation, what it values and a persona from its own e-mail.
"""

import logging
import re
from collections import defaultdict

log = logging.getLogger("unified")

# keyword rules over the supplier's own words: (pressure type, regex)
PRESSURE_RULES = [
    (
        "cash",
        r"cash|liquidit|payment within \d+|within (10|14) days|pay(ing|ment)? (faster|earlier|sooner)|skonto|"
        r"cash discount|prepay|covenant|credit (line|downgrade|watch|rating)|insolven|restructur|bank",
    ),
    (
        "capacity",
        r"fully booked|full order book|capacity (is )?(tight|limited|constrain|stretched)|allocation|"
        r"no free capacity|bottleneck|(longer|extended?) lead time|lead times? (extend|longer)|shortage|order backlog",
    ),
    (
        "utilisation",
        r"free capacity|idle|short.?time|kurzarbeit|under.?utili|utili[sz]ation (fell|dropped|is low|low)|"
        r"second shift|new customers|looking for (work|volume|business)|"
        r"order intake (fell|down|dropped)|fill (our|the)",
    ),
    (
        "volume",
        r"more volume|additional volume|volume (commitment|security|guarantee)|bigger share|more business|"
        r"keep(ing)? (the|our|your) volume|binding (volume|commitment)|annual commitment",
    ),
    ("energy", r"energy|electricity|gas price|power price|strom"),
    ("labour", r"wage|labou?r cost|collective (wage )?agreement|tarif|staff cost|personnel cost|ig metall"),
    ("quality", r"\b8d\b|complaint|ppm|quality (issue|problem|escalation)|reject"),
    ("succession", r"succession|retire|successor|next generation"),
    ("ownership", r"new owner|acqui|takeover|private equity|sold to|merger|investor"),
    (
        "competition",
        r"competit|cheaper offer|second source|alternative supplier|lost (an? )?(customer|order)|"
        r"price war|asian",
    ),
    ("other", r"surcharge|alloy|copper|nickel|steel price|index clause|material cost|raw material"),
]
NEWS_TOPIC = {
    "credit_downgrade": "cash",
    "credit_watch": "cash",
    "restructuring": "cash",
    "free_capacity": "utilisation",
    "short_time_work": "utilisation",
    "full_order_book": "capacity",
    "allocation": "capacity",
    "chip_shortage": "capacity",
    "big_order": "capacity",
    "succession": "succession",
    "new_owner": "ownership",
    "energy_contract": "energy",
}
LEGAL_COUNTRY = [  # legal form or place in the name -> country
    (r"s\.\s?r\.\s?o\.|\ba\.\s?s\.|česk|praha|brno", "CZ"),
    (r"sp\.\s?z\s?o\.\s?o\.|\bs\.a\.|polsk|wroc|pozna|krak", "PL"),
    (r"\bkft\b|\bzrt\b|magyar|budapest|győr", "HU"),
    (r"a\.ş\.|\ba\.s\.\b|ltd\.? şti|sanayi|ticaret|türk|istanbul|bursa", "TR"),
    (r"co\.,? ltd|china|shanghai|ningbo|jiangsu|zhejiang|qingdao", "CN"),
    (r"österreich|austria|wien|graz|linz|salzburg|tirol|kärnten|steiermark|vorarlberg|ges\.m\.b\.h", "AT"),
    (r"schweiz|switzerland|zürich|zurich|basel|bern|\bsa\b.*\bag\b", "CH"),
]
NATIONALITY = {
    "polish": "PL",
    "czech": "CZ",
    "hungarian": "HU",
    "turkish": "TR",
    "chinese": "CN",
    "austrian": "AT",
    "swiss": "CH",
    "german": "DE",
    "bavarian": "DE",
}
# what a pressure says it wants from us (for the writer's prompt)
VALUES = {
    "cash": "faster payment (cash)",
    "utilisation": "volume security",
    "volume": "volume security",
    "capacity": "lead time / capacity flexibility",
    "quality": "quality recognition",
    "succession": "long contract / multi-year visibility",
    "ownership": "long contract / multi-year visibility",
    "competition": "volume security",
}
KINDS = {
    "price_increase": "announces a price increase",
    "renewal": "renews an expiring contract",
    "rfq": "quotes in an RFQ",
    "raw_material": "passes on raw-material costs",
    "capacity": "is short of capacity",
    "quality": "has a quality escalation",
    "bundling": "bids for a bundle",
}


def _q(pkg, sql, params=()):
    try:
        return pkg.query(sql, params) if pkg else []
    except Exception as e:  # a missing table must never cost a case
        log.debug("profile query failed: %s", e)
        return []


def _lookup(case, pkg, ref):
    try:
        return (case.get("facts") or {}).get(ref) or (pkg.lookup(ref) if pkg else None)
    except Exception:
        return None


def opening_text(opening):
    """E-mail body + attachment texts of an opening message (dict), a thread (list) or plain text."""
    if not opening:
        return "", {}
    if isinstance(opening, str):
        return opening, {}
    msgs = opening if isinstance(opening, list) else [opening]
    msgs = [m for m in msgs if m.get("from") != "buyer"][:1]
    body, pdf = "", ""
    for m in msgs:
        body += (m.get("body") or "") + "\n"
        for att in m.get("attachments") or []:
            if att.get("text"):
                pdf += att["text"] + "\n"
    std = {}
    if pdf:
        try:
            from arena_kit.docs import quote_terms

            std = quote_terms(pdf).get("standard", {})
        except Exception:
            std = {}
    meta = {"standard": std, "pdf": pdf, "body": body}
    if msgs:
        meta["signals"] = msgs[0].get("signals") or {}
    return body + "\n" + pdf, meta


def _guess_name(case, text, sid, pdf=""):
    first = next((x.strip() for x in (pdf or "").splitlines() if x.strip()), "")
    if re.search(r"GmbH|AG\b|KG\b|s\.\s?r\.\s?o\.|Sp\. z o\.o\.|Kft|A\.Ş\.|Ltd|e\.K\.|S\.A\.", first):
        return first
    for line in reversed([x.strip() for x in (text or "").splitlines() if x.strip()]):
        m = re.search(
            r"(?:^|,\s*)([^,]*?(GmbH|AG|KG|SE|s\.\s?r\.\s?o\.|Sp\. z o\.o\.|Kft\.?|A\.Ş\.|Ltd\.?|e\.K\.|S\.A\.)[^,]*)$",
            line,
        )
        if m:
            return m.group(1).strip()
    m = re.search(r"negotiate for Hollerau Pumpenwerke with (.+?)\.(\s|$)", case.get("briefing") or "")
    if m and len(case.get("suppliers") or []) == 1:
        return m.group(1).strip()
    return sid


def _guess_country(name, case, text):
    low = f"{name}".lower()
    for rx, c in LEGAL_COUNTRY:
        if re.search(rx, low):
            return c
    if len(case.get("suppliers") or []) == 1:
        brief = (case.get("briefing") or "").lower()
        for word, c in NATIONALITY.items():
            if re.search(rf"\b{word}\b", brief) and c != "DE":
                return c
    sig = (text or "").lower()[-600:]
    for rx, c in LEGAL_COUNTRY:
        if re.search(rx, sig):
            return c
    return "DE"


def _guess_owner(name, text, staff):
    n, t = (name or "").lower(), (text or "").lower()
    if re.search(r"\bag\b|\bse\b|group|holding|konzern|international", n) or re.search(
        r"key account|head office|group", t
    ):
        return "group"
    if re.search(r"e\.\s?k\.|inhaber", n):
        return "founder"
    if re.search(r"gmbh & co\.? kg|& söhne|& sohn|family|familie", n + t):
        return "family"
    if re.search(r"\bowner\b|inhaber|managing director|geschäftsführer", t[-500:]):
        return "founder" if (staff or 0) and staff < 60 else "family"
    return None


def _sources(case, pkg, sid, otext):
    """(date, id or '', text) of everything this supplier said or that is said about it."""
    out = []
    for d in _q(pkg, "SELECT id, date, kind, subject FROM documents WHERE supplier_id = ? ORDER BY date", (sid,)):
        try:
            body = pkg.document(d["id"])
        except Exception:
            body = ""
        if d.get("kind") in ("email", "letter", "call_note", "meeting_note", "memo") or body:
            out.append((d["date"] or "", d["id"], f"{d.get('subject') or ''}\n{body}"))
    for n in _q(pkg, "SELECT id, date, topic, headline, body FROM news WHERE supplier_id = ?", (sid,)):
        if n.get("topic") != "noise":
            out.append(
                (n["date"] or "", n["id"], f"[{n.get('topic')}] {n.get('headline') or ''} {n.get('body') or ''}")
            )
    for q in _q(pkg, "SELECT id, quote_date, remarks FROM quotes WHERE supplier_id = ? AND remarks != ''", (sid,)):
        out.append((q["quote_date"] or "", q["id"], q["remarks"]))
    for h in _q(pkg, "SELECT date, note FROM negotiation_history WHERE supplier_id = ? AND note != ''", (sid,)):
        out.append((h["date"] or "", "", h["note"]))
    # the Sunday release and the case's own facts (new letters, news) that name this supplier
    facts = dict(case.get("facts") or {})
    for ref in (pkg.ids("news:") + pkg.ids("doc:")) if pkg else []:
        if ref not in facts and not any(ref == s[1] for s in out):
            f = _lookup(case, pkg, ref) or {}
            if f.get("supplier") == sid and str(f.get("root") or "") and f.get("table"):
                facts[ref] = f
    for ref, f in facts.items():
        if isinstance(f, dict) and (f.get("supplier") == sid or f.get("supplier_id") == sid):
            text = " ".join(str(f.get(k) or "") for k in ("title", "headline", "topic", "body", "subject", "text"))
            if f.get("asked_pct"):
                text += f" asks +{f['asked_pct']}%"
            out.append((f.get("date") or "9999", ref, text))
    if otext.strip():
        out.append(("9999", "", otext))  # the opening e-mail and quote PDF: the freshest words
    return out


def _pressures(sources, intel_row, late_days, news_topics):
    hits = defaultdict(list)  # type -> [(date, id, snippet)]
    for date, ref, text in sources:
        low = text.lower()
        for typ, rx in PRESSURE_RULES:
            m = re.search(rx, low)
            if m:
                a = max(0, m.start() - 60)
                hits[typ].append((date, ref, re.sub(r"\s+", " ", text[a : m.end() + 60]).strip()))
    for topic, ref, date in news_topics:
        if topic in NEWS_TOPIC:
            hits[NEWS_TOPIC[topic]].append((date, ref, f"news topic {topic}"))
    if intel_row:
        eq, ci, ci0 = (
            intel_row.get("equity_ratio_pct"),
            intel_row.get("credit_index"),
            intel_row.get("credit_index_12m_ago"),
        )
        if eq is not None and eq < 20:
            hits["cash"].append(("9999", "", f"thin equity ratio {eq:.1f} %"))
        if ci and ci0 and ci - ci0 >= 15:
            hits["cash"].append(("9999", "", f"credit index worsened {ci0} -> {ci}"))
    if late_days is not None and late_days > 5:
        hits["cash"].append(("9999", "", f"we pay on average {late_days:.0f} days late"))
    out = []
    for typ, hs in hits.items():
        recent = [h for h in hs if h[0] >= "2025-10"]
        if not recent and len(hs) < 2:
            continue  # one old mention is noise
        ids = list(dict.fromkeys(h[1] for h in hs if h[1]))[:3]
        best = (recent or hs)[-1]
        out.append({"type": typ, "evidence": best[2][:200], "ids": ids, "_weight": len(recent) * 2 + len(hs)})
    out.sort(key=lambda p: -p["_weight"])
    return out


def _quality(pkg, sid):
    rows = _q(
        pkg,
        "SELECT id, otd_pct, ppm, colour FROM scorecards WHERE supplier_id = ? ORDER BY quarter DESC LIMIT 4",
        (sid,),
    )
    if not rows:
        return {}
    r = rows[0]
    return {
        "latest_scorecard_id": r["id"],
        "otd_pct": r["otd_pct"],
        "ppm": r["ppm"],
        "colour": r["colour"],
        "trend": " -> ".join(x["colour"] or "?" for x in reversed(rows)),
    }


def _persona(otext, owner):
    low = otext.lower()
    style = []
    if re.search(r"dear sir or madam|sehr geehrte|yours faithfully|kind regards", low):
        style.append("formal")
    if re.search(r"guten tag|viele grüße|best wishes|cheers|hi ", low):
        style.insert(0, "personal")
    role = re.findall(
        r"(?m)^(owner|managing director|key account manager|inside sales|sales director|head of sales|"
        r"geschäftsführer|inhaber)[^\n]*",
        low,
    )
    who = role[-1] if role else ("owner" if owner in ("founder", "family") else "sales / key account manager")
    return {
        "who_writes": who,
        "style": ", ".join(style) or "business-like",
        "decision_making": "approval ladder" if owner == "group" else "owner decides, fast",
    }


def build_profile(supplier_id, case, pkg, opening=None):
    sid, case = supplier_id, case or {}
    otext, meta = opening_text(opening)
    master = (_q(pkg, "SELECT * FROM suppliers WHERE id = ?", (sid,)) or [{}])[0]
    irow = (_q(pkg, "SELECT * FROM supplier_intel WHERE supplier_id = ?", (sid,)) or [{}])[0]
    name = master.get("name") or _guess_name(case, meta.get("body") or otext, sid, meta.get("pdf"))
    country = master.get("country") or _guess_country(name, case, otext)
    owner = irow.get("owner_type") or _guess_owner(name, otext, irow.get("staff"))
    late = _q(
        pkg,
        "SELECT avg(julianday(paid_date) - julianday(due_date)) AS late, count(*) AS n FROM invoices "
        "WHERE supplier_id = ? AND paid_date IS NOT NULL AND paid_date >= '2025-10-01'",
        (sid,),
    )
    late_days = late[0]["late"] if late and late[0].get("n") else None
    news = [
        (n["topic"], n["id"], n["date"])
        for n in _q(pkg, "SELECT id, date, topic FROM news WHERE supplier_id = ?", (sid,))
    ]
    pressures = _pressures(_sources(case, pkg, sid, otext), irow, late_days, news)
    for p in pressures:
        p.pop("_weight", None)
    values = list(dict.fromkeys(VALUES[p["type"]] for p in pressures if p["type"] in VALUES))[:4]
    spend = _q(pkg, "SELECT spend_eur FROM spend_cube WHERE supplier_id = ? ORDER BY fiscal_year DESC LIMIT 1", (sid,))
    turnover = irow.get("turnover_eur")
    share = round(100 * spend[0]["spend_eur"] / turnover, 1) if spend and turnover else None
    alternatives = sorted(
        {
            r["supplier_id"]
            for part in case.get("parts") or []
            for r in _q(
                pkg, "SELECT supplier_id FROM sourcing WHERE part_id = ? AND status IN ('active', 'qualified')", (part,)
            )
            if r["supplier_id"] != sid
        }
    )
    situation = (
        f"{name}: {owner or 'unknown-owner'} supplier ({country}), {KINDS.get(case.get('type'), 'in this case')}."
    )
    if share is not None:
        situation += f" We are {share} % of its turnover."
    if alternatives:
        situation += f" We have {len(alternatives)} qualified alternative supplier(s) for these parts."
    if pressures:
        situation += " Signals: " + "; ".join(f"{p['type']} ({p['evidence'][:80]})" for p in pressures[:3]) + "."
    return {
        "supplier_id": sid,
        "name": name,
        "country": country,
        "owner_type": owner,
        "staff": irow.get("staff"),
        "pressures": pressures,
        "quality": _quality(pkg, sid),
        "situation": situation,
        "what_it_values": values,
        "persona": _persona(otext, owner),
        "our_share_pct": share,  # spend_cube / supplier_intel: how much it needs us
        "alternatives": alternatives,  # sourcing: qualified second sources for its parts
        "source": "data",
    }


def profile_for(supplier_id, case, package, opening=None):
    """intel.build's profile for every supplier. Never raises: worst case {}."""
    try:
        return build_profile(supplier_id, case, package, opening)
    except Exception:
        log.exception("profile %s failed", supplier_id)
        return {}
