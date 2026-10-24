"""The Sunday path: fold a data release into the curated profiles as minimal, reviewable updates.

1. detect   new IDs in the release (its facts.json, data/*.csv), with their text
2. map      each item to its supplier(s); company-wide items -> profiles/_market.json
3. update   per affected supplier, in parallel: current curated profile + only the new items -> a PATCH
            (additions, a rewritten situation, explicit removals with reasons); code merges the patch,
            so curated content can only disappear through a listed removal
4. stage    <staging>/<supplier>.json + <supplier>.md (diff report) + REPORT.md; --apply copies to profiles/
"""

import csv
import difflib
import json
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from . import llm, soft, sources
from .common import PROFILES, STAGING, curated, digits, dump, id_exists, sid
from .verify import Checker

# ---------------------------------------------------------------- 1 + 2: detect and map


def release_ids(pkg):
    """IDs new in the release: its facts.json keys plus the `id` column of its data/*.csv."""
    if not pkg.release:
        raise SystemExit("no release merged: pass --release <dir> (a folder with facts.json)")
    ids = set(json.loads((pkg.release / "facts.json").read_text(encoding="utf-8")))
    for path in sorted(pkg.release.glob("data/*.csv")):
        with path.open(encoding="utf-8", newline="") as f:
            ids |= {r["id"] for r in csv.DictReader(f) if r.get("id")}
    return sorted(ids)


def _name_patterns(pkg):
    """Distinctive name fragments of the detailed suppliers, for mapping un-tagged text to suppliers."""
    pats = {}
    generic = {
        "gmbh",
        "kg",
        "co.",
        "&",
        "s.r.o.",
        "sp.",
        "z",
        "o.",
        "o.o.",
        "ag",
        "a.s.",
        "ltd.",
        "co.,",
        "gießerei",
        "präzision",
        "precision",
        "castings",
        "mechanik",
        "zerspanung",
        "kft.",
        "a.ş.",
        "sanayi",
        "döküm",
    }
    for r in pkg.query("SELECT id, name FROM suppliers WHERE detail = 'full'", limit=10_000):
        words = [w for w in r["name"].split() if w.lower().strip(",") not in generic and len(w) > 3]
        pats[r["id"]] = [r["name"]] + words[:1]
    return pats


def map_item(pkg, ref, text, meta, names, profiles):
    """(suppliers, how): direct owner first, then explicit sup: IDs, names, then parts -> source list."""
    owner = sources.item_supplier(pkg, ref)
    memo = str(meta.get("kind") or meta.get("type") or "").lower() == "memo"
    if owner and not memo:
        return [owner], "owner"
    found = sorted({m for m in re.findall(r"sup:\d{5}", text)})
    if found:
        return found, "mentions sup: ID"
    by_name = sorted(s for s, pats in names.items() if any(p and p in text for p in pats))
    if by_name:
        return by_name, "mentions supplier name"
    parts = set(re.findall(r"part:\d{6}", text)) | set(re.findall(r"part:\d{6}", str(meta.get("part_ids") or "")))
    if parts:
        q = "SELECT DISTINCT supplier_id FROM sourcing WHERE part_id IN ({})".format(",".join("?" * len(parts)))
        sup = sorted(r["supplier_id"] for r in pkg.query(q, tuple(sorted(parts)), limit=1000))
        sup = [s for s in sup if (Path(profiles) / f"{digits(s)}.json").is_file()]
        if sup or owner:
            return sorted(
                set(sup) | ({owner} if owner else set())
            ), "memo: owner + parts it names" if owner else "parts it names (source list)"
    if owner:
        return [owner], "memo: owner"
    return [], "company-wide"


