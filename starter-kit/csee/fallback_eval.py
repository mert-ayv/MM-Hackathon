"""Evaluate fallback.auto_profile without quota.

    uv run python -m csee.fallback_eval loo            leave-one-out over the 46 curated profiles (+ type c)
    uv run python -m csee.fallback_eval sim [--seeds 5] local simulator: base with curated vs auto profiles

Leave-one-out: hide a curated profile (and drop it from the archetype priors), generate the auto profile
from the data (type b) or from the case file and opening e-mail alone with the supplier masked out of
the data package (type c), and compare the fields the agent uses.

Simulator: the simulated suppliers always use the real data and curated profiles; only the agent's
view changes - curated profiles, auto profiles (b), auto profiles with the supplier and its parts
masked from the agent's package (c), (c) with the case carrying a `cost:` fact for the part, and (c)
with the price-heuristic floor fed in as the full cost.
"""

import argparse
import json
import os
import statistics
from pathlib import Path

from arena_kit.data import DataPackage

from . import fallback, intel, localsim
from .agent import CseeAgent
from .runner import play_case

ROOT = Path(__file__).parents[2]
OPENINGS = Path(__file__).parents[1] / "tests" / "fixtures" / "practice_openings.json"
CASES = json.loads((Path(__file__).parent / "cases" / "practice.json").read_text())


def package():
    pkg = DataPackage(os.environ.get("ARENA_DATA_EVAL") or ROOT / "data")
    pkg.lookup("")
    return pkg


class MaskedPackage:
    """The package as an agent sees it when a supplier (and its parts) are new: every row naming them is gone."""

    def __init__(self, pkg, hidden):
        self.pkg, self.hidden = pkg, set(hidden)
        self.digits = {h.split(":")[-1] for h in self.hidden}

    def _hidden_ref(self, ref, fact=None):
        body = ref.split(":", 1)[-1]
        if any(body.startswith(d) for d in self.digits):
            return True
        fact = fact or {}
        return any(fact.get(k) in self.hidden for k in ("supplier", "supplier_id", "part", "part_id"))

    def query(self, sql, params=(), limit=200):
        if any(p in self.hidden for p in params):
            return []
        rows = self.pkg.query(sql, params, limit)
        return [r for r in rows if not any(v in self.hidden for v in r.values() if isinstance(v, str))]

    def lookup(self, ref):
        f = self.pkg.lookup(ref)
        return None if f is None or self._hidden_ref(ref, f) else f

    def ids(self, prefix):
        return [i for i in self.pkg.ids(prefix) if self.lookup(i) is not None]

    def document(self, ref):
        if self.lookup(ref) is None:
            raise FileNotFoundError(ref)
        return self.pkg.document(ref)


def curated(sid):
    return json.loads((fallback.PROFILES / f"{sid.split(':')[-1]}.json").read_text())


def case_for(p):
    """The practice case with this supplier, else a renewal of its first profiled part."""
    sid = p["supplier_id"]
    for c in CASES:
        if sid in c["suppliers"]:
            return c
    parts = p.get("parts") or [{}]
    part = next((x for x in parts if x.get("current_price") and x.get("should_cost_unit")), None) or next(
        (x for x in parts if x.get("current_price")), parts[0]
    )
    return {
        "case_id": f"case:LOO-{sid}",
        "type": "renewal",
        "title": f"Renewal for {part.get('name')}",
        "briefing": "",
        "parts": [part.get("part_id")] if part.get("part_id") else [],
        "suppliers": [sid],
        "negotiable": ["unit_price"],
        "buyer": {
            "current_unit_price": part.get("current_price"),
            "category_goal": fallback.CATEGORY_GOAL.get(p.get("category"), "leverage"),
        },
    }


