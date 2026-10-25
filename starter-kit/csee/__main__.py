"""csee command line - run from starter-kit/ with .env filled in.

    uv run python -m csee play case:P01            one case with our agent (prints score + replay link)
    uv run python -m csee run [--set practice]     every hosted case of a set, in parallel
    uv run python -m csee final                    THE LIVE FINAL: waits for wave 1, plays all 5 waves
    uv run python -m csee eval [--set practice]    fetch finished sessions into runs/, report vs house agent
    uv run python -m csee show <session_id>        one negotiation, move by move (from runs/)
    uv run python -m csee board                    every variant x case from the team ledger (experiments/)
    uv run python -m csee bench --variants base v2 --repeat 3   FREE: sandbox D01+D02, N times each
    uv run python -m csee sim --agents base ege                FREE + offline: compare team agents

`--agent NAME` picks a team agent from csee/agents/ (default `base`), `--variant` its parameter preset.

Practice costs quota (200 / 24h for the whole team): `run`/`play` on practice cases need --confirm
and refuse to go below the reserve of 30 sessions. Test on `bench` (free) first.

Every play/run is logged to experiments/<date>-<author>.jsonl with --agent, --variant, commit and --note.
Every command that plays (play, run, final, sim, bench) also writes a run log for the dashboard:
runs/<YYYYMMDD-HHMMSS>-<agent>-<set>/ (docs/run-log.md); --no-runlog turns it off.

Without an LLM key (ANTHROPIC_API_KEY or LLM_API_KEY) the agent writes from templates.
"""

import argparse
import json
import logging
import os
from pathlib import Path

import httpx

from arena_kit.cli import load_env, summary
from arena_kit.client import ArenaClient
from arena_kit.play import hosted

from . import agents, evaluate, final_est, ledger, runlog, variants
from .datapkg import shared
from .runner import play_all, play_case, play_waves


def find_data():
    """The data package: ARENA_DATA (the kit's `arena data` unpacks to data/package), else the copy
    checked into the repo root (`../data` from starter-kit/). None if neither exists."""
    here = Path(__file__).resolve().parents[2]  # the repo root
    for p in (os.environ.get("ARENA_DATA"), "data/package", here / "data"):
        if p and (Path(p) / "facts.json").is_file():
            return str(p)
    return None


def runtime_client(**kwargs):
    """Return control promptly on a lost connection; keep long supplier reads.

    The runner re-reads failed sends and retries until its case deadline. Six
    client retries with 180-second connection timeouts can hide a whole wave
    from that recovery loop. Two retries retain the same move ID in the kit.
    """
    return ArenaClient(retries=2, timeout=httpx.Timeout(180, connect=5, write=15, pool=5), **kwargs)


def agent_factory(use_llm=True, variant="base", agent="base"):
    cls = agents.get(agent)
    package = None
    data = find_data()
    if data:
        from arena_kit.data import DataPackage

        package = shared(DataPackage(data))  # one SQLite connection for all cases: serialize access
        package.lookup("")  # build the ID index once, before agents share it
    else:  # no should-cost, no floors, no data claims: the agent still plays, but much weaker
        logging.getLogger("csee").warning(
            "NO DATA PACKAGE (ARENA_DATA=%s, no ../data): playing without data", os.environ.get("ARENA_DATA")
        )
    writer = None
    if use_llm and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")):
        from .llm import complete_from_env
        from .writer import LLMWriter

        writer = LLMWriter(complete_from_env())  # prompt caching on the stable prefix
    params = variants.params(variant)
    agent_factory.llm = writer is not None
    return lambda: cls(package, writer, params)


