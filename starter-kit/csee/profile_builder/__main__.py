"""Supplier-profile pipeline CLI (run from starter-kit/; LLM commands need --extra anthropic).

    uv run python -m csee.profile_builder facts 70110            hard fields (deterministic JSON)
    uv run python -m csee.profile_builder validate               hard fields vs all curated profiles
    uv run --extra anthropic python -m csee.profile_builder soft 70110 [--model M] [--out DIR]
    uv run --extra anthropic python -m csee.profile_builder update --release ../data/release-sunday [--model M]
    uv run python -m csee.profile_builder apply runs/profiles/<stamp>          copy staged files to profiles/
    uv run python -m csee.profile_builder rehearse build [--since 2026-09-15]   fake release from held-out items
    uv run --extra anthropic python -m csee.profile_builder rehearse run [--suppliers 70110 70240 ...]

Model: --model, else env PROFILE_MODEL, else claude-haiku-5-5. Nothing writes to profiles/ except `apply`
and `update --apply`.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from arena_kit.cli import load_env

from . import facts, llm, validate
from .common import KIT, PROFILES, STAGING, detailed_suppliers, digits, dump, open_package


def main(argv=None):
    load_env(KIT / ".env")
    ap = argparse.ArgumentParser(
        prog="csee.profile_builder", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--data", help="data package folder (default: ARENA_DATA, data/package, ../data)")
    ap.add_argument("--profiles", default=str(PROFILES), help="curated profiles folder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("facts", help="deterministic hard fields of one supplier")
    f.add_argument("supplier")
    v = sub.add_parser("validate", help="hard fields vs the curated profiles, field by field")
    v.add_argument("--out", help="write the markdown report here")
    s = sub.add_parser("soft", help="LLM soft fields (+ hard fields) of suppliers -> staged files")
    s.add_argument("suppliers", nargs="+", help="supplier ids, or 'all'")
    s.add_argument("--model")
    s.add_argument("--out", help="staging folder (default runs/profiles/soft-<stamp>)")
    s.add_argument("--workers", type=int, default=16)
    u = sub.add_parser("update", help="fold a data release into the profiles (staged + diff reports)")
    u.add_argument("--release", required=True, help="unpacked release folder (with facts.json)")
    u.add_argument("--model")
    u.add_argument("--out", help="staging folder (default runs/profiles/<stamp>)")
    u.add_argument("--suppliers", nargs="*", help="only these suppliers (default: all affected)")
    u.add_argument("--workers", type=int, default=16)
    u.add_argument("--apply", action="store_true", help="also copy the staged files into profiles/")
    a = sub.add_parser("apply", help="copy a staged update into profiles/")
    a.add_argument("staged")
    a.add_argument("--only", nargs="*", help="only these suppliers (+ _market.json)")
    r = sub.add_parser("rehearse", help="fake release from held-out recent items; run update; score recovery")
    r.add_argument("step", choices=["build", "run", "score"])
    r.add_argument("--dir", default=str(KIT / "runs" / "rehearsal"))
    r.add_argument("--since", default="2026-09-15")
    r.add_argument("--suppliers", nargs="*")
    r.add_argument("--also", nargs="*", default=[], help="build: extra IDs to hold out (e.g. a memo)")
    r.add_argument("--orphan-memos", action="store_true", help="build: blank the supplier of held-out memos")
    r.add_argument("--model")
    r.add_argument("--staged", help="score: staged folder (default <dir>/staged)")
    args = ap.parse_args(argv)

    if args.cmd == "facts":
        print(dump(facts.build(open_package(args.data), args.supplier)), end="")
    elif args.cmd == "validate":
        res = validate.run(open_package(args.data), profiles=args.profiles)
        if args.out:
            Path(args.out).write_text(res["report"], encoding="utf-8")
    elif args.cmd == "soft":
        _soft(args)
    elif args.cmd == "update":
        from . import update

        pkg = open_package(args.data, args.release)
        model = llm.model_from(args.model)
        res = update.run(pkg, model, args.profiles, args.out, args.suppliers, args.workers)
        if args.apply:
            update.apply(res["out_dir"], args.profiles)
        return 1 if res["errors"] and not res["results"] else 0
    elif args.cmd == "apply":
        from . import update

        update.apply(args.staged, args.profiles, args.only)
    elif args.cmd == "rehearse":
        _rehearse(args)
    return 0


def _soft(args):
    from concurrent.futures import ThreadPoolExecutor

    from . import soft

    pkg = open_package(args.data)
    model = llm.model_from(args.model)
    sups = detailed_suppliers(pkg) if args.suppliers == ["all"] else args.suppliers
    out = Path(args.out or STAGING / time.strftime("soft-%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    def one(s):
        prof, log, row = soft.build(pkg, s, model)
        (out / f"{digits(s)}.json").write_text(dump(prof), encoding="utf-8")
        return s, log, row

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for s, log, row in ex.map(one, sups):
            print(
                f"{s}: {row['seconds']} s, ${row['usd']:.4f}, {len(log)} check notes"
                + "".join(f"\n   {x}" for x in log)
            )
    print(
        f"staged in {out} ({time.time() - t0:.1f} s wall, ${llm.LEDGER.usd:.4f}); not applied - curated profiles untouched"  # noqa: E501
    )


def _rehearse(args):
    from . import rehearse, update

    d = Path(args.dir)
    if args.step == "build":
        rehearse.build(d, args.since, args.data, args.profiles, args.also, args.orphan_memos)
        return
    staged = Path(args.staged or d / "staged")
    if args.step == "run":
        pkg = open_package(d / "package", d / "release-sunday")
        model = llm.model_from(args.model)
        update.run(pkg, model, d / "profiles_before", staged, args.suppliers)
        (staged / "ledger.json").write_text(json.dumps(llm.LEDGER.calls, indent=1), encoding="utf-8")
    rows, report = rehearse.score(d, staged, args.profiles)
    print(report)


if __name__ == "__main__":
    sys.exit(main())