def detect(pkg, profiles=PROFILES):
    """{'items': [...], 'by_supplier': {sup: [item]}, 'market': [item]}"""
    names = _name_patterns(pkg)
    items, by_sup, market = [], {}, []
    for ref in release_ids(pkg):
        meta = sources.item_meta(pkg, ref)
        text = sources.item_text(pkg, ref) if ref.split(":")[0] in ("doc", "news") else ""
        if not text:  # a non-document fact (index value, quote, ...): its fields are its text
            text = json.dumps(pkg.lookup(ref) or {}, ensure_ascii=False, default=str)
        sups, how = map_item(pkg, ref, text, meta, names, profiles)
        item = {"id": ref, "date": meta.get("date"), "meta": meta, "text": text, "suppliers": sups, "mapped_by": how}
        items.append(item)
        for s in sups:
            by_sup.setdefault(s, []).append(item)
        if how != "owner":  # memos, market news, cross-supplier items: also company-wide
            market.append(item)
    return {"items": items, "by_supplier": by_sup, "market": market}


# ---------------------------------------------------------------- 3: per-supplier patch

REMOVAL = soft.obj(
    field={
        "type": "string",
        "enum": [
            "pressures",
            "what_it_values",
            "likely_tradeables",
            "arguments_that_should_land",
            "arguments_to_avoid",
            "noise",
            "key_quotes",
        ],
    },
    match=soft.S,
    reason=soft.S,
)
PATCH_SCHEMA = soft.obj(
    relevant={"type": "boolean"},
    change_summary=soft.S,
    situation=soft.S,
    add_pressures=soft.arr(soft.PRESSURE),
    what_it_values=soft.arr(soft.S),
    add_likely_tradeables=soft.arr(soft.TRADEABLE),
    add_arguments_that_should_land=soft.arr(soft.ARG_LAND),
    add_arguments_to_avoid=soft.arr(soft.ARG_AVOID),
    add_noise=soft.arr(soft.S),
    add_key_quotes=soft.arr(soft.QUOTE),
    persona_note=soft.S,
    removals=soft.arr(REMOVAL),
    confidence={"type": "string", "enum": ["high", "medium", "low"]},
)

UPDATE_SYSTEM = """You maintain the negotiation profile of one supplier for Hollerau Pumpenwerke's autonomous
buyer agent. A new data release brought NEW ITEMS (letters, e-mails, notes, news, a memo). Produce a MINIMAL
update of the CURRENT PROFILE as a patch.

Rules:
- The current profile was curated by hand: keep its content. Only add what the new items show, and rewrite
  `situation` so it reflects them (keep its still-valid facts and IDs; 3-6 sentences).
- `what_it_values` is the full, re-ordered list: keep every existing entry unless a new item contradicts it.
- Remove an existing entry only when a new item makes it wrong or obsolete; put it in `removals` with the
  exact text of the entry (`match`) and the new item's ID in `reason`.
- New pressures / tradeables / arguments must cite the NEW item IDs (plus any existing IDs they rely on).
  Never invent IDs or figures. Arguments that should land are checkable data arguments (figure + IDs).
- If a new item is noise for this negotiation (apprentices, new director without consequence, trade fair),
  add it to `add_noise` (e.g. "news:... apprentices award") and set relevant=false if nothing else changes.
- key quotes: copied CHARACTER FOR CHARACTER from a new item, short, with its ID.
- Company-wide items are filed separately (_market.json): do NOT list them under add_noise; cite one only
  where it changes this supplier's negotiation (e.g. an index move that supports or undercuts its ask).
- Pressure types: pick the specific type (cash, capacity, utilisation, volume, energy, labour, quality,
  succession, ownership, competition); use "other" only if none fits.
- persona_note: one sentence on tone/relationship the new items reveal, or "" if nothing new.
- change_summary: 1-3 sentences for the human reviewer: what changed and why it matters for negotiating."""


