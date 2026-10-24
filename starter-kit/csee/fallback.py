"""A profile for a supplier nobody profiled by hand: the Live Final's hidden cases bring strangers.

`auto_profile(supplier_id, case, package, opening)` returns a profile in the `profiles/SCHEMA.md` shape,
marked `"source": "auto"` and `"confidence": "low"`, from three layers:

1. **Data** (deterministic): supplier master, intel, spend, sourcing, should-cost, POs, invoices,
   scorecards, contracts, quotes, negotiation history, documents and news for this supplier_id; the
   case file (parts, `cost:` facts, category goal, `case.facts` naming the supplier); the opening
   e-mail and quote PDF (standard terms, validity, the reasons it states). Keyword rules turn text
   into pressures (cash, capacity, utilisation, energy, ...).
2. **Archetype priors** from the 46 curated profiles (`profiles/_archetypes.json`, regenerate with
   `uv run python -m csee.fallback archetypes`), grouped by category x owner type x country group:
   settle-to-ask ratio, share with a cash pressure, what it values, tradeables, persona style,
   price-to-should-cost ratio. They fill what the data does not say.
3. **Optional model** (`enrich_async`): a time-boxed Haiku call over the opening e-mail, the quote
   remarks and the case facts that refines situation, pressures and persona. It merges into the
   profile dict in place only if it finishes in time; the agent reads the profile on every move, so
   it uses the result once it is there and never waits for it. Off unless CSEE_ENRICH=1.

Stage 1 (case file, before `POST /sessions`) and stage 2 (opening e-mail + quote PDF) are the same
call with and without `opening`; both take a few milliseconds.

Hook: `intel.build` calls `profile_for` when no curated profile exists, so the 46 curated suppliers
behave exactly as before.
"""

import json
import logging
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("csee")
PROFILES = Path(__file__).parent / "profiles"
ARCHETYPES = PROFILES / "_archetypes.json"
# use the price-heuristic floor as the agent's full cost: off, it lost 0.016 in the local simulator
FEED_QUOTE_FLOOR = False
PRIOR_PRESSURE_SHARE = 0.5  # a stranger gets a pressure most similar suppliers have

# company.md: full cost relative to the German should-cost base (mid-points of the stated ranges)
COUNTRY_COST = {"DE": 1.0, "AT": 1.05, "CH": 1.1, "CZ": 0.82, "PL": 0.82, "HU": 0.82, "TR": 0.75, "CN": 0.7}
COUNTRY_GROUP = {
    "DE": "DE",
    "AT": "DACH",
    "CH": "DACH",
    "CZ": "CEE",
    "PL": "CEE",
    "HU": "CEE",
    "TR": "FAR",
    "CN": "FAR",
}
# company.md: category strategies
CATEGORY_GOAL = {
    "castings": "stabilise",
    "machined parts": "leverage",
    "sheet metal": "leverage",
    "seals": "secure_supply",
    "electrical": "stabilise",
    "C-parts": "routine",
    "raw material": "leverage",
}

# ---------- canonical vocabularies (curated free text -> tokens the agent's rules understand) ----------
# label wording matters: agent.sheets() looks for "cash"/"payment", generic_trade_moves for "capacity",
# "lead", "volume", "contract", "long", "index" in what_it_values
VALUE_RULES = [
    ("cash", r"cash|payment|paid|liquid|skonto|\bpay\b", "faster payment (cash)"),
    ("volume", r"volume|share|account|load|fill|shift|business|work|customer with", "volume security"),
    ("relationship", r"partner|recogni|reference|loyal|relationship|status|goodwill", "partnership / reference status"),
    ("stability", r"stab|predictab|hedge window", "price stability"),
    ("index", r"index|alloy|copper|surcharge|metal|pass.?through", "index-based pricing (pass-through)"),
    ("transparency", r"transparen|open.?book|data|fair", "transparent, data-based pricing"),
    ("price", r"full cost|margin|list.?price|below.?cost|cost recovery|price|committee|2 ?%", "price level / margin"),
    (
        "contract",
        r"multi.?year|long|contract|visibility|security|commitment|agreement|term",
        "long contract / multi-year visibility",
    ),
    ("capacity", r"lead|capacity|call.?off|logistic|stock|load", "lead time / capacity flexibility"),
    ("quality", r"quality|ppm|scorecard", "quality recognition"),
]
VALUE_LABEL = {k: label for k, _, label in VALUE_RULES}
VALUE_LEVER = {
    "cash": "payment_days",
    "volume": "volume_per_year",
    "contract": "contract_months",
    "capacity": "lead_time_days",
    "index": "index_clause",
    "quality": "ppm_commitment",
    "price": "effective_date",
}
STYLE_RULES = [
    ("personal", r"personal|loyal|partnership|proud|warm|eager"),
    ("formal", r"formal|policy|letter|list|committee|standard"),
    ("brief", r"short|brief|terse|cool|confident|conditional"),
    ("informal", r"informal|friendly|plain|chatty"),
    ("data-open", r"data|numbers|transparen|open|pragmatic|factual|practical|business.?like"),
    ("defensive", r"defensive|anxious|stubborn|firm|guarded"),
]
CLAIM_KINDS = ("index", "should_cost", "rival", "scorecard", "notice", "forecast", "news", "history")