def opening_for(p, case, openings):
    """The real round-0 e-mail when we have one, else a bland quote that names the supplier."""
    sid = p["supplier_id"]
    if sid in openings:
        o = openings[sid]
        return {
            "from": f"sales@{sid}",
            "body": o["body"],
            "term_sheets": [{"terms": o["terms"]}],
            "signals": o["signals"],
        }
    price = (case.get("buyer") or {}).get("current_unit_price") or 100.0
    body = (
        f"Dear customer,\n\nthank you for your enquiry. We offer EUR {price * 1.05:.2f} per unit.\n"
        f"This offer stays valid for 30 days.\n\nKind regards\nSales\n{p['name']}"
    )
    return {"from": f"sales@{sid}", "body": body, "term_sheets": [{"terms": {"unit_price": round(price * 1.05, 2)}}]}


def type_c_case(case, pkg, sid):
    """A case as a new supplier would bring it: the trigger letter travels in `case.facts`."""
    c = json.loads(json.dumps(case))
    facts = dict(c.get("facts") or {})
    if c.get("trigger_doc") and pkg.lookup(c["trigger_doc"]):
        facts[c["trigger_doc"]] = pkg.lookup(c["trigger_doc"])
    c["facts"] = facts
    return c


def payment_trade(p):
    """agent.sheets(): the faster-payment trade sheet fires for this profile."""
    values = " ".join(p.get("what_it_values", [])).lower()
    levers = [t.get("lever") for t in p.get("likely_tradeables", [])]
    return "cash" in values or "payment" in values or "payment_days" in levers


def compare(cur, auto, ref_floor):
    fc, fa = fallback._features(cur), fallback._features(auto)
    pc = {t for t in fc["pressures"] if t != "other"}
    pa = {t for t in fa["pressures"] if t != "other"}
    vc, va = fc["values"][:3], fa["values"][:4]
    lc, la = fc["levers"][:3], fa["levers"][:4]
    floor = auto.get("floor_estimate")
    return {
        "floor_err": abs(floor / ref_floor - 1) if floor and ref_floor else None,
        "floor_method": auto.get("floor_method"),
        "cash_ok": ("cash" in pc) == ("cash" in pa),
        "pay_ok": payment_trade(cur) == payment_trade(auto),
        "press_jac": len(pc & pa) / len(pc | pa) if pc | pa else 1.0,
        "values_rec": len(set(vc) & set(va)) / len(vc) if vc else 1.0,
        "levers_rec": len(set(lc) & set(la)) / len(lc) if lc else 1.0,
        "style_ok": bool(set(fc["styles"][:1]) & set(fa["styles"])),
        "avoid_ok": set(fc["avoid"]) == set(fa["avoid"]),
    }


def loo(pkg, enrich=False):
    openings = json.loads(OPENINGS.read_text()) if OPENINGS.exists() else {}
    rows = []
    for path in sorted(fallback.PROFILES.glob("[0-9]*.json")):
        cur = json.loads(path.read_text())
        sid = cur["supplier_id"]
        table = fallback.build_archetypes(fallback.curated_profiles(exclude={sid}))
        case = case_for(cur)
        country = cur.get("country") or "DE"
        ref, _ = intel.estimate_full_cost(case, pkg, sid, country)
        opening = opening_for(cur, case, openings)
        out = {"sid": sid, "cat": cur.get("category"), "real_opening": sid in openings}
        # b: in the data, profile hidden; c: only the case file and the opening e-mail
        b = fallback.auto_profile(sid, case, pkg, opening, table)
        masked = MaskedPackage(pkg, {sid, *case.get("parts", [])})
        cc = type_c_case(case, pkg, sid)
        c = fallback.auto_profile(sid, cc, masked, opening, table)
        cc_cost = json.loads(json.dumps(cc))
        for part in case.get("parts", []):
            ref_id = f"cost:{part.split(':')[-1]}"
            if pkg.lookup(ref_id):
                cc_cost["facts"][ref_id] = pkg.lookup(ref_id)
        c2 = fallback.auto_profile(sid, cc_cost, masked, opening, table)
        empty = {"what_it_values": [], "likely_tradeables": [], "pressures": [], "persona": {}}
        out["b"], out["c"], out["c_cost"], out["empty"] = (compare(cur, x, ref) for x in (b, c, c2, empty))
        if enrich and sid in openings:  # the optional model on top of (c): one Haiku call per supplier
            c_llm = json.loads(json.dumps(c))
            try:
                fallback.enrich_async(c_llm, cc, opening, budget_s=8).result(timeout=12)
            except Exception as e:
                print(sid, "enrich failed:", repr(e))
            out["c_llm"] = compare(cur, c_llm, ref)
            out["c_real"] = out["c"]
        out["c_country_ok"] = c.get("country") == country
        out["c_owner_ok"] = c.get("owner_type") == cur.get("owner_type")
        out["c_name_ok"] = c.get("name") == cur.get("name")
        rows.append(out)
    return rows


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else float("nan")


