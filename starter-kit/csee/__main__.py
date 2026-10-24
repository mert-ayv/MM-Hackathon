"""csee command line - run from starter-kit/ with .env filled in.

    uv run python -m csee play case:P01            one case with our agent (prints score + replay link)
    uv run python -m csee run [--set practice]     every hosted case of a set, in parallel
    uv run python -m csee final                    THE LIVE FINAL: waits for wave 1, plays all 5 waves
    uv run python -m csee eval [--set practice]    fetch finished sessions into runs/, report vs house agent
    uv run python -m csee show <session_id>        one negotiation, move by move (from runs/)
    uv run python -m csee board                    every variant x case from the team ledger (experiments/)
    uv run python -m csee bench --variants base v2 --repeat 3   FREE: sandbox D01+D02, N times each

Practice costs quota (200 / 24h for the whole team): `run`/`play` on practice cases need --confirm
and refuse to go below the reserve of 30 sessions. Test on `bench` (free) first.

Every play/run is logged to experiments/<date>-<author>.jsonl with --variant, commit and --note.

Without an LLM key (ANTHROPIC_API_KEY or LLM_API_KEY) the agent writes from templates.
"""

import argparse
import json
import logging
import os
from pathlib import Path

from arena_kit.cli import load_env, summary
from arena_kit.client import ArenaClient
from arena_kit.play import hosted

from . import evaluate, ledger, variants
from .agent import CseeAgent
from .runner import play_all, play_case, play_waves


def agent_factory(use_llm=True, variant="base"):
    package = None
    data = os.environ.get("ARENA_DATA", "data/package")
    if Path(data).exists():
        from arena_kit.data import DataPackage

        package = DataPackage(data)
        package.lookup("")  # build the ID index once, before agents share it
    writer = None
    if use_llm and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY")):
        from arena_kit.agents.llm import llm_from_env

        from .writer import LLMWriter

        writer = LLMWriter(llm_from_env())
    params = variants.params(variant)
    agent_factory.llm = writer is not None
    return lambda: CseeAgent(package, writer, params)


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(prog="csee")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="template e-mails even if an LLM key is set")
    ap.add_argument("--variant", default="base", help="a preset from csee/variants.py")
    ap.add_argument("--note", default="", help="free text stored with every ledger row")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("play")
    p.add_argument("case_id")
    r = sub.add_parser("run")
    r.add_argument("--set", default="practice", choices=["practice", "sandbox"])
    r.add_argument("--parallel", type=int, default=8)
    r.add_argument("--cases", nargs="*", help="only these case ids")
    r.add_argument("--confirm", action="store_true", help="practice only: yes, spend the quota")
    p.add_argument("--confirm", action="store_true", help="practice only: yes, spend the quota")
    bn = sub.add_parser("bench", help="FREE: sandbox cases, several times per variant")
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
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(threadName)s %(message)s",
    )

    if args.cmd == "play":
        from arena_kit.play import RemoteTable

        client = ArenaClient()
        if args.case_id.startswith("case:P"):
            guard_quota(client, 1, args.confirm)
        factory = agent_factory(not args.no_llm, args.variant)
        result = play_case(RemoteTable(client), args.case_id, factory())
        log_row(args, args.case_id, "practice" if "case:P" in args.case_id else "sandbox", result)
        print(json.dumps(summary(result), indent=2, ensure_ascii=False))
        if result.get("replay_url") or result.get("session_id"):
            print("replay:", result.get("replay_url"))
    elif args.cmd == "run":
        client = ArenaClient()
        ids = args.cases or [c["case_id"] for c in hosted(client.cases(args.set))]
        if args.set == "practice":
            guard_quota(client, len(ids), args.confirm)
        out = play_all(client, ids, agent_factory(not args.no_llm, args.variant), min(args.parallel, 10))
        for cid, res in out.items():
            log_row(args, cid, args.set, res)
            print(cid, json.dumps(summary(res)) if isinstance(res, dict) else f"ERROR {res}")
    elif args.cmd == "final":
        client = ArenaClient()
        out = play_waves(client, agent_factory(not args.no_llm, args.variant), args.waves, min(args.parallel, 10))
        for cid, res in out.items():
            log_row(args, cid, "final", res)
            print(cid, json.dumps(summary(res)) if isinstance(res, dict) else f"ERROR {res}")
    elif args.cmd == "bench":
        client = ArenaClient()
        ids = [c["case_id"] for c in client.cases("sandbox")]
        jobs = [(v, cid) for v in args.variants for cid in ids for _ in range(args.repeat)]
        from concurrent.futures import ThreadPoolExecutor

        from arena_kit.play import RemoteTable

        factories = {v: agent_factory(not args.no_llm, v) for v in args.variants}

        def one(job):
            v, cid = job
            try:
                res = play_case(RemoteTable(client), cid, factories[v]())
            except Exception as e:  # keep the bench going
                res = e
            args.variant = v
            ledger.record(cid, "sandbox", res, v, variants.describe(v), getattr(agent_factory, "llm", False), args.note)
            return v, cid, res

        with ThreadPoolExecutor(max_workers=min(args.parallel, 9)) as pool:
            for v, cid, res in pool.map(one, jobs):
                print(
                    v, cid, f"{res.get('score'):.3f}" if isinstance(res, dict) and res.get("score") is not None else res
                )
        rows = [r for r in ledger.load() if r["variant"] in args.variants and r.get("commit") == ledger.commit()]
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
        print(ledger.board(ledger.load(), house, args.set))


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
    ledger.record(case_id, set_, result, args.variant, variants.describe(args.variant), llm, args.note)


if __name__ == "__main__":
    main()