def stay_awake():
    """macOS: keep the machine awake while this process lives. Sat night a laptop slept 51 min mid-run; the arena's
    60 s clock ran on, the session timed out and a 0.794 final offer was lost (P11). `caffeinate -w` ends with us."""
    import shutil
    import subprocess
    import sys

    if sys.platform == "darwin" and shutil.which("caffeinate"):
        try:
            # no inherited pipes and its own session: holding our stdout would keep `| tee` open after a crash and
            # stall the final's restart loop
            subprocess.Popen(
                ["caffeinate", "-dimsu", "-w", str(os.getpid())],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as e:
            logging.getLogger("csee").warning("caffeinate failed: %s - keep the machine awake by hand", e)


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(prog="csee")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="template e-mails even if an LLM key is set")
    ap.add_argument("--agent", default="base", choices=list(agents.AGENTS), help="a team agent from csee/agents/")
    ap.add_argument("--variant", default="base", help="a preset from csee/variants.py")
    ap.add_argument("--note", default="", help="free text stored with every ledger row")
    ap.add_argument("--no-runlog", action="store_true", help="don't write the run log (runs/<run_id>/)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("play")
    p.add_argument("case_id")
    r = sub.add_parser("run")
    r.add_argument("--set", default="practice", choices=["practice", "sandbox"])
    r.add_argument("--parallel", type=int, default=8)
    r.add_argument("--cases", nargs="*", help="only these case ids")
    r.add_argument("--confirm", action="store_true", help="practice only: yes, spend the quota")
    p.add_argument("--confirm", action="store_true", help="practice only: yes, spend the quota")
    sm = sub.add_parser("sim", help="FREE + offline: local supplier simulator on all practice case files")
    sm.add_argument("--agents", nargs="+", help="team agents to compare (default: --agent)")
    sm.add_argument("--variants", nargs="+", default=["base"])
    sm.add_argument("--seeds", type=int, default=3)
    sm.add_argument("--cases", nargs="*")
    sm.add_argument(
        "--llm", action="store_true",
        help="exercise the model against local suppliers (LLM charges, no arena quota)",
    )
    bn = sub.add_parser("bench", help="FREE: sandbox cases, several times per variant")
    bn.add_argument("--agents", nargs="+", help="team agents to compare (default: --agent)")
    bn.add_argument("--variants", nargs="+", default=["base"])
    bn.add_argument("--repeat", type=int, default=3)
    bn.add_argument("--parallel", type=int, default=8)
    f = sub.add_parser("final")
    f.add_argument("--parallel", type=int, default=10)
    f.add_argument("--waves", type=int, default=5)
    e = sub.add_parser("eval")
    e.add_argument("--set", default="practice", choices=["practice", "sandbox", "final"])
    s = sub.add_parser("show")
    s.add_argument("session_id")
    bd = sub.add_parser("board")
    bd.add_argument("--set", default="practice", choices=["practice", "sandbox", "final"])
    bd.add_argument("--final", action="store_true", help="estimated Live-Final score (8-min wave) instead")
    fe = sub.add_parser("finalest", help="FREE: practice score vs estimated Live-Final score, from run logs")
    fe.add_argument("run_dirs", nargs="*", help="default: the 10 newest practice/sandbox runs")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(threadName)s %(message)s",
    )
    runs = {}
    if args.cmd in ("final", "run", "play"):
        stay_awake()
    try:
        command(args, runs)
    finally:
        for run in runs.values():
            run.end()
        if runs:
            print("run log:", ", ".join(str(r.dir) for r in runs.values()))


def new_run(args, runs, set_, agent=None, variant=None):
    """The run log for one agent/variant in this invocation (None with --no-runlog, or if it can't be made)."""
    agent, variant = agent or args.agent, variant or args.variant
    if args.no_runlog:
        return None
    if (agent, variant) not in runs:
        label = agent if variant == "base" else f"{agent}-{variant}"
        try:
            runs[agent, variant] = runlog.Run(
                label,
                set_,
                args.note,
                agent_name=agent,
                variant=variant,
                llm=getattr(agent_factory, "llm", False),
                command=args.cmd,
            )
        except Exception as e:  # the log is never worth a failed run
            logging.getLogger("csee").warning("run log off: %s", e)
            return None
    return runs[agent, variant]