def _avoid_kinds(p):
    """Claim kinds the agent drops for this profile: agent.pick_claims tests `kind in <avoid text>`."""
    text = " ".join(a.get("argument", "") for a in p.get("arguments_to_avoid") or []).lower()
    return sorted(k for k in CLAIM_KINDS if k in text)


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
CATEGORY_WORDS = [
    (r"cast|foundry|gießerei|volute|housing|impeller", "castings"),
    (r"shaft|machin|turned|milled|sleeve|bush|cnc|zerspan", "machined parts"),
    (r"sheet|base.?frame|guard|laser|bent|blech", "sheet metal"),
    (r"seal|o-ring|gasket|dicht", "seals"),
    (r"motor|electr|converter|cable|sensor|drive", "electrical"),
    (r"screw|bolt|nut|washer|fastener|stud|kit|c-part", "C-parts"),
    (r"bar|stainless|steel|rod|alloy|1\.4\d{3}", "raw material"),
]


# ---------- the archetype priors ----------
def _tokens(texts, rules):
    """Ordered canonical tokens of a list of free-text items (first matching rule per item)."""
    out = []
    for t in texts:
        low = (t or "").lower()
        for key, rx, *_ in rules:
            if re.search(rx, low):
                if key not in out:
                    out.append(key)
                break
    return out


def _cgroup(country):
    return COUNTRY_GROUP.get(country or "DE", "OTHER")


def _features(p):
    parts = p.get("parts") or []
    ratios = [
        x["current_price"] / x["should_cost_unit"]
        for x in parts
        if x.get("current_price") and x.get("should_cost_unit")
    ]
    persona = p.get("persona") or {}
    return {
        "category": p.get("category") or "?",
        "owner": (p.get("owner_type") or "?").lower(),
        "cgroup": _cgroup(p.get("country")),
        "ratio": (p.get("negotiation_history") or {}).get("settle_to_ask_ratio"),
        "pressures": sorted({x.get("type") for x in p.get("pressures") or [] if x.get("type")}),
        "values": _tokens(p.get("what_it_values") or [], VALUE_RULES),
        "levers": [t.get("lever") for t in p.get("likely_tradeables") or [] if t.get("lever")],
        "styles": _tokens([persona.get("style", "")], STYLE_RULES)
        + [k for k, rx in STYLE_RULES if re.search(rx, (persona.get("style") or "").lower())],
        "committee": bool(re.search(r"committee|approval|>\s*2|board|head office", json.dumps(persona).lower())),
        "avoid": _avoid_kinds(p),
        "price_to_cost": statistics.median(ratios) if ratios else None,
        "staff": p.get("staff"),
    }


def _summarise(feats):
    n = len(feats)

    def ranked(key, top):
        score = Counter()
        for f in feats:
            for i, tok in enumerate(dict.fromkeys(f[key])):
                score[tok] += 1.0 / (1 + i)
        return [k for k, _ in score.most_common(top)]

    def share(pred):
        return round(sum(1 for f in feats if pred(f)) / n, 2)

    ratios = [f["ratio"] for f in feats if f["ratio"] is not None]
    ptc = [f["price_to_cost"] for f in feats if f["price_to_cost"]]
    press = Counter(t for f in feats for t in f["pressures"])
    return {
        "n": n,
        "settle_to_ask_ratio": round(statistics.median(ratios), 2) if ratios else None,
        "cash_share": share(lambda f: "cash" in f["pressures"]),
        "pressure_share": {k: round(v / n, 2) for k, v in press.most_common()},
        "what_it_values": ranked("values", 5),
        "tradeables": ranked("levers", 4),
        "persona_style": ranked("styles", 2),
        "committee_share": share(lambda f: f["committee"]),
        "avoid_share": {k: round(v / n, 2) for k, v in Counter(t for f in feats for t in f["avoid"]).most_common()},
        "price_to_should_cost": round(statistics.median(ptc), 3) if ptc else None,
        "members": sorted(f["sid"] for f in feats),
    }