def report_loo(rows):
    metrics = [
        ("floor_err", "floor error (mean abs)"),
        ("cash_ok", "cash pressure agrees"),
        ("pay_ok", "payment trade fires as curated"),
        ("press_jac", "pressures Jaccard"),
        ("values_rec", "values: curated top-3 in auto top-4"),
        ("levers_rec", "tradeables: curated top-3 in auto"),
        ("style_ok", "persona style tag matches"),
        ("avoid_ok", "avoided claim kinds equal"),
    ]
    lines = [
        "| metric | empty profile (before) | (b) data, profile hidden | (c) case + opening only | (c) + cost fact |",
        "|---|---|---|---|---|",
    ]
    for key, label in metrics:
        vals = [
            mean([float(r[arm][key]) if r[arm][key] is not None else None for r in rows])
            for arm in ("empty", "b", "c", "c_cost")
        ]
        lines.append(f"| {label} | " + " | ".join("-" if v != v else f"{v:.2f}" for v in vals) + " |")
    sub = [r for r in rows if "c_llm" in r]
    if sub:
        lines += [
            "",
            f"with the model, on the {len(sub)} suppliers with a real opening e-mail:",
            "| metric | (c) deterministic | (c) + Haiku enrich |",
            "|---|---|---|",
        ]
        for key, label in metrics[1:]:
            vals = [mean([float(r[arm][key]) for r in sub]) for arm in ("c_real", "c_llm")]
            lines.append(f"| {label} | " + " | ".join(f"{v:.2f}" for v in vals) + " |")
    n = len(rows)
    lines.append(
        f"\n(c) guessed correctly from e-mail/case only: name {sum(r['c_name_ok'] for r in rows)}/{n}, "
        f"country {sum(r['c_country_ok'] for r in rows)}/{n}, owner type {sum(r['c_owner_ok'] for r in rows)}/{n}; "
        f"{sum(r['real_opening'] for r in rows)} with a real opening e-mail"
    )
    lines.append("\nper supplier (b / c): floor err, cash, pay, pressures J, values rec")

    def f(a):
        floor = f"{a['floor_err']:.2f}" if a["floor_err"] is not None else "-"
        flags = ("Y" if a["cash_ok"] else "n") + ("Y" if a["pay_ok"] else "n")
        return f"{floor} {flags} {a['press_jac']:.2f} {a['values_rec']:.2f}"

    for r in rows:
        lines.append(f"{r['sid']} {r['cat']:<15} b: {f(r['b'])}  |  c: {f(r['c'])} ({r['c']['floor_method']})")
    return "\n".join(lines)


