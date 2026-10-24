"""Supplier dossier: one machine-readable record per final supplier (the 46 in the data package).

Tacto (Discord, Sat 20:24): every supplier in the final is one of the 46 main suppliers. `dossier.json` is
built offline (scratchpad sub-dossier/build_dossier.py) from the package, the curated profiles and our practice
sessions; this module loads it and RE-DERIVES the document-driven fields from the package the agent runs with,
so the Sunday 08:00 release (new letters, news, memo; merged by arena_kit's DataPackage) is picked up without a
rebuild:

    hedges           "covered at fixed prices until March 2027", "bought their copper forward until ..."
                     (letters AND call notes; mert.HEDGE_RE misses the call-note wording, e.g. 70190/70560/70730)
    price_letters    documents with asked_pct / asked_price / effective_date (price-increase letters)
    cash_asks        documents asking for faster payment
    news             news rows naming the supplier (topic + headline)

Static fields (persona fit, money rate, levers, quality, should-cost, cost drivers) come from the JSON.

Use:
    d = dossier.get(sid, pkg)            # dict or None (unknown supplier)
    dossier.hedged_series(d, at=date)    # index series it is hedged on at `at` (date) -> set
    dossier.plan_overrides(d, case)      # PlanParams overrides (empty dict = today's defaults)

Everything here is advisory and fails closed: any error returns None / empty, never raises into the agent.
"""

import json
import logging
import re
import threading
from datetime import date
from pathlib import Path

log = logging.getLogger("csee")

FILE = Path(__file__).parent / "dossier.json"

# hedged material (as written in letters / call notes) -> index series it covers
MATERIALS = {
    "copper": ("WB-CU", "CU-NOTATION"),
    "nickel": ("WB-NI", "AS-14404", "AS-14301"),
    "alloy": ("WB-NI", "AS-14404", "AS-14301"),
    "stainless": ("WB-NI", "AS-14404", "AS-14301"),
    "electricity": ("PPI-D351", "PPI-D35", "SMARD-DA"),
    "power": ("PPI-D351", "PPI-D35", "SMARD-DA"),
    "energy": ("PPI-D351", "PPI-D35", "SMARD-DA", "WB-NGEU"),
    "gas": ("WB-NGEU", "PPI-D35"),
    "aluminium": ("WB-AL",),
    "aluminum": ("WB-AL",),
    "steel": ("PPI-C241", "WB-FEORE"),
    "iron": ("PPI-C241", "WB-FEORE"),
    "scrap": ("PPI-C241", "WB-FEORE"),
}
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}
HEDGE_WORDS = re.compile(r"covered at fixed prices|hedg|forward|fixed[- ]price (?:cover|contract|purchase)", re.I)
UNTIL = re.compile(r"until\s+(?:end of\s+|the end of\s+)?([A-Za-z]+)\s+(\d{4})", re.I)
CASH_ASK = re.compile(r"faster payment|pay(?:ing)? (?:us |our invoices )?(?:faster|within \d+ days)|paid faster|cash flow|"
                      r"liquidity|cash discount|Zahlungsziel verk", re.I)

_lock = threading.RLock()
_static = None
_runtime = {}  # (id(pkg), sid) -> derived


def _load():
    global _static
    with _lock:
        if _static is None:
            try:
                _static = json.loads(FILE.read_text(encoding="utf-8")).get("suppliers", {})
            except Exception as e:  # a missing / broken file means: no dossier, today's defaults
                log.warning("dossier: %s", e)
                _static = {}
        return _static


