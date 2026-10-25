"""Supplier knowledge for the voice copilot: everything the team's data says about one supplier.

Reads the challenge data package (`data/`: correspondence, contracts, the CSV tables) and our own offline
profiles and dossier (`starter-kit/csee/profiles`, `starter-kit/csee/dossier`). Read-only, cached per
supplier, standard library only. Numbers pass through untouched: the copilot quotes them, it never computes.
"""

import csv
import functools
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA = REPO / "data"
PROFILES = REPO / "starter-kit" / "csee" / "profiles"
DOSSIER = REPO / "starter-kit" / "csee" / "dossier" / "dossier.json"

# per-supplier tables of the data package (supplier_id column), and how many rows the copilot gets
TABLES = {
    "supplier_intel": 1,
    "contracts": 10,
    "contract_clauses": 20,
    "price_conditions": 20,
    "should_cost": 10,
    "negotiation_history": 20,
    "scorecards": 12,
    "quality_notifications": 15,
    "news": 10,
    "quotes": 15,
}


def num(sid: str) -> str:
    return sid.split(":")[-1]


@functools.lru_cache(maxsize=None)
def _table(name: str) -> list[dict]:
    path = DATA / "data" / f"{name}.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@functools.lru_cache(maxsize=1)
def _dossier() -> dict:
    try:
        return json.loads(DOSSIER.read_text()).get("suppliers", {})
    except (OSError, ValueError):
        return {}


def _json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _rows(name: str, sid: str, limit: int) -> list[dict]:
    rows = [{k: v for k, v in r.items() if v not in ("", None) and k != "supplier_id"} for r in _table(name) if r.get("supplier_id") == sid]
    # newest first where the table has a date
    key = next((k for k in ("date", "qn_date", "period_end", "estimate_date", "valid_from", "quote_date") if rows and k in rows[0]), None)
    if key:
        rows.sort(key=lambda r: r.get(key, ""), reverse=True)
    return rows[:limit]


@functools.lru_cache(maxsize=128)
def supplier(sid: str) -> dict | None:
    """The complete picture of one supplier, compact: profile, dossier, tables, letters and notes, contract."""
    sid = sid if sid.startswith("sup:") else f"sup:{sid}"
    n = num(sid)
    profile = _json(PROFILES / f"{n}.json")
    dossier = _dossier().get(sid)
    if not profile and not dossier and not any(r.get("supplier_id") == sid for r in _table("supplier_intel")):
        return None
    letters = []
    corr = DATA / "correspondence"
    if corr.is_dir():
        for p in sorted(corr.glob(f"*-{n}-*.md")):
            letters.append({"id": f"doc:{p.stem}", "text": p.read_text(encoding="utf-8").strip()[:2000]})
    contract = None
    cid = ((profile or {}).get("contract") or {}).get("id") or ((dossier or {}).get("contract") or {}).get("id")
    if cid:
        path = DATA / "contracts" / f"{cid.split(':')[-1]}.md"
        if path.is_file():
            contract = path.read_text(encoding="utf-8").strip()[:3000]
    # the dossier repeats the profile's basics; keep only what it adds
    extra = {k: v for k, v in (dossier or {}).items() if k not in (profile or {})} if profile else dossier
    return {
        "supplier_id": sid,
        "profile": profile,
        "dossier_extra": extra,
        "tables": {name: _rows(name, sid, limit) for name, limit in TABLES.items()},
        "correspondence": letters,
        "contract": contract,
        "note": "profile = our offline analysis of the data package; tables/correspondence/contract = the raw data package.",
    }


def history(sid: str) -> list[dict]:
    """Past negotiations with this supplier from the ERP (negotiation_history.csv), oldest first."""
    sid = sid if sid.startswith("sup:") else f"sup:{sid}"
    rows = [r for r in _table("negotiation_history") if r.get("supplier_id") == sid]
    rows.sort(key=lambda r: r.get("date", ""))
    out = []
    for r in rows:
        out.append({
            "date": r.get("date"),
            "part": r.get("part_id"),
            "type": r.get("type"),
            "asked_pct": float(r["asked_pct"]) if r.get("asked_pct") else None,
            "settled_pct": float(r["settled_pct"]) if r.get("settled_pct") else None,
            "note": r.get("note") or None,
        })
    return out


def category_of(sid: str) -> str | None:
    sid = sid if sid.startswith("sup:") else f"sup:{sid}"
    p = _json(PROFILES / f"{num(sid)}.json")
    if p and p.get("category"):
        return p["category"]
    return (_dossier().get(sid) or {}).get("category")


def category_history(category: str, exclude: str | None = None, limit: int = 12) -> list[dict]:
    """Recent negotiations in the same category with other suppliers (ERP history)."""
    sids = {s for s, d in _dossier().items() if d.get("category") == category}
    sids |= {f"sup:{p.stem}" for p in PROFILES.glob("*.json") if (_json(p) or {}).get("category") == category}
    sids.discard(exclude or "")
    names = {r["id"]: r.get("name") for r in _table("suppliers") if r.get("id")}
    rows = []
    for r in _table("negotiation_history"):
        if r.get("supplier_id") in sids and r.get("settled_pct"):
            rows.append({"date": r.get("date"), "supplier": names.get(r["supplier_id"]) or r["supplier_id"], "type": r.get("type"),
                         "asked_pct": float(r["asked_pct"]) if r.get("asked_pct") else None, "settled_pct": float(r["settled_pct"])})
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    return rows[:limit]