def sim(pkg, seeds=5, cases=None, arms=None):
    arms = arms or ["curated", "none_b", "auto_b", "none_c", "auto_c", "auto_c_cost", "auto_c_qfloor"]
    real_load, real_arch, real_for = intel.load_profile, fallback.archetypes, fallback.profile_for
    scores = {a: {} for a in arms}
    for case in CASES:
        if cases and case["case_id"] not in cases:
            continue
        sids = set(case["suppliers"])
        table = fallback.build_archetypes(fallback.curated_profiles(exclude=sids))
        for arm in arms:
            for seed in range(seeds):
                tbl = localsim.LocalTable(case, pkg, seed)  # suppliers: real data + curated profiles
                agent_pkg, agent_case = pkg, case
                if arm != "curated":
                    intel.load_profile = lambda s, _r=real_load, _h=sids: {} if s in _h else _r(s)
                    fallback.archetypes = lambda _t=table: _t
                if arm.startswith("none"):  # the agent before fallback.py: an empty profile
                    fallback.profile_for = lambda *a, **k: {}
                if arm.startswith(("auto_c", "none_c")):
                    agent_pkg = MaskedPackage(pkg, sids | set(case["parts"]))
                    agent_case = type_c_case(case, pkg, None)
                    if arm == "auto_c_cost":
                        for part in case["parts"]:
                            ref = f"cost:{part.split(':')[-1]}"
                            if pkg.lookup(ref):
                                agent_case["facts"][ref] = pkg.lookup(ref)
                fallback.FEED_QUOTE_FLOOR = arm == "auto_c_qfloor"
                try:
                    tbl.case = case
                    res = play_case(_Table(tbl, agent_case), case["case_id"], CseeAgent(agent_pkg))
                    s = res.get("score") or 0.0
                except Exception as e:
                    print(arm, case["case_id"], seed, "ERROR", repr(e))
                    s = 0.0
                finally:
                    intel.load_profile, fallback.archetypes, fallback.FEED_QUOTE_FLOOR = real_load, real_arch, False
                    fallback.profile_for = real_for
                scores[arm].setdefault(case["case_id"], []).append(s)
    return scores


class _Table:
    """LocalTable, but the agent receives `agent_case` (e.g. with case.facts) from `open`."""

    def __init__(self, table, agent_case):
        self.t, self.agent_case = table, agent_case
        self.done = None

    def open(self, case_id):
        _, threads = self.t.open(case_id)
        return self.agent_case, threads

    def __getattr__(self, name):
        return getattr(self.t, name)


def report_sim(scores):
    arms = list(scores)
    cases = sorted(next(iter(scores.values())))
    lines = ["| case | " + " | ".join(arms) + " |", "|---" * (len(arms) + 1) + "|"]
    for c in cases:
        lines.append(f"| {c[5:]} | " + " | ".join(f"{mean(scores[a][c]):.3f}" for a in arms) + " |")
    means = {a: mean([mean(v) for v in scores[a].values()]) for a in arms}
    lines.append("| **mean** | " + " | ".join(f"**{means[a]:.3f}**" for a in arms) + " |")
    goal = {c["case_id"]: c["buyer"].get("category_goal") for c in CASES}
    other = {
        a: mean([mean(v) for c, v in scores[a].items() if goal[c] not in ("stabilise", "secure_supply")]) for a in arms
    }
    lines.append("| mean, non-relationship goals* | " + " | ".join(f"{other[a]:.3f}" for a in arms) + " |")
    lines.append("| loss vs curated | " + " | ".join(f"{means[a] - means[arms[0]]:+.3f}" for a in arms) + " |")
    lines.append(
        "\n*localsim scores C without the relationship charge, so in stabilise/secure_supply cases an agent"
        " without a floor estimate squeezes harder and looks better than it would on the arena."
    )
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="csee.fallback_eval")
    ap.add_argument("cmd", choices=["loo", "sim"])
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--cases", nargs="*")
    ap.add_argument("--arms", nargs="*")
    ap.add_argument("--enrich", action="store_true", help="loo: also run the Haiku enrichment (costs a few cents)")
    a = ap.parse_args(argv)
    import logging

    logging.getLogger("csee").setLevel(logging.ERROR)
    pkg = package()
    if a.cmd == "loo":
        if a.enrich:
            from arena_kit.cli import load_env

            load_env()
        print(report_loo(loo(pkg, a.enrich)))
    else:
        print(report_sim(sim(pkg, a.seeds, a.cases, a.arms)))


if __name__ == "__main__":
    main()