LEVELS = [
    ("category", "owner", "cgroup"),
    ("category", "owner"),
    ("category", "cgroup"),
    ("category",),
    ("owner", "cgroup"),
    ("owner",),
    (),
]


def curated_profiles(exclude=()):
    out = []
    for path in sorted(PROFILES.glob("[0-9]*.json")):
        p = json.loads(path.read_text())
        if p.get("supplier_id") not in exclude:
            out.append(p)
    return out


def build_archetypes(profiles):
    """Priors per group at every level of detail: {"category|owner|cgroup": summary, ..., "*": all}."""
    feats = [{**_features(p), "sid": p.get("supplier_id")} for p in profiles]
    groups = defaultdict(list)
    for f in feats:
        for level in LEVELS:
            groups["|".join(f"{k}={f[k]}" for k in level) or "*"].append(f)
    return {k: _summarise(v) for k, v in sorted(groups.items())}


@lru_cache(maxsize=1)
def archetypes():
    try:
        return json.loads(ARCHETYPES.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return build_archetypes(curated_profiles())


def prior(category, owner, country, table=None, min_n=3):
    """The most specific archetype with at least `min_n` members; numeric fields fall back level by level."""
    table = table or archetypes()
    f = {"category": category or "?", "owner": (owner or "?").lower(), "cgroup": _cgroup(country)}
    chain = [table.get("|".join(f"{k}={f[k]}" for k in level) or "*") for level in LEVELS]
    chain = [g for g in chain if g]
    best = next((g for g in chain if g["n"] >= min_n), chain[-1] if chain else {})
    out = dict(best)
    for key in ("settle_to_ask_ratio", "price_to_should_cost"):
        if out.get(key) is None:
            out[key] = next((g[key] for g in chain if g.get(key) is not None and g["n"] >= 2), None)
    out["level"] = next((k for k, g in table.items() if g is best), "*")
    return out


# ---------- the deterministic layer ----------
def _q(pkg, sql, params=()):
    try:
        return pkg.query(sql, params) if pkg else []
    except Exception as e:  # a missing table must never cost a case
        log.debug("fallback query failed: %s", e)
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


def _guess_category(case, pkg, master):
    if master.get("category"):
        return master["category"]
    for part in case.get("parts") or []:
        rows = _q(pkg, "SELECT category FROM parts WHERE id = ?", (part,))
        if rows and rows[0].get("category"):
            return rows[0]["category"]
    text = f"{case.get('title', '')} {case.get('briefing', '')}".lower()
    for rx, cat in CATEGORY_WORDS:
        if re.search(rx, text):
            return cat
    goal = (case.get("buyer") or {}).get("category_goal")
    return {"secure_supply": "seals", "routine": "C-parts"}.get(goal)


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


def _floor(case, pkg, sid, country, ref_price, pri):
    """(full cost per unit, source, method): should-cost x country factor, else quote heuristics."""
    for part in case.get("parts") or []:
        digits = part.split(":")[-1]
        fact = _lookup(case, pkg, f"cost:{digits}")
        rows = _q(pkg, "SELECT * FROM should_cost WHERE part_id = ?", (part,))
        own = [r for r in rows if r.get("supplier_id") == sid and r.get("unit_cost")]
        if own:
            return own[0]["unit_cost"], f"{own[0]['id']} (its own plant)", "should_cost"
        base = next((r for r in rows if r.get("unit_cost")), None)
        unit = (fact or {}).get("unit_cost") or (base or {}).get("unit_cost")
        if unit:
            cb = (base or {}).get("cost_base") or "DE"
            k = COUNTRY_COST.get(country, 1.0) / COUNTRY_COST.get(cb, 1.0)
            ref = (base or {}).get("id") or f"cost:{digits}"
            return round(unit * k, 4), f"{ref} ({cb} base x{k:.2f})", "should_cost"
    if ref_price:
        r = pri.get("price_to_should_cost") or 1.0
        # curated suppliers sell at ~should-cost; a DE-based ratio, so scale by the country factor
        return (
            round(ref_price / r, 4),
            f"price heuristic: {ref_price:.2f} / {r:.2f} (archetype price-to-should-cost)",
            "quote",
        )
    return None, "", ""


def auto_profile(supplier_id, case, package, opening=None, table=None):
    """A SCHEMA-shaped profile from data, case file, opening e-mail/quote PDF and archetype priors."""
    t0 = time.perf_counter()
    sid, pkg, case = supplier_id, package, case or {}
    b = case.get("buyer") or {}
    otext, ometa = opening_text(opening)
    master = (_q(pkg, "SELECT * FROM suppliers WHERE id = ?", (sid,)) or [{}])[0]
    irow = (_q(pkg, "SELECT * FROM supplier_intel WHERE supplier_id = ?", (sid,)) or [{}])[0]
    name = master.get("name") or _guess_name(case, ometa.get("body") or otext, sid, ometa.get("pdf"))
    country = master.get("country") or _guess_country(name, case, otext)
    category = _guess_category(case, pkg, master)
    owner = irow.get("owner_type") or _guess_owner(name, otext, irow.get("staff"))
    pri = prior(category, owner, country, table)
    owner = owner or _majority_owner(category, table)
    evidence = []

    # spend, parts, prices
    spend = _q(
        pkg, "SELECT fiscal_year, spend_eur FROM spend_cube WHERE supplier_id = ? ORDER BY fiscal_year DESC", (sid,)
    )
    spend26 = spend[0]["spend_eur"] if spend else 0
    turnover = irow.get("turnover_eur")
    parts = []
    for part in case.get("parts") or []:
        prow = (_q(pkg, "SELECT * FROM parts WHERE id = ?", (part,)) or [{}])[0]
        po = _q(
            pkg,
            "SELECT id, price, price_unit FROM po_lines WHERE supplier_id = ? AND part_id = ? "
            "ORDER BY order_date DESC LIMIT 1",
            (sid, part),
        )
        src = _q(pkg, "SELECT supplier_id, status, quota_pct FROM sourcing WHERE part_id = ?", (part,))
        digits = part.split(":")[-1]
        sc = _lookup(case, pkg, f"cost:{digits}") or {}
        parts.append(
            {
                "part_id": part,
                "name": prow.get("description") or "",
                "current_price": b.get("current_unit_price") or (po[0]["price"] if po else None),
                "price_unit": prow.get("price_unit") or (po[0]["price_unit"] if po else 1),
                "quota_pct": next((s["quota_pct"] for s in src if s["supplier_id"] == sid), None),
                "qualified_alternatives": [s["supplier_id"] for s in src if s["supplier_id"] != sid],
                "should_cost_id": f"cost:{digits}" if sc else None,
                "should_cost_unit": sc.get("unit_cost"),
            }
        )

    # standard terms: quote PDF > supplier master
    std = dict(ometa.get("standard") or {})
    hint = {
        "payment_days": std.get("payment_days") or master.get("payment_days"),
        "incoterm": std.get("incoterm") or master.get("incoterm"),
        "lead_time_days": std.get("lead_time_days") or master.get("standard_lead_time_days"),
        "skonto": f"{master['skonto_pct']}% in {master['skonto_days']} days" if master.get("skonto_pct") else None,
    }
    validity = (ometa.get("signals") or {}).get("validity_days")
    m = re.search(r"valid for (\d+) days|(\d+) days valid|remains valid for (\d+)", otext.lower())
    validity = validity or (int(next(g for g in m.groups() if g)) if m else None)

    # quality, payment behaviour, contract
    sc_rows = _q(
        pkg,
        "SELECT id, otd_pct, ppm, colour, score FROM scorecards WHERE supplier_id = ? ORDER BY quarter DESC LIMIT 4",
        (sid,),
    )
    quality = {}
    if sc_rows:
        r = sc_rows[0]
        quality = {
            "latest_scorecard_id": r["id"],
            "otd_pct": r["otd_pct"],
            "ppm": r["ppm"],
            "colour": r["colour"],
            "trend": " -> ".join(x["colour"] or "?" for x in reversed(sc_rows)),
            "open_8d_overdue": None,
        }
    late = _q(
        pkg,
        "SELECT avg(julianday(paid_date) - julianday(due_date)) AS late, count(*) AS n FROM invoices "
        "WHERE supplier_id = ? AND paid_date IS NOT NULL AND paid_date >= '2025-10-01'",
        (sid,),
    )
    late_days = late[0]["late"] if late and late[0].get("n") else None
    ctr = (_q(pkg, "SELECT * FROM contracts WHERE supplier_id = ?", (sid,)) or [{}])[0]
    clauses = (
        _q(
            pkg,
            "SELECT id, series, material_share, deadband_pct FROM contract_clauses "
            "WHERE contract_id = ? AND series IS NOT NULL AND series != ''",
            (ctr.get("id"),),
        )
        if ctr
        else []
    )

    # negotiation history: asked vs settled (else the archetype's ratio)
    hist = _q(
        pkg,
        "SELECT asked_pct, settled_pct FROM negotiation_history WHERE supplier_id = ? AND asked_pct IS NOT NULL",
        (sid,),
    )
    asked = [h["asked_pct"] for h in hist if h["asked_pct"] is not None]
    settled = [h["settled_pct"] for h in hist if h["settled_pct"] is not None]
    pos = [
        (h["asked_pct"], h["settled_pct"]) for h in hist if (h["asked_pct"] or 0) > 0 and h["settled_pct"] is not None
    ]
    ratio = round(statistics.mean(s / a for a, s in pos), 2) if pos else None
    nh = {
        "events": len(hist),
        "avg_asked_pct": round(statistics.mean(asked), 2) if asked else None,
        "avg_settled_pct": round(statistics.mean(settled), 2) if settled else None,
        "settle_to_ask_ratio": ratio if ratio is not None else pri.get("settle_to_ask_ratio"),
        "notes": [
            "ratio from its own history" if ratio is not None else f"ratio is the archetype prior ({pri.get('level')})"
        ],
    }

    # pressures: keyword rules over its words, plus finance and our payment behaviour
    news_topics = [
        (n["topic"], n["id"], n["date"])
        for n in _q(pkg, "SELECT id, date, topic FROM news WHERE supplier_id = ?", (sid,))
    ]
    sources = _sources(case, pkg, sid, otext)
    pressures = _pressures(sources, irow, late_days, news_topics)
    has_data = bool(irow) or bool(master) or any(ref for _, ref, _ in sources)
    if not has_data:  # a stranger: what most similar suppliers had (marked as prior, not evidence)
        have = {p["type"] for p in pressures}
        for typ, share in (pri.get("pressure_share") or {}).items():
            if typ not in have and typ != "other" and share >= PRIOR_PRESSURE_SHARE:
                pressures.append(
                    {
                        "type": typ,
                        "evidence": f"prior: {share:.0%} of similar suppliers ({pri.get('level')})",
                        "ids": [],
                        "_weight": 0,
                        "prior": True,
                    }
                )
    for p in pressures:
        p.pop("_weight", None)

    # what it values: its own signals first, then the archetype's ranking
    # stated cost reasons (energy, wages, material) are in every price letter and say little about what
    # it trades; the pressures that do (cash, work, capacity) lead, the archetype fills the rest
    primary = {
        "cash": ["cash"],
        "utilisation": ["volume", "contract"],
        "volume": ["volume", "contract"],
        "capacity": ["capacity", "contract"],
        "quality": ["quality"],
        "succession": ["contract", "relationship"],
        "ownership": ["contract"],
        "competition": ["volume"],
    }
    secondary = {"energy": ["price"], "labour": ["price"], "other": ["index"]}
    cash = any(p["type"] == "cash" for p in pressures)
    tokens = []
    for table_ in (primary, None, secondary):
        if table_ is None:
            # the faster-payment trade (agent.sheets) only for a supplier with a cash signal or prior
            src = [t for t in pri.get("what_it_values") or [] if t != "cash" or cash]
        else:
            src = [t for p in pressures if not p.get("prior") for t in table_.get(p["type"], [])]
        for tok in src:
            if tok not in tokens:
                tokens.append(tok)
    tokens = tokens[:4]
    values = [VALUE_LABEL[t] for t in tokens]
    levers = [VALUE_LEVER[t] for t in tokens if t in VALUE_LEVER]
    for lv in pri.get("tradeables") or []:
        if lv not in levers and (lv != "payment_days" or cash):
            levers.append(lv)
    tradeables = [
        {
            "lever": lv,
            "give": "",
            "get": "a lower unit price",
            "why": "auto: from its signals and the archetype prior",
            "ids": [],
        }
        for lv in levers[:4]
    ]

    # arguments to avoid: claim kinds most similar suppliers brushed off (word the kind literally:
    # agent.pick_claims drops a claim whose kind appears in this text)
    avoid = [
        {"argument": f"{k} data", "why": f"prior: avoided for {s:.0%} of similar suppliers ({pri.get('level')})"}
        for k, s in (pri.get("avoid_share") or {}).items()
        if s >= 0.5
    ]

    # persona: archetype style, adjusted by its own greeting and signature
    style = list(pri.get("persona_style") or [])
    low = otext.lower()
    if re.search(r"dear sir or madam|sehr geehrte|yours faithfully|kind regards", low):
        style = ["formal"] + [s for s in style if s != "formal"]
    if re.search(r"guten tag|viele grüße|best wishes|cheers|hi ", low):
        style = ["personal"] + [s for s in style if s != "personal"]
    role = re.findall(
        r"(?m)^(owner|managing director|key account manager|inside sales|sales director|head of sales|"
        r"geschäftsführer|inhaber)[^\n]*",
        low,
    )
    who = role[-1] if role else ("owner" if owner in ("founder", "family") else "sales / key account manager")
    committee = pri.get("committee_share", 0) >= 0.5 or owner == "group"
    persona = {
        "who_writes": who,
        "style": ", ".join(style[:2]) or "business-like",
        "decision_making": "pricing committee / approval ladder above ~2 %" if committee else "owner decides, fast",
        "relationship_notes": f"auto profile: archetype {pri.get('level')} (n={pri.get('n')})",
    }

    # the price it charges us now (single-supplier cases) or asks now; in an RFQ the current price is
    # someone else's, so only its own ask counts, else the current price scaled by the country factor
    own_ask = _opening_price(opening)
    if len(case.get("suppliers") or []) > 1:
        floor_price_ref = own_ask or (b.get("current_unit_price") or 0) * COUNTRY_COST.get(country, 1.0) or None
    else:
        floor_price_ref = min([x for x in (b.get("current_unit_price"), own_ask) if x] or [None])
    floor, floor_src, floor_method = _floor(case, pkg, sid, country, floor_price_ref, pri)

    kinds = {
        "price_increase": "announces a price increase",
        "renewal": "renews an expiring contract",
        "rfq": "quotes in an RFQ",
        "raw_material": "passes on raw-material costs",
        "capacity": "is short of capacity",
        "quality": "has a quality escalation",
        "bundling": "bids for a bundle",
    }
    sit = [
        f"{name}: {owner or 'unknown-owner'} {category or 'unknown-category'} supplier ({country}), "
        f"{kinds.get(case.get('type'), 'in this case')}."
    ]
    if spend26 and turnover:
        sit.append(f"Our spend EUR {spend26:,.0f} is {100 * spend26 / turnover:.1f} % of its turnover.")
    elif not has_data:
        sit.append("Not in our detailed data: profile from the case file, its own e-mail and similar suppliers.")
    if pressures:
        sit.append("Signals: " + "; ".join(f"{p['type']} ({p['evidence'][:80]})" for p in pressures[:3]) + ".")
    if validity:
        sit.append(f"Quote valid {validity} days.")

    profile = {
        "supplier_id": sid,
        "name": name,
        "category": category,
        "country": country,
        "owner_type": owner,
        "group_parent": irow.get("group_parent"),
        "staff": irow.get("staff"),
        "turnover_eur": turnover,
        "our_spend_fy2026_eur": spend26,
        "our_share_of_their_turnover_pct": round(100 * spend26 / turnover, 1) if spend26 and turnover else None,
        "parts": parts,
        "contract": {
            "id": ctr.get("id"),
            "valid_to": ctr.get("valid_to"),
            "payment_days": ctr.get("payment_days"),
            "incoterm": ctr.get("incoterm"),
            "notice_days": ctr.get("notice_days"),
            "index_clauses": [
                {
                    "id": c["id"],
                    "series": c["series"],
                    "material_share": c["material_share"],
                    "deadband_pct": c["deadband_pct"],
                }
                for c in clauses
            ],
        }
        if ctr
        else {},
        "standard_terms_hint": hint,
        "quality": quality,
        "payment_behaviour": {
            "avg_days_late_by_us": round(late_days, 1) if late_days is not None else None,
            "note": "since 2025-10",
        },
        "financial_health": {
            "equity_ratio_pct": irow.get("equity_ratio_pct"),
            "credit_index": irow.get("credit_index"),
            "credit_index_12m_ago": irow.get("credit_index_12m_ago"),
            "signal": "",
        },
        "negotiation_history": nh,
        "situation": " ".join(sit),
        "pressures": pressures,
        "what_it_values": values,
        "likely_tradeables": tradeables,
        "arguments_that_should_land": [],
        "arguments_to_avoid": avoid,
        "persona": persona,
        "noise": [],
        "key_quotes": [],
        "floor_estimate": floor,
        "floor_source": floor_src,
        "floor_method": floor_method,
        # intel.build uses it as the full cost only when the data has none: a should-cost figure always,
        # the price heuristic only with FEED_QUOTE_FLOOR (the simulator decides)
        "floor_feed": floor_method == "should_cost" or (floor_method == "quote" and FEED_QUOTE_FLOOR),
        "quote_validity_days": validity,
        "archetype": pri.get("level"),
        "confidence": "low",
        "source": "auto",
        "stage": 2 if otext.strip() else 1,
    }
    evidence.append(f"built in {1000 * (time.perf_counter() - t0):.0f} ms")
    profile["_build"] = evidence
    return profile


def _opening_price(opening):
    if isinstance(opening, dict):
        for s in opening.get("term_sheets") or []:
            p = (s.get("terms") or s).get("unit_price")
            if p:
                return p
    return None


def _majority_owner(category, table=None):
    """The most common owner type among curated suppliers of this category (None if none)."""
    table = table or archetypes()
    prefix = f"category={category}|owner="
    owners = {k[len(prefix) :]: g["n"] for k, g in table.items() if k.startswith(prefix) and k.count("|") == 1}
    return max(owners, key=owners.get) if owners else None


# ---------- the optional model ----------
ENRICH_SYSTEM = """You read a supplier's quote e-mail to an industrial buyer (a German pump maker) and the
facts the buyer has. Return ONE JSON object, nothing else:
{"situation": "2-3 sentences: what is going on with this supplier",
 "pressures": [{"type": "cash|capacity|utilisation|volume|energy|labour|quality|succession|ownership|competition|other",
                "evidence": "a VERBATIM quote of 3-15 words from the e-mail or facts"}],
 "what_it_values": ["what this supplier wants from the buyer, most important first, in short phrases"],
 "persona": {"who_writes": "...", "style": "...", "decision_making": "..."}}
A pressure needs a verbatim quote that shows it; leave the list empty rather than guess. Courtesy phrases
("long-term partner", "we value the relationship") are style, not pressures."""
PRESSURE_TYPES = {
    "cash",
    "capacity",
    "utilisation",
    "volume",
    "energy",
    "labour",
    "quality",
    "succession",
    "ownership",
    "competition",
    "other",
}
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="enrich")