def _patch_prompt(pkg, cur, items, market):
    sup_items = [(i["id"], i["meta"], i["text"]) for i in items]
    mk = [(i["id"], i["meta"], i["text"]) for i in market if i not in items]
    keep = {k: v for k, v in cur.items() if k not in ("parts", "payment_behaviour", "negotiation_history")}
    return "\n\n".join(
        [
            "CURRENT PROFILE (curated):\n" + json.dumps(keep, ensure_ascii=False, indent=1),
            "NEW ITEMS FOR THIS SUPPLIER:\n" + sources.render_items(sup_items),
            "NEW COMPANY-WIDE ITEMS (context only; cite only if they change this supplier's negotiation):\n"
            + (sources.render_items(mk) or "(none)"),
            "Return the patch as one JSON object.",
        ]
    )


KEY_FIELD = {
    "pressures": "evidence",
    "likely_tradeables": "give",
    "arguments_that_should_land": "argument",
    "arguments_to_avoid": "argument",
    "key_quotes": "quote",
}


def _key(field, e):
    """The text a removal's `match` is compared with."""
    return e if isinstance(e, str) else (e.get(KEY_FIELD.get(field, ""), "") or json.dumps(e, ensure_ascii=False))


def _matches(a, b):
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    return bool(a) and (a == b or a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() > 0.85)


def merge(pkg, cur, patch, items, release_date):
    """Curated profile + checked patch -> (updated profile, log of checks, applied removals)."""
    new_ids = [i["id"] for i in items]
    c = Checker(pkg, new_ids)
    out = json.loads(json.dumps(cur))
    log = []
    removed = []
    for r in patch.get("removals") or []:
        f = r.get("field")
        if f not in out or not isinstance(out[f], list):
            continue
        reason = r.get("reason", "").strip()
        if not reason:
            log.append(f"ignored removal without reason in {f}: {r.get('match', '')[:80]}")
            continue
        kept = []
        for e in out[f]:
            if _matches(r.get("match"), _key(f, e)):
                removed.append({"field": f, "entry": e, "reason": reason})
            else:
                kept.append(e)
        out[f] = kept
    situation = c.text(patch.get("situation") or "", "situation").strip()
    if situation and len(situation) > 80:
        out["situation"] = situation
    for f, need in (("pressures", True), ("likely_tradeables", False), ("arguments_that_should_land", True)):
        out[f] = (out.get(f) or []) + c.entries(patch.get(f"add_{f}"), f"add_{f}", need_ids=need)
    out["arguments_to_avoid"] = (out.get("arguments_to_avoid") or []) + [
        {k: c.text(v, "add_arguments_to_avoid") for k, v in a.items()}
        for a in patch.get("add_arguments_to_avoid") or []
    ]
    out["noise"] = (out.get("noise") or []) + [c.text(n, "add_noise") for n in patch.get("add_noise") or []]
    # quotes must come from the new items or the supplier's documents
    out["key_quotes"] = (out.get("key_quotes") or []) + c.quotes(patch.get("add_key_quotes"))
    # what_it_values: the model's order, but no curated entry silently lost
    values = [c.text(v, "what_it_values") for v in patch.get("what_it_values") or []] or list(
        out.get("what_it_values", [])
    )
    gone = {r["entry"] for r in removed if r["field"] == "what_it_values" and isinstance(r["entry"], str)}
    for old in cur.get("what_it_values", []):
        if old not in gone and not any(_matches(old, v) for v in values):
            values.append(old)
            log.append(f"kept curated what_it_values entry the patch dropped without a removal: '{old[:60]}'")
    out["what_it_values"] = values
    note = (patch.get("persona_note") or "").strip()
    if note:
        persona = dict(out.get("persona") or {})
        persona["relationship_notes"] = (
            persona.get("relationship_notes", "") + f" [{release_date}] " + c.text(note, "persona")
        ).strip()
        out["persona"] = persona
    if patch.get("confidence"):
        out["confidence"] = patch["confidence"]
    out["updated_from"] = sorted(set(out.get("updated_from", [])) | set(new_ids))
    out.setdefault("update_notes", []).append(
        {"release": release_date, "ids": new_ids, "summary": c.text(patch.get("change_summary", ""), "summary")}
    )
    return out, c.log + log, removed


