"""Rehearsal: fake a Sunday release from the most recent real items and check `update` recovers them.

build  copy the package without docs/news dated >= --since; package the held-out items in the
       release layout DataPackage reads (facts.json with new IDs only, data/news.csv,
       data/documents.csv, correspondence/*.md); ablate the curated profiles (drop every entry,
       quote and situation sentence that cites a held-out ID) = "the profiles before the release"
score  compare the updated profiles with the curated ones on the held-out IDs
"""

import csv
import json
import re
import shutil
import sqlite3
from pathlib import Path

from .common import PROFILES, curated, digits, dump, find_data, ids_in, load_json

LIST_FIELDS = (
    "pressures",
    "likely_tradeables",
    "arguments_that_should_land",
    "arguments_to_avoid",
    "noise",
    "key_quotes",
)


def build(out, since="2026-09-15", data=None, profiles=PROFILES, also=(), orphan_memos=False):
    """`also`: extra IDs to hold out; `orphan_memos`: blank the supplier of held-out memos, to rehearse a
    company-wide memo (mapped by the parts it names, and written to _market.json)."""
    src = find_data(data)
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    pkg_dir, rel_dir, prof_dir = out / "package", out / "release-sunday", out / "profiles_before"
    shutil.copytree(src, pkg_dir, ignore=shutil.ignore_patterns("release-sunday"))
    db = sqlite3.connect(pkg_dir / "world.sqlite")
    db.row_factory = sqlite3.Row
    held = {}
    for table in ("documents", "news"):
        cond = "date >= ? OR id IN ({})".format(",".join("?" * len(also))) if also else "date >= ?"
        rows = [dict(r) for r in db.execute(f"SELECT * FROM {table} WHERE {cond} ORDER BY date, id", (since, *also))]
        held[table] = rows
        db.execute(f"DELETE FROM {table} WHERE {cond}", (since, *also))
    db.commit()
    db.execute("VACUUM")
    db.close()
    ids = [r["id"] for rows in held.values() for r in rows]
    facts = json.loads((pkg_dir / "facts.json").read_text(encoding="utf-8"))
    (rel_dir / "data").mkdir(parents=True)
    (pkg_dir / "facts.json").write_text(
        json.dumps({k: v for k, v in facts.items() if k not in ids}, ensure_ascii=False), encoding="utf-8"
    )
    rel_facts = {k: facts[k] for k in ids if k in facts}
    if orphan_memos:
        for r in held["documents"]:
            if r.get("kind") == "memo":
                r["supplier_id"] = ""
                rel_facts[r["id"]] = {**rel_facts[r["id"]], "supplier": None}
    (rel_dir / "facts.json").write_text(json.dumps(rel_facts, ensure_ascii=False, indent=1), encoding="utf-8")
    for table, rows in held.items():
        if not rows:
            continue
        with (rel_dir / "data" / f"{table}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        csv_master = pkg_dir / "data" / f"{table}.csv"  # keep the package's CSV master copy consistent
        if csv_master.is_file():
            with csv_master.open(encoding="utf-8", newline="") as f:
                rd = csv.DictReader(f)
                keep = [r for r in rd if r["id"] not in ids]
                fields = rd.fieldnames
            with csv_master.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows(keep)
    for r in held["documents"]:
        dst = rel_dir / r["file"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(pkg_dir / r["file"], dst)
    # profiles as they would look without the held-out items
    prof_dir.mkdir()
    ablation = {}
    for p in sorted(Path(profiles).glob("7*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        d2, removed = ablate(d, set(ids))
        (prof_dir / p.name).write_text(dump(d2), encoding="utf-8")
        if removed:
            ablation[d["supplier_id"]] = removed
    (out / "heldout.json").write_text(
        json.dumps({"since": since, "ids": ids, "ablation": ablation}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"held out {len(held['documents'])} documents + {len(held['news'])} news from {since}: {out}")
    print(f"ablated {len(ablation)} curated profiles -> {prof_dir}")
    return out


def ablate(profile, ids):
    """Drop list entries citing held-out IDs and situation sentences naming them. -> (profile, removed)."""
    d = json.loads(json.dumps(profile))
    removed = []
    for f in LIST_FIELDS:
        kept = []
        for e in d.get(f, []):
            if ids_in(e) & ids:
                removed.append({"field": f, "entry": e})
            else:
                kept.append(e)
        d[f] = kept
    sents = re.split(r"(?<=[.!?])\s+", d.get("situation", ""))
    keep = [s for s in sents if not (ids_in(s) & ids)]
    if len(keep) != len(sents):
        removed.append({"field": "situation", "entry": " ".join(s for s in sents if ids_in(s) & ids)})
    d["situation"] = " ".join(keep)
    return d, removed


def score(rehearsal_dir, staged_dir, profiles=PROFILES):
    """Per supplier: held-out IDs the curated profile cites vs those the updated profile cites,
    and pressure types recovered."""
    held = load_json(Path(rehearsal_dir) / "heldout.json")
    ids = set(held["ids"])
    rows, lines = [], ["# Rehearsal: recovery of held-out information", ""]
    lines += [
        "| supplier | held-out IDs cited by curated | recovered by update | ID recall | pressure types curated (held-out) | recovered |",  # noqa: E501
        "|---|---|---|---:|---|---|",
    ]
    for p in sorted(Path(staged_dir).glob("7*.json")):
        s = f"sup:{p.stem}"
        cur, upd = curated(s, profiles), load_json(p)
        gone = held["ablation"].get(s, [])
        want = set().union(*[ids_in(r["entry"]) & ids for r in gone]) if gone else set()
        soft_keys = ("situation",) + LIST_FIELDS
        got = ids_in({k: upd.get(k) for k in soft_keys}) & ids
        rec = len(want & got) / len(want) if want else None
        ptypes = sorted({r["entry"]["type"] for r in gone if r["field"] == "pressures"})
        before = load_json(Path(rehearsal_dir) / "profiles_before" / p.name) or {}
        n0 = len(before.get("pressures", []))
        new_types = sorted({e.get("type") for e in upd.get("pressures", [])[n0:]})
        rows.append(
            {
                "supplier": s,
                "want": sorted(want),
                "got": sorted(got),
                "recall": rec,
                "ptypes": ptypes,
                "new_types": new_types,
            }
        )
        lines.append(
            f"| {s} {cur.get('name', '')[:24]} | {', '.join(sorted(want)) or '-'} | {', '.join(sorted(want & got)) or '-'}"  # noqa: E501
            f"{' (+' + ', '.join(sorted(got - want)) + ')' if got - want else ''} | "
            f"{'-' if rec is None else f'{rec:.0%}'} | {', '.join(ptypes) or '-'} | {', '.join(t for t in new_types if t) or '-'} |"  # noqa: E501
        )
    with_want = [r for r in rows if r["want"]]
    if with_want:
        tot = sum(len(r["want"]) for r in with_want)
        hit = sum(len(set(r["want"]) & set(r["got"])) for r in with_want)
        pt = sum(len(r["ptypes"]) for r in with_want)
        pthit = sum(len(set(r["ptypes"]) & set(r["new_types"])) for r in with_want)
        lines += [
            "",
            f"**Held-out IDs recovered: {hit}/{tot} ({hit / tot:.0%}); held-out pressure types recovered: {pthit}/{pt}**",  # noqa: E501
        ]
    lines += ["", "## Side by side: curated (removed by ablation) vs added by the update", ""]
    for r in rows:
        s = r["supplier"]
        lines.append(f"### {s}")
        for g in held["ablation"].get(s, []):
            lines.append(f"- curated {g['field']}: `{json.dumps(g['entry'], ensure_ascii=False)[:400]}`")
        upd = load_json(Path(staged_dir) / f"{digits(s)}.json")
        lines.append(f"- updated situation: {upd.get('situation', '')}")
        before = load_json(Path(rehearsal_dir) / "profiles_before" / f"{digits(s)}.json") or {}
        for f in ("pressures", "arguments_that_should_land", "likely_tradeables", "key_quotes"):
            for e in upd.get(f, [])[len(before.get(f, [])) :]:
                lines.append(f"- update +{f}: `{json.dumps(e, ensure_ascii=False)[:400]}`")
        lines.append("")
    report = "\n".join(lines) + "\n"
    (Path(staged_dir) / "REHEARSAL.md").write_text(report, encoding="utf-8")
    return rows, report
