"""unified command line - run from starter-kit/ with .env filled in. One shared agent, no variants.

    uv run python -m unified sim [--cases ...]         FREE + offline: the local supplier simulator
    uv run python -m unified play case:P01 --confirm   one case (practice costs quota: ask the team first)
    uv run python -m unified run --confirm             every hosted case of a set, in parallel
    uv run python -m unified final                     THE LIVE FINAL: waits for wave 1, plays all 5 waves

Practice `play`/`run` need --confirm and refuse to go below the reserve of 30 sessions. Every one is logged to
experiments/<date>-<author>.jsonl as agent "unified" with its full parameters (defaults and per-type settings);
read results with csee (`python -m csee board | eval | show`). Every command that plays also writes a run log:
runs/<YYYYMMDD-HHMMSS>-unified-<set>/; --no-runlog turns it off.

Without an LLM key (ANTHROPIC_API_KEY or LLM_API_KEY) the agent writes from templates.
"""

import argparse
import dataclasses
import json
import logging
import os
import statistics
from pathlib import Path

from arena_kit.cli import load_env, summary
from arena_kit.client import ArenaClient
from arena_kit.play import RemoteTable, hosted

from . import ledger, localsim, runlog
from .agent import TYPE_SETTINGS, Params, UnifiedAgent
from .datapkg import shared
from .runner import play_all, play_case, play_waves

AGENT, VARIANT = "unified", "base"  # ledger labels: shows as unified/base@<commit> on csee's board
RESERVE = 30  # practice sessions we always keep for Sunday morning (data release, pre-flight)
log = logging.getLogger("unified")


def describe_params():
    """What ran, for the ledger: the defaults and every per-type override (no hidden prepare() changes)."""
    return {"defaults": dataclasses.asdict(Params()), "by_type": TYPE_SETTINGS}


def find_data():
    """The data package: ARENA_DATA, else data/package (`arena data`), else the repo root's data/."""
    here = Path(__file__).resolve().parents[2]
    for p in (os.environ.get("ARENA_DATA"), "data/package", here / "data"):
        if p and (Path(p) / "facts.json").is_file():
            return str(p)
    return None


def agent_factory(use_llm=True):
    """A function making a fresh agent per case; sets agent_factory.llm."""
    package = None
    data = find_data()
    if data:
        from arena_kit.data import DataPackage

        package = shared(DataPackage(data))  # one SQLite connection for all cases: serialize access
        package.lookup("")  # build the ID index once, before agents share it
    else:
        log.warning("NO DATA PACKAGE (ARENA_DATA=%s, no ../data): playing without data", os.environ.get("ARENA_DATA"))
    writer = None
    if use_llm and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")):
        from .llm import complete_from_env
        from .writer import LLMWriter

        writer = LLMWriter(complete_from_env())  # prompt caching on the stable prefix
    agent_factory.llm = writer is not None
    return lambda: UnifiedAgent(package, writer, Params())


def guard_quota(client, n, confirm):
    left = (client.me().get("practice") or {}).get("left", 0)
    print(f"practice quota: {left} left; this run uses {n}; reserve {RESERVE}")
    if not confirm:
        raise SystemExit("practice costs quota shared by the whole team. Test with `sim` (free) first; add --confirm.")
    if left - n < RESERVE:
        raise SystemExit(f"refused: would leave {left - n} < reserve {RESERVE}. Ask the team before going lower.")


def log_row(args, case_id, set_, result):
    llm = getattr(agent_factory, "llm", False)
    ledger.record(case_id, set_, result, VARIANT, describe_params(), llm, args.note, agent=AGENT)


def new_run(args, set_):
    """The run log of this invocation (None with --no-runlog, or if it can't be made)."""
    if args.no_runlog:
        return None
    try:
        return runlog.Run(
            AGENT,
            set_,
            args.note,
            agent_name=AGENT,
            variant=VARIANT,
            llm=getattr(agent_factory, "llm", False),
            command=args.cmd,
        )
    except Exception as e:  # the log is never worth a failed run
        log.warning("run log off: %s", e)
        return None