def update_one(pkg, supplier, items, market, model, release_date, profiles):
    t0 = time.time()
    cur = curated(supplier, profiles)
    if not cur:
        return {"supplier": supplier, "error": "no curated profile (long-tail supplier?)", "items": items, "seconds": 0}
    patch, row = llm.call_json(
        UPDATE_SYSTEM, _patch_prompt(pkg, cur, items, market), PATCH_SCHEMA, model, label=f"update {supplier}"
    )
    new, log, removed = merge(pkg, cur, patch, items, release_date)
    return {
        "supplier": supplier,
        "before": cur,
        "after": new,
        "patch": patch,
        "log": log,
        "removed": removed,
        "items": items,
        "cost": row,
        "seconds": round(time.time() - t0, 1),
    }


# ---------------------------------------------------------------- market file

MARKET_SCHEMA = soft.obj(
    items=soft.arr(
        soft.obj(
            id=soft.S,
            summary=soft.S,
            affected_categories=soft.arr(soft.S),
            affected_series=soft.arr(soft.S),
            implications=soft.S,
        )
    )
)
MARKET_SYSTEM = """You brief Hollerau Pumpenwerke's buyer agent on company-wide items of a new data release
(market news, internal memos). For every item give: a one-sentence factual summary (figures as stated),
the affected supplier categories and index series (choose ONLY from the lists given), and the implication
for negotiations: which argument it supports or undermines (e.g. "supports suppliers' steel surcharge asks;
do not argue steel is falling"). No invented figures."""


def market_update(pkg, market, model, release_date, profiles):
    if not market:
        return None, None
    cats = [r["category"] for r in pkg.query("SELECT DISTINCT category FROM suppliers WHERE detail='full'", limit=1000)]
    series = {r["id"]: r["name"] for r in pkg.query("SELECT id, name FROM index_series", limit=1000)}
    user = "\n\n".join(
        [
            "CATEGORIES: " + json.dumps(cats, ensure_ascii=False),
            "INDEX SERIES: " + json.dumps(series, ensure_ascii=False),
            "ITEMS:\n" + sources.render_items([(i["id"], i["meta"], i["text"]) for i in market]),
        ]
    )
    res, row = llm.call_json(MARKET_SYSTEM, user, MARKET_SCHEMA, model, label="market")
    by_id = {i["id"]: i for i in market}
    out_items = []
    for it in res.get("items", []):
        if it.get("id") not in by_id:
            continue
        src = by_id[it["id"]]
        out_items.append(
            {
                "id": it["id"],
                "date": src.get("date"),
                "title": src["meta"].get("subject") or src["meta"].get("title") or src["text"].split("\n")[0][:120],
                "summary": it["summary"],
                "affected_categories": [c for c in it.get("affected_categories", []) if c in cats],
                "affected_series": [s for s in it.get("affected_series", []) if s in series],
                "affected_suppliers": src["suppliers"],
                "implications": it["implications"],
            }
        )
    for ref, src in by_id.items():  # never lose an item because the model skipped it
        if ref not in {i["id"] for i in out_items}:
            out_items.append(
                {
                    "id": ref,
                    "date": src.get("date"),
                    "title": src["text"].split("\n")[0][:120],
                    "summary": src["text"][:300],
                    "affected_categories": [],
                    "affected_series": [],
                    "affected_suppliers": src["suppliers"],
                    "implications": "",
                }
            )
    old = (curated("_market", profiles) or {}) if (Path(profiles) / "_market.json").is_file() else {}
    keep = [i for i in old.get("items", []) if i["id"] not in by_id]
    market_doc = {
        "date": release_date,
        "note": "Company-wide items of the data releases (market news, memos). Built by csee.profile_builder.",
        "items": sorted(keep + out_items, key=lambda i: (i.get("date") or "", i["id"])),
    }
    return market_doc, row


# ---------------------------------------------------------------- 4: stage, report, apply


def _diff(a, b, name):
    return "".join(
        difflib.unified_diff(
            dump(a).splitlines(True), dump(b).splitlines(True), f"profiles/{name} (curated)", f"staged/{name}"
        )
    )