@lru_cache(maxsize=4)
def _anthropic_client(timeout):
    import anthropic

    return anthropic.Anthropic(timeout=timeout, max_retries=0)


def haiku_complete(model="claude-haiku-5-5", timeout=8.0):
    """complete(system, user) -> str on the Anthropic SDK, one try, short timeout. The SDK is imported and
    the client built inside the call (it runs on the enrich thread): starting it costs the move nothing."""

    def complete(system, user):
        r = _anthropic_client(timeout).messages.create(
            model=model,
            max_tokens=1200,
            system=system,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in r.content if b.type == "text")

    return complete


def _parse_json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    return json.loads(m.group(0)) if m else None


def _norm(text):
    return re.sub(r"[^a-z0-9%€ ]+", " ", (text or "").lower()).split()


def merge_enrichment(profile, data, source_text=None):
    """Merge a model's reading into an auto profile in place. Validated: a pressure only with evidence
    found in `source_text`, the cash value only with a cash pressure, never numbers or tradeables."""
    if not isinstance(data, dict) or profile.get("source") != "auto":
        return False
    if isinstance(data.get("situation"), str) and data["situation"].strip():
        profile["situation"] = data["situation"].strip()[:800] + " " + profile.get("situation", "")
    src = " ".join(_norm(source_text)) if source_text is not None else None
    have = {p["type"] for p in profile.get("pressures") or []}
    for p in data.get("pressures") or []:
        if not isinstance(p, dict) or p.get("type") not in PRESSURE_TYPES or p["type"] in have:
            continue
        ev = " ".join(_norm(str(p.get("evidence", ""))))
        if src is not None and (len(ev.split()) < 3 or ev not in src):
            continue  # not in the text: a guess
        profile["pressures"] = list(profile.get("pressures") or []) + [
            {"type": p["type"], "evidence": str(p.get("evidence", ""))[:200], "ids": [], "model": True}
        ]
        have.add(p["type"])
    vals = [v for v in data.get("what_it_values") or [] if isinstance(v, str) and v.strip()][:4]
    if vals:
        # canonical labels (the agent's rules read them): the model's ranking first, then ours
        cash = "cash" in have
        mine = _tokens(profile.get("what_it_values") or [], VALUE_RULES)
        toks = [t for t in _tokens(vals, VALUE_RULES) if t != "cash" or cash]
        merged = list(dict.fromkeys(toks + mine))[: max(4, len(mine))]
        profile["what_it_values"] = [VALUE_LABEL[t] for t in merged]
    if isinstance(data.get("persona"), dict):
        persona = dict(profile.get("persona") or {})
        for k in ("who_writes", "style", "decision_making"):
            if isinstance(data["persona"].get(k), str) and data["persona"][k].strip():
                persona[k] = data["persona"][k].strip()[:200]
        profile["persona"] = persona
    profile["enriched"] = True
    return True