def command(args, runs):
    if getattr(args, "variants", None) == ["base"] and args.variant != "base":
        args.variants = [args.variant]  # `--variant v14 bench` means v14, not the default list
    if args.cmd == "play":
        from arena_kit.play import RemoteTable

        client = runtime_client()
        if args.case_id.startswith("case:P"):
            guard_quota(client, 1, args.confirm)
        factory = agent_factory(not args.no_llm, args.variant, args.agent)
        set_ = "practice" if "case:P" in args.case_id else "sandbox"
        result = play_case(RemoteTable(client), args.case_id, factory(), run=new_run(args, runs, set_))
        log_row(args, args.case_id, set_, result)
        print(json.dumps(summary(result), indent=2, ensure_ascii=False))
        if result.get("replay_url") or result.get("session_id"):
            print("replay:", result.get("replay_url"))
    elif args.cmd == "run":
        client = runtime_client()
        ids = args.cases or [c["case_id"] for c in hosted(client.cases(args.set))]
        if args.set == "practice":
            guard_quota(client, len(ids), args.confirm)
        factory = agent_factory(not args.no_llm, args.variant, args.agent)
        out = play_all(client, ids, factory, min(args.parallel, 10), run=new_run(args, runs, args.set))
        for cid, res in out.items():
            log_row(args, cid, args.set, res)
            print(cid, json.dumps(summary(res)) if isinstance(res, dict) else f"ERROR {res}")
    elif args.cmd == "final":
        # Bounded connection retries, then the runner's deadline-aware recovery.
        # The kit preserves X-Move-Id across the client's retries.
        client = runtime_client()
        factory = agent_factory(not args.no_llm, args.variant, args.agent)
        out = play_waves(client, factory, args.waves, min(args.parallel, 10), run=new_run(args, runs, "final"))
        for cid, res in out.items():
            log_row(args, cid, "final", res)
            print(cid, json.dumps(summary(res)) if isinstance(res, dict) else f"ERROR {res}")
    elif args.cmd == "sim":
        import statistics

        from . import localsim

        if args.llm and args.no_llm:
            raise SystemExit("sim --llm conflicts with --no-llm")
        logging.getLogger("csee").setLevel(
            logging.INFO if args.verbose else logging.WARNING if args.llm else logging.ERROR
        )
        cases = [c for c in localsim.cases() if not args.cases or c["case_id"] in args.cases]
        rows = []
        for a in args.agents or [args.agent]:
            for v in args.variants:
                factory = agent_factory(args.llm, v, a)
                llm = bool(getattr(agent_factory, "llm", False))
                if args.llm and not llm:
                    raise SystemExit(
                        "sim --llm requires a configured model and key; refusing a silent template comparison"
                    )
                if args.llm and a == "ege" and not factory().llm:
                    raise SystemExit("Ege's tool strategist requires LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY")
                run = new_run(args, runs, "sim", a, v)
                for case in cases:
                    for seed in range(args.seeds):
                        mode = (
                            "local suppliers + model API; model decisions can take tens of seconds"
                            if llm else "offline"
                        )
                        print(f"SIM {a}/{v} {case['case_id']} seed={seed}: started ({mode})", flush=True)
                        table = localsim.LocalTable(case, factory().pkg, seed)
                        try:
                            res = play_case(table, case["case_id"], factory(), run=run)
                        except Exception as e:
                            res = {"score": 0.0, "error": repr(e)}
                            print(a, v, case["case_id"], seed, "ERROR", e, flush=True)
                        print(
                            f"SIM {a}/{v} {case['case_id']} seed={seed}: finished, score={res.get('score')}",
                            flush=True,
                        )
                        rows.append(
                            {
                                "agent": a,
                                "variant": v,
                                "commit": ledger.commit(),
                                "llm": llm,
                                "set": "localsim",
                                "case_id": case["case_id"],
                                "score": res.get("score") or 0.0,
                            }
                        )
        print(ledger.board(rows, None, "localsim"))
        for label in sorted({ledger.label(r) for r in rows}):
            print(label, "mean", round(statistics.mean(r["score"] for r in rows if ledger.label(r) == label), 3))
    elif args.cmd == "bench":
        client = ArenaClient()
        ids = [c["case_id"] for c in client.cases("sandbox")]
        names = args.agents or [args.agent]
        jobs = [(a, v, cid) for a in names for v in args.variants for cid in ids for _ in range(args.repeat)]
        from concurrent.futures import ThreadPoolExecutor

        from arena_kit.play import RemoteTable

        factories = {(a, v): agent_factory(not args.no_llm, v, a) for a in names for v in args.variants}
        llm = getattr(agent_factory, "llm", False)
        bench_runs = {(a, v): new_run(args, runs, "sandbox", a, v) for a in names for v in args.variants}

        def one(job):
            a, v, cid = job
            try:
                res = play_case(RemoteTable(client), cid, factories[a, v](), run=bench_runs[a, v])
            except Exception as e:  # keep the bench going
                res = e
            ledger.record(
                cid,
                "sandbox",
                res,
                v,
                variants.describe(v),
                llm,
                args.note,
                agent=a,
                final_est=final_est.for_case(a, v, cid),
            )
            return a, v, cid, res

        with ThreadPoolExecutor(max_workers=min(args.parallel, 9)) as pool:
            for a, v, cid, res in pool.map(one, jobs):
                score = f"{res.get('score'):.3f}" if isinstance(res, dict) and res.get("score") is not None else res
                print(a, v, cid, score)
        rows = [
            r
            for r in ledger.load()
            if (r.get("agent") or "base") in names
            and r["variant"] in args.variants
            and r.get("commit") == ledger.commit()
        ]
        print(ledger.board(rows, None, "sandbox"))
    elif args.cmd == "eval":
        client = ArenaClient()
        sessions = evaluate.fetch(client, args.set)
        text = evaluate.report(sessions, evaluate.house_scores(os.environ.get("ARENA_URL", "https://arena.tacto.ai")))
        (evaluate.RUNS / f"report-{args.set}.md").write_text(text)
        print(text)
    elif args.cmd == "show":
        path = evaluate.RUNS / "sessions" / f"{args.session_id.replace('/', '_')}.json"
        if not path.exists():
            raise SystemExit(f"{path} not found - run `python -m csee eval` first")
        print(evaluate.show(json.loads(path.read_text())))
    elif args.cmd == "board":
        house = evaluate.house_scores(os.environ.get("ARENA_URL", "https://arena.tacto.ai"))
        print(ledger.board(ledger.load(), house, args.set, final=args.final))
    elif args.cmd == "finalest":
        dirs = (
            args.run_dirs
            or sorted(
                (str(d) for d in final_est.RUNS_ROOT.glob("*") if d.name.endswith(("practice", "sandbox"))),
                key=lambda d: Path(d).stat().st_mtime,
            )[-10:]
        )
        print(final_est.report(dirs))


RESERVE = 30  # practice sessions we always keep for Sunday morning (data release, pre-flight)


def guard_quota(client, n, confirm):
    left = (client.me().get("practice") or {}).get("left", 0)
    print(f"practice quota: {left} left; this run uses {n}; reserve {RESERVE}")
    if not confirm:
        raise SystemExit(
            "practice costs quota shared by the whole team. Test with `bench` (free) first; add --confirm."
        )
    if left - n < RESERVE:
        raise SystemExit(f"refused: would leave {left - n} < reserve {RESERVE}. Ask the team before going lower.")


def log_row(args, case_id, set_, result):
    llm = getattr(agent_factory, "llm", False)
    params = variants.describe(args.variant)
    est = final_est.for_case(args.agent, args.variant, case_id)
    ledger.record(case_id, set_, result, args.variant, params, llm, args.note, agent=args.agent, final_est=est)


if __name__ == "__main__":
    main()