def supplier_report(r):
    s = r["supplier"]
    lines = [f"# {s} {r['after'].get('name', '')}", ""]
    lines.append(f"**Change summary:** {r['patch'].get('change_summary', '')}  ")
    lines.append(
        f"relevant: {r['patch'].get('relevant')}, model {r['cost']['model']}, {r['seconds']} s, ${r['cost']['usd']:.4f}"
    )
    lines += ["", "## New items", ""]
    for i in r["items"]:
        lines.append(
            f"- `{i['id']}` ({i.get('date')}, mapped by {i['mapped_by']}): {i['text'].strip()[:300].replace(chr(10), ' ')}"  # noqa: E501
        )
    lines += [
        "",
        "## Situation",
        "",
        f"- before: {r['before'].get('situation', '')}",
        f"- after: {r['after'].get('situation', '')}",
    ]
    added = []
    for f in (
        "pressures",
        "likely_tradeables",
        "arguments_that_should_land",
        "arguments_to_avoid",
        "noise",
        "key_quotes",
    ):
        n0 = len([e for e in r["before"].get(f, []) if e not in [x["entry"] for x in r["removed"]]])
        for e in r["after"].get(f, [])[n0:]:
            added.append(f"- **{f}**: `{json.dumps(e, ensure_ascii=False)}`")
    lines += ["", "## Added", ""] + (added or ["(nothing)"])
    if r["before"].get("what_it_values") != r["after"].get("what_it_values"):
        lines += [
            "",
            "## what_it_values",
            "",
            f"- before: {r['before'].get('what_it_values')}",
            f"- after: {r['after'].get('what_it_values')}",
        ]
    lines += ["", "## Removed (with reasons)", ""]
    lines += [
        f"- **{x['field']}**: `{json.dumps(x['entry'], ensure_ascii=False)[:300]}` - {x['reason']}"
        for x in r["removed"]
    ] or ["(nothing)"]
    lines += ["", "## Checks (IDs, quotes)", ""] + (
        [f"- {x}" for x in r["log"]] or ["- all cited IDs exist; all quotes verbatim"]
    )
    lines += ["", "## Full diff", "", "```diff", _diff(r["before"], r["after"], f"{digits(s)}.json"), "```", ""]
    return "\n".join(lines)


