"""Empirical observations from our completed practice logs, never learned supplier rules.

Offline import: python -m csee.negotiation.memory --runs ../runs
No arena/model requests. Runtime retrieval uses type/goal/fields, not supplier or case identity.
"""

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path
from threading import Lock

LOCK = Lock()
DEFAULT = Path(__file__).with_name("experience.jsonl")


def location():
    return Path(os.environ.get("CSEE_EXPERIENCE_PATH", DEFAULT))


def read(path):
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except ValueError:
            continue
    return rows


def features(case):
    return {
        "type": case.get("type"),
        "goal": case.get("buyer", {}).get("category_goal"),
        "bidders": len(case.get("suppliers", [])),
        "fields": sorted(case.get("negotiable", [])),
    }


def summarize(rows, meta):
    if meta.get("set") != "practice":
        return None  # simulator scores and hidden final outcomes never enter practice evidence
    opened = next((r for r in rows if r.get("type") == "case_opened"), None)
    result = next((r for r in reversed(rows) if r.get("type") == "result"), None)
    if not opened or not result:
        return None
    score = result.get("score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
        return None
    opening = opened.get("opening", {})
    paths = []
    for sid, first in opening.items():
        quote = first.get("priced", {}).get("terms", {}).get("unit_price")
        if not isinstance(quote, (int, float)) or quote <= 0:
            continue
        buys, sells, trades = [], [], set()
        buyer_packages, supplier_packages = [], []

        def terms_view(terms, first=first, quote=quote):
            full = {**opened["case"].get("fixed_terms", {}), **first.get("standard_terms", {}), **terms}
            clause = full.get("index_clause") or {}
            return {
                "price_ratio": round(full["unit_price"] / quote, 4),
                **{f: full.get(f) for f in ("payment_days", "lead_time_days", "contract_months", "incoterm")},
                "indexed": bool(clause),
                "material_share": clause.get("material_share"),
                "deadband_pct": clause.get("deadband_pct"),
            }

        feedback = Counter()
        for r in rows:
            if r.get("supplier_id") != sid:
                continue
            if r.get("type") == "message_sent":
                sheets = r.get("sheets", [])
                if sheets and sheets[0].get("terms", {}).get("unit_price"):
                    buys.append(round(sheets[0]["terms"]["unit_price"] / quote, 4))
                    buyer_packages.append(terms_view(sheets[0]["terms"]))
                if sheets:
                    primary = sheets[0].get("terms", {})
                    for sh in sheets[1:]:
                        trades.update(
                            f for f, v in sh.get("terms", {}).items() if f != "unit_price" and primary.get(f) != v
                        )
            elif r.get("type") == "reply":
                price = (r.get("standing") or {}).get("priced", {}).get("terms", {}).get("unit_price")
                if price:
                    sells.append(round(price / quote, 4))
                    supplier_packages.append(terms_view(r["standing"]["priced"]["terms"]))
                feedback.update(c.get("result", "unknown") for c in r.get("claim_results", []))
        paths.append(
            {
                "buyer_price_ratios": buys,
                "supplier_price_ratios": sells,
                "buyer_packages": buyer_packages,
                "supplier_packages": supplier_packages,
                "probed_fields": sorted(trades),
                "claim_feedback": dict(feedback),
                "awarded": sid == result.get("supplier_id"),
            }
        )
    identity = f"{result.get('run_id')}|{result.get('session_id')}|{result.get('case_id')}"
    return {
        "schema_version": 2,
        "sample_id": hashlib.sha256(identity.encode()).hexdigest()[:20],
        **features(opened["case"]),
        "policy": f"{meta.get('agent')}/{meta.get('variant')}",
        "observed_at": result.get("ts"),
        "deal": bool(result.get("deal")),
        "score": score,
        "paths": paths,
        "limitation": "Uncontrolled historical observation; no causal effect or acceptance probability inferred.",
    }


def append(row, path=None):
    if row is None:
        return
    path = Path(path or location())
    with LOCK:
        if (row["sample_id"], row.get("schema_version")) in {
            (r.get("sample_id"), r.get("schema_version")) for r in read(path)
        }:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def record_log(log):
    if not getattr(log, "enabled", False):
        return
    row = summarize(read(log.path), log.run.meta)
    if row:
        log.event("unified_experience", observation=row)
        append(row)


def recall(case, path=None, limit=6):
    wanted = features(case)
    unique = {r.get("sample_id"): r for r in read(path or location()) if r.get("sample_id")}
    matching = [
        r for r in unique.values() if r.get("type") == wanted["type"] and r.get("goal") == wanted["goal"]
    ]
    matching.sort(
        key=lambda r: (
            r.get("fields") == wanted["fields"],
            r.get("bidders") == wanted["bidders"],
            r.get("observed_at") or "",
        ),
        reverse=True,
    )
    # Include more than one policy when available; many recent runs of one experiment
    # must not erase the evidence from the previous baseline.
    samples, policies = [], Counter()
    for row in matching:
        if policies[row.get("policy")] < 2:
            samples.append(row)
            policies[row.get("policy")] += 1
        if len(samples) == limit:
            break
    samples += [r for r in matching if r not in samples][: max(0, limit - len(samples))]
    return {
        "matching_sample_count": len(matching),
        "shown_sample_count": len(samples),
        "samples": samples,
        "uncertainty": "Descriptive only: policies, data and responses differ. Scores and price paths are not rules.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=location())
    args = parser.parse_args()
    count = 0
    for run in sorted(args.runs.glob("*practice")):
        try:
            meta = json.loads((run / "run.json").read_text())
        except (OSError, ValueError):
            continue
        for path in sorted(run.glob("case*.jsonl")):
            row = summarize(read(path), meta)
            if row:
                append(row, args.output)
                count += 1
    distinct = len({r.get("sample_id") for r in read(args.output)})
    print(f"Read {count} completed practice cases; {distinct} distinct observations in {args.output}")


if __name__ == "__main__":
    main()
