"""Strategy search on the replay-calibrated P10 bot: every strategy is a real team agent played through
`runner.play_case`; the score is averaged over the bot's worlds, weighted by their priors.

    cd starter-kit && ARENA_DATA=... uv run python ../experiments/capacity/p10_search.py [--fit] [--quick]
"""

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from p10_bot import P10Table, World, normalised  # noqa: E402

from arena_kit.data import DataPackage  # noqa: E402
from csee import variants  # noqa: E402
from csee.__main__ import find_data  # noqa: E402
from csee.agent import CseeAgent  # noqa: E402
from csee.agents.annika_capacity import AnnikaCapacityAgent, KParams  # noqa: E402
from csee.datapkg import shared  # noqa: E402
from csee.runner import play_case  # noqa: E402

logging.getLogger("csee").setLevel(logging.ERROR)
PKG = shared(DataPackage(find_data()))
PKG.lookup("")


def k_agent(name, push=0.0, **k):
    cls = type(name, (AnnikaCapacityAgent,), {"K": replace(KParams(), **k)})
    params = variants.params("v14")
    if push:
        params = replace(params, final_push=push)
    return lambda: cls(PKG, None, params)


class PushK(AnnikaCapacityAgent):
    """annika-k + one unsnapped 1 % price push on its standing final sheet (what v15 meant to do)."""

    def thread_move(self, case, threads, sid):
        from arena_kit.play import latest

        last = latest(threads[sid])
        st = self.threads.get(sid)
        if st and last.get("status") == "final_offer" and not st.pushed and last.get("term_sheets"):
            first = last["term_sheets"][0]["terms"]
            cheapest = self.their_sheet(case, threads[sid], {})[1]
            if cheapest == first:
                st.pushed = 1
                ask = {f: first[f] for f in case["negotiable"]}
                ask["unit_price"] = round(first["unit_price"] * 0.99, 2)
                return {
                    "subject": "Re",
                    "body": "If you can meet us at this price, we sign today.",
                    "term_sheets": [{"terms": ask}],
                    "refs": [],
                }
        return super().thread_move(case, threads, sid)


def base(variant, **over):
    return lambda: CseeAgent(PKG, None, replace(variants.params(variant), **over))


OLD_K = {"anchor_below_open": 0.12, "mode": "v14"}  # annika-k@d720b8c, practice #2

STRATEGIES = {
    "v13 (deep ask, propose its alternative back)": base("v13"),
    "annika-k@d720b8c (12 %, v14 rounds 2+)": k_agent("Kold", **OLD_K),
    "annika-k H2 (3.75 %, converge)": k_agent("KH2"),
    "H2 anchor 2.5 %": k_agent("KH2a", anchor_below_open=0.025),
    "H2 anchor 6 %": k_agent("KH2b", anchor_below_open=0.06),
    "H2 anchor 9 %": k_agent("KH2c", anchor_below_open=0.09),
    "H2 faster steps (share 0.35)": k_agent("KH2d", converge_share=0.35),
    "H2 slower steps (share 0.12, decay 0.75)": k_agent("KH2e", converge_share=0.12, converge_decay=0.75),
}


def play(factory, world):
    table = P10Table(world)
    res = play_case(table, "case:P10", factory())
    return res.get("score") or 0.0, table


def fit():
    """The three real games, reproduced in every world: v1 0.570 and v13 0.671 (final at reply 1), and
    annika-k@d720b8c 0.671 (open at reply 1, hold -> final at reply 2)."""
    games = (
        ("v1", base("v1"), 0.5703),
        ("v13", base("v13"), 0.6709),
        ("annika-k@d720b8c", k_agent("Kold", **OLD_K), 0.6709),
    )
    ws = [w for w, _ in normalised()]
    for name, fac, want in games:
        got = {}
        for w in ws[::37]:
            s, t = play(fac, w)
            statuses = tuple(r[1] for r in t.trace if r[0] == "S")
            got.setdefault((round(s, 4), statuses), 0)
            got[(round(s, 4), statuses)] += 1
        print(f"{name}: real {want}; bot {got}")
    s, t = play(k_agent("Kold", **OLD_K), World())
    for row in t.trace:
        print("   ", row)
    print("   ", t.bot.events)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--quick", action="store_true", help="every --step-th world")
    ap.add_argument("--step", type=int, default=7)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    if a.fit:
        fit()
        return
    ws = normalised()
    if a.quick:
        ws = ws[:: a.step]
        z = sum(w for _, w in ws)
        ws = [(x, w / z) for x, w in ws]
    print(f"{len(ws)} worlds")
    for name, fac in STRATEGIES.items():
        if a.only and not any(o in name for o in a.only):
            continue
        scores = []
        for world, w in ws:
            # pushes are random: average a few seeds
            seeds = range(3) if (world.approve not in (0.0, 1.0) or "push" in name) else range(1)
            for sd in seeds:
                s, _ = play(fac, replace(world, seed=sd))
                scores.append((s, w / len(seeds)))
        mean = sum(s * w for s, w in scores)
        beat = sum(w for s, w in scores if s > 0.6945)
        worse = sum(w for s, w in scores if s < 0.6705)
        zero = sum(w for s, w in scores if s == 0)
        qs = sorted(scores)
        acc, q = 0.0, {}
        for s, w in qs:
            acc += w
            for p in (0.1, 0.5, 0.9):
                if p not in q and acc >= p:
                    q[p] = s
        print(
            f"{name:45s} mean {mean:.4f}  p10/50/90 {q[0.1]:.3f}/{q[0.5]:.3f}/{q[0.9]:.3f}  "
            f"P(>0.694) {beat:.2f}  P(<0.671) {worse:.2f}  P(0) {zero:.2f}"
        )
        sys.stdout.flush()


if __name__ == "__main__":
    main()