def run(pkg, model, profiles=PROFILES, out_dir=None, suppliers=None, workers=16, release_date=None):
    t0 = time.time()
    found = detect(pkg, profiles)
    t_detect = time.time() - t0
    release_date = release_date or max((i.get("date") or "" for i in found["items"]), default="") or "release"
    out_dir = Path(out_dir or STAGING / datetime.now().strftime("%Y%m%d-%H%M%S"))
    out_dir.mkdir(parents=True, exist_ok=True)
    by_sup = found["by_supplier"]
    if suppliers:
        by_sup = {s: v for s, v in by_sup.items() if s in {sid(x) for x in suppliers}}
    print(
        f"release {pkg.release}: {len(found['items'])} new IDs, {len(by_sup)} suppliers affected, "
        f"{len(found['market'])} company-wide items (detect {t_detect:.1f} s)"
    )
    for s, its in sorted(by_sup.items()):
        print(f"  {s}: {', '.join(i['id'] for i in its)}")
    results, errors = [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(update_one, pkg, s, its, found["market"], model, release_date, profiles): s
            for s, its in by_sup.items()
        }
        mfut = ex.submit(market_update, pkg, found["market"], model, release_date, profiles)
        for f in as_completed(futs):
            s = futs[f]
            try:
                r = f.result()
            except Exception as e:  # one supplier failing must not cost the others
                errors.append((s, repr(e)))
                print(f"  FAILED {s}: {e!r}")
                continue
            if r.get("error"):
                errors.append((s, r["error"]))
                continue
            results.append(r)
            (out_dir / f"{digits(s)}.json").write_text(dump(r["after"]), encoding="utf-8")
            (out_dir / f"{digits(s)}.md").write_text(supplier_report(r), encoding="utf-8")
            print(f"  staged {s} in {r['seconds']} s (${r['cost']['usd']:.4f}), {len(r['log'])} check notes")
        try:
            market_doc, mrow = mfut.result()
        except Exception as e:
            market_doc, mrow = None, None
            errors.append(("_market", repr(e)))
    if market_doc:
        (out_dir / "_market.json").write_text(dump(market_doc), encoding="utf-8")
    wall = time.time() - t0
    report = _index_report(found, results, errors, market_doc, mrow, model, wall, out_dir)
    (out_dir / "REPORT.md").write_text(report, encoding="utf-8")
    (out_dir / "detected.json").write_text(
        json.dumps({k: v for k, v in found.items() if k != "by_supplier"}, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    print(f"done in {wall:.1f} s wall, ${llm.LEDGER.usd:.4f} total; {len(errors)} errors")
    print(f"REPORT: {out_dir / 'REPORT.md'}")
    return {
        "out_dir": out_dir,
        "results": results,
        "errors": errors,
        "market": market_doc,
        "found": found,
        "wall": wall,
    }


def _index_report(found, results, errors, market_doc, mrow, model, wall, out_dir):
    lines = [f"# Release update - staged in `{out_dir}`", ""]
    lines.append(
        f"model `{model}`, {len(found['items'])} new IDs, {len(results)} suppliers staged, "
        f"{len(errors)} errors, wall {wall:.1f} s, cost ${llm.LEDGER.usd:.4f}"
    )
    lines += [
        "",
        "| supplier | new items | relevant | +press. | +args | removed | checks | s | $ |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in sorted(results, key=lambda r: r["supplier"]):
        p = r["patch"]
        lines.append(
            f"| [{r['supplier']}]({digits(r['supplier'])}.md) {r['after'].get('name', '')[:28]} | "
            f"{', '.join(i['id'] for i in r['items'])} | {p.get('relevant')} | {len(p.get('add_pressures') or [])} | "
            f"{len(p.get('add_arguments_that_should_land') or [])} | {len(r['removed'])} | {len(r['log'])} | "
            f"{r['seconds']} | {r['cost']['usd']:.4f} |"
        )
    if errors:
        lines += ["", "## Errors (these suppliers keep their current profile)", ""] + [f"- {s}: {e}" for s, e in errors]
    lines += ["", "## Company-wide items -> `_market.json`", ""]
    for i in (market_doc or {}).get("items", []):
        if i["id"] in {m["id"] for m in found["market"]}:
            lines.append(
                f"- `{i['id']}` {i['summary']} -> {i['implications']} (categories {i['affected_categories']}, series {i['affected_series']})"  # noqa: E501
            )
    lines += [
        "",
        "## Review and apply",
        "",
        "Read each supplier's `.md` (diff at the bottom). Then:",
        "",
        f"    uv run python -m csee.profile_builder apply {out_dir}",
        "",
    ]
    return "\n".join(lines)


def apply(staged_dir, profiles=PROFILES, only=None):
    """Copy staged profiles (and _market.json) into profiles/. Validates JSON and IDs' shape first."""
    staged_dir = Path(staged_dir)
    files = sorted(p for p in staged_dir.glob("*.json") if p.name != "detected.json")
    if only:
        keep = {digits(x) for x in only} | {"_market"}
        files = [p for p in files if p.stem in keep]
    for p in files:
        d = json.loads(p.read_text(encoding="utf-8"))
        if p.stem != "_market" and d.get("supplier_id") != f"sup:{p.stem}":
            raise SystemExit(f"{p}: supplier_id mismatch, not applying anything")
    for p in files:
        shutil.copyfile(p, Path(profiles) / p.name)
        print(f"applied {p.name}")
    return files


def check_ids(pkg, obj):
    from .common import ids_in

    return [i for i in ids_in(obj) if not id_exists(pkg, i)]