def enrich_async(profile, case, opening=None, complete=None, budget_s=8.0):
    """Start a model reading of the opening e-mail, quote remarks and case facts. Returns a Future;
    the result is merged into `profile` in place only if it arrives within `budget_s`. Never blocks."""
    if complete is None:
        complete = haiku_complete(timeout=budget_s)
    text, _ = opening_text(opening)
    facts = {
        k: v
        for k, v in (case.get("facts") or {}).items()
        if isinstance(v, dict) and v.get("supplier") in (profile.get("supplier_id"), None)
    }
    user = "\n".join(
        [
            f"CASE: {case.get('title')} ({case.get('type')}): {case.get('briefing', '')[:800]}",
            f"SUPPLIER: {profile.get('name')} ({profile.get('country')}, {profile.get('category')})",
            f"CASE FACTS: {json.dumps(facts, ensure_ascii=False)[:1500]}",
            f"QUOTE E-MAIL AND PDF:\n{text[:3500]}",
        ]
    )
    t0 = time.monotonic()

    def job():
        out = _parse_json(complete(ENRICH_SYSTEM, user))
        if time.monotonic() - t0 > budget_s:
            log.info("enrich %s: too late (%.1fs), dropped", profile.get("supplier_id"), time.monotonic() - t0)
            return None
        merge_enrichment(profile, out, user)
        return out

    try:
        return _pool.submit(job)
    except Exception as e:  # never cost a move
        f = Future()
        f.set_exception(e)
        return f


# ---------- the hook ----------
def profile_for(supplier_id, case, package, opening=None):
    """intel.build's fallback when no curated profile exists. Never raises: worst case {}."""
    try:
        profile = auto_profile(supplier_id, case, package, opening)
    except Exception:
        log.exception("auto_profile %s failed", supplier_id)
        return {}
    if os.environ.get("CSEE_ENRICH") == "1" and opening and os.environ.get("ANTHROPIC_API_KEY"):
        profile["_enrich"] = enrich_async(profile, case, opening)
    log.info("%s: auto profile (%s, floor %s)", supplier_id, profile.get("archetype"), profile.get("floor_estimate"))
    return profile


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if argv[:1] == ["archetypes"]:
        table = build_archetypes(curated_profiles())
        ARCHETYPES.write_text(json.dumps(table, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {ARCHETYPES} ({len(table)} groups from {table['*']['n']} profiles)")
    else:
        raise SystemExit("usage: python -m csee.fallback archetypes")


if __name__ == "__main__":
    main()