# ---------- re-derivable from documents ----------
def hedges_from_text(text):
    """[(material, series, 'YYYY-MM')] for every sentence that announces a hedge with an end month."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+|\n", text or ""):
        if not HEDGE_WORDS.search(sent):
            continue
        m = UNTIL.search(sent)
        if not m or m.group(1).lower() not in MONTHS:
            continue
        until = f"{int(m.group(2)):04d}-{MONTHS[m.group(1).lower()]:02d}"
        low = sent.lower()
        mats = [k for k in MATERIALS if re.search(rf"\b{k}", low)]
        series = sorted({s for k in mats for s in MATERIALS[k]})
        out.append((mats[0] if mats else None, series, until))
    return out


def _doc_refs(pkg, sid):
    for ref, fact in list((getattr(pkg, "facts", None) or {}).items()):
        if ref.startswith("doc:") and isinstance(fact, dict) and fact.get("supplier") == sid:
            yield ref, fact


def derive(pkg, sid):
    """Document-driven fields from the package as loaded (base + Sunday release)."""
    hedges, letters, cash, news = [], [], [], []
    for ref, fact in _doc_refs(pkg, sid):
        if fact.get("asked_pct") is not None or fact.get("asked_price") is not None:
            letters.append({"id": ref, "date": fact.get("date"), "asked_pct": fact.get("asked_pct"),
                            "asked_price": fact.get("asked_price"), "effective_date": fact.get("effective_date"),
                            "notice_days": fact.get("days")})
        try:
            text = pkg.document(ref) or ""
        except Exception:
            continue
        for mat, series, until in hedges_from_text(text):
            hedges.append({"material": mat, "series": series, "until": until, "ids": [ref],
                           "type": fact.get("type"), "date": fact.get("date")})
        if CASH_ASK.search(text):
            cash.append(ref)
    for ref, fact in list((getattr(pkg, "facts", None) or {}).items()):
        if ref.startswith("news:") and isinstance(fact, dict) and fact.get("supplier") == sid:
            news.append({"id": ref, "date": fact.get("date"), "topic": fact.get("topic"),
                         "headline": fact.get("headline")})
    # one hedge per (material, until): keep every evidence ID
    merged = {}
    for h in hedges:
        k = (h["material"], h["until"])
        if k in merged:
            merged[k]["ids"] = sorted(set(merged[k]["ids"]) | set(h["ids"]))
        else:
            merged[k] = h
    return {"hedges": sorted(merged.values(), key=lambda h: h["until"]),
            "price_letters": sorted(letters, key=lambda x: x.get("date") or ""),
            "cash_asks": sorted(set(cash)), "news": sorted(news, key=lambda x: x.get("date") or "")}


def get(sid, pkg=None):
    """The dossier entry for `sid` (static JSON + fields re-derived from `pkg`), or None if we have none."""
    try:
        entry = _load().get(sid)
        if entry is None:
            return None
        if pkg is None:
            return entry
        key = (id(pkg), sid)
        with _lock:
            if key not in _runtime:
                _runtime[key] = derive(pkg, sid)
            live = _runtime[key]
        out = dict(entry)
        known = {(h.get("material"), h.get("until")) for h in entry.get("hedges", [])}
        new_h = [h for h in live["hedges"] if (h.get("material"), h.get("until")) not in known]
        out["hedges"] = list(entry.get("hedges", [])) + new_h
        out["price_letters"] = live["price_letters"] or entry.get("price_letters", [])
        out["cash_asks"] = sorted(set(entry.get("cash_asks", [])) | set(live["cash_asks"]))
        out["news"] = live["news"] or entry.get("news", [])
        out["release_new"] = {"hedges": new_h,
                              "docs": sorted({h["ids"][0] for h in new_h} |
                                             (set(live["cash_asks"]) - set(entry.get("cash_asks", []))))}
        return out
    except Exception as e:
        log.warning("dossier %s: %s", sid, e)
        return None


def hedged_series(entry, at=None):
    """Index series the supplier is hedged on beyond `at` (a date; default today): its market moves do not reach
    its costs before the hedge ends ("not our reality")."""
    if not entry:
        return set()
    at = at or date.today()
    ym = f"{at.year:04d}-{at.month:02d}"
    return {s for h in entry.get("hedges", []) if (h.get("until") or "") > ym for s in h.get("series", [])}


# ---------- planner priors ----------
PLAN_FIELDS = ("dec", "n_plan", "gmax")  # default_rate: see plan_overrides


def plan_overrides(entry, case=None, plan=None, use_priors=False, use_rate=False):
    """PlanParams overrides for this supplier. Only `fitted` personas (we met it in practice, the fit explains its
    moves) are applied; inferred priors only with use_priors=True. An empty dict keeps today's defaults.

    fitted persona (engine: reply k>1 gives min(m * our step, cap * V0 * dec^(k-2)); final at reply N, or from
    reply K0 when our gap > G):
      default_rate <- its money rate, ONLY with use_rate=True: the planner's anchor/gap budget were tuned at 0.08,
                      and the true P01 rate (9.54 %) cost 0.962 -> 0.919 in the engine; its sheets reveal the rate
                      after reply 1 anyway (PlanMixin.revealed_rate)
      dec          <- dec (only within 0.6 .. 1.0)
      n_plan       <- N (only 4 .. 6: the planner's horizon)
      gmax         <- the default budget, capped at 0.8 x G from reply K0 on (avoid the early final)
    """
    try:
        if not entry:
            return {}
        pp = entry.get("planner") or {}
        conf = pp.get("confidence")
        if conf not in ("high", "medium") and not (use_priors and conf == "low"):
            return {}
        out = {}
        for f in PLAN_FIELDS + (("default_rate",) if use_rate else ()):
            if pp.get(f) is not None:
                out[f] = tuple(pp[f]) if f == "gmax" else pp[f]
        if plan is not None and "gmax" in out:
            # merge with the plan's own budget: never looser than today's
            out["gmax"] = tuple(min(a, b) for a, b in zip(plan.gmax, out["gmax"])) + tuple(plan.gmax[len(out["gmax"]):])
        return out
    except Exception:
        return {}