def sim(args, run):
    logging.getLogger("unified").setLevel(logging.ERROR)
    factory = agent_factory(False)
    cases = [c for c in localsim.cases() if not args.cases or c["case_id"] in args.cases]
    means = []
    for case in cases:
        scores = []
        for seed in range(args.seeds):
            table = localsim.LocalTable(case, factory().pkg, seed)
            try:
                res = play_case(table, case["case_id"], factory(), run=run)
            except Exception as e:
                res = {"score": 0.0}
                print(case["case_id"], seed, "ERROR", e)
            scores.append(res.get("score") or 0.0)
        means.append(statistics.mean(scores))
        print(f"{case['case_id']:10} {means[-1]:.2f}  ({', '.join(f'{s:.2f}' for s in scores)})")
    print(f"unified@{ledger.commit()} mean {statistics.mean(means):.3f} over {len(cases)} cases x {args.seeds} seeds")


def command(args, run_box):
    if args.cmd == "sim":
        run_box.append(new_run(args, "sim"))
        sim(args, run_box[-1])
        return
    ledger.snapshot()  # the code this logged run executes, before it starts
    client = ArenaClient()
    if args.cmd == "play":
        if args.case_id.startswith("case:P"):
            guard_quota(client, 1, args.confirm)
        factory = agent_factory(not args.no_llm)
        set_ = "practice" if "case:P" in args.case_id else "sandbox"
        run_box.append(new_run(args, set_))
        result = play_case(RemoteTable(client), args.case_id, factory(), run=run_box[-1])
        log_row(args, args.case_id, set_, result)
        print(json.dumps(summary(result), indent=2, ensure_ascii=False))
        if result.get("replay_url") or result.get("session_id"):
            print("replay:", result.get("replay_url"))
        return
    if args.cmd == "run":
        ids = args.cases or [c["case_id"] for c in hosted(client.cases(args.set))]
        if args.set == "practice":
            guard_quota(client, len(ids), args.confirm)
        factory = agent_factory(not args.no_llm)
        run_box.append(new_run(args, args.set))
        out, set_ = play_all(client, ids, factory, min(args.parallel, 10), run=run_box[-1]), args.set
    else:  # final
        factory = agent_factory(not args.no_llm)
        run_box.append(new_run(args, "final"))
        out, set_ = play_waves(client, factory, args.waves, min(args.parallel, 10), run=run_box[-1]), "final"
    for cid, res in out.items():
        log_row(args, cid, set_, res)
        print(cid, json.dumps(summary(res)) if isinstance(res, dict) else f"ERROR {res}")


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(prog="unified")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="template e-mails even if an LLM key is set")
    ap.add_argument("--note", default="", help="free text stored with every ledger row")
    ap.add_argument("--no-runlog", action="store_true", help="don't write the run log (runs/<run_id>/)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sm = sub.add_parser("sim", help="FREE + offline: local supplier simulator on the practice case files")
    sm.add_argument("--seeds", type=int, default=3)
    sm.add_argument("--cases", nargs="*")
    p = sub.add_parser("play")
    p.add_argument("case_id")
    p.add_argument("--confirm", action="store_true", help="practice only: yes, spend the quota")
    r = sub.add_parser("run")
    r.add_argument("--set", default="practice", choices=["practice", "sandbox"])
    r.add_argument("--parallel", type=int, default=8)
    r.add_argument("--cases", nargs="*", help="only these case ids")
    r.add_argument("--confirm", action="store_true", help="practice only: yes, spend the quota")
    f = sub.add_parser("final")
    f.add_argument("--parallel", type=int, default=10)
    f.add_argument("--waves", type=int, default=5)
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(threadName)s %(message)s",
    )
    run_box = []
    try:
        command(args, run_box)
    finally:
        for run in filter(None, run_box):
            run.end()
            print("run log:", run.dir)


if __name__ == "__main__":
    main()
