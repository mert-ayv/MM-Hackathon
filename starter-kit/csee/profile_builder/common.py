"""Shared helpers: where the data package and the profiles live, how to load them."""

import json
import os
import re
import threading
from pathlib import Path

from arena_kit.data import DataPackage

KIT = Path(__file__).resolve().parents[2]  # starter-kit/
REPO = KIT.parent
PROFILES = KIT / "csee" / "profiles"
SCHEMA = PROFILES / "SCHEMA.md"
STAGING = KIT / "runs" / "profiles"  # git-ignored (runs/), staged updates + reports land here
ID_RE = re.compile(
    r"\b(?:sup|part|po|gr|inv|qn|ctr|quote|rfq|fc|idx|sc|cost|news|doc):[A-Za-z0-9_.\-]+(?:#[0-9.]+)?(?:@[0-9A-Za-z\-]+)?"
)


def find_data(explicit=None):
    """The data package folder: --data, else ARENA_DATA (relative to starter-kit/), else the usual spots."""
    cands = [explicit] if explicit else []
    env = os.environ.get("ARENA_DATA")
    if env:
        cands += [env, KIT / env]
    cands += [KIT / "data" / "package", REPO / "data" / "package", REPO / "data"]
    for c in cands:
        p = Path(c).expanduser()
        if (p / "facts.json").is_file():
            return p.resolve()
    raise SystemExit(f"no data package found (tried {', '.join(map(str, cands))}); pass --data")


def open_package(data=None, release=None):
    """DataPackage over the package; `release` = a release folder to merge (else DataPackage's own lookup)."""
    pkg = DataPackage(find_data(data), release=str(release) if release else None)
    pkg.lookup("")  # build the ID index once
    # one SQLite connection is shared by the worker threads: serialise its use
    lock, query = threading.Lock(), pkg.query

    def locked_query(*a, **k):
        with lock:
            return query(*a, **k)

    pkg.query = locked_query
    return pkg


def sid(supplier):
    """'70110' / 'sup:70110' -> 'sup:70110'."""
    s = str(supplier).strip()
    return s if s.startswith("sup:") else f"sup:{s}"


def digits(supplier):
    return sid(supplier).split(":", 1)[1]


def detailed_suppliers(pkg):
    return [r["id"] for r in pkg.query("SELECT id FROM suppliers WHERE detail = 'full' ORDER BY id", limit=10_000)]


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def curated(supplier, profiles=PROFILES):
    return load_json(Path(profiles) / f"{digits(supplier)}.json")


def dump(obj):
    """Profiles are written like the curated ones: indent 1, UTF-8 kept."""
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def ids_in(obj):
    """Every data ID mentioned anywhere in a JSON-able object."""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return set(m.rstrip(".,;)") for m in ID_RE.findall(text))


def id_exists(pkg, ref):
    if ref in pkg.facts or pkg._ids.get(ref):
        return True
    # a fact with a period, e.g. idx:X@2026-08 is in facts; a contract clause ctr:...#3.1 too
    return False
