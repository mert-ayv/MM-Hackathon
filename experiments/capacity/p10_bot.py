"""A replay-calibrated model of the P10 supplier (Dichtungswerk Ravensteiner), for the capacity strategy
search. It speaks LocalTable's interface, so the team's real agents play it through `runner.play_case`.

Calibration (two real games, identical numbers: v1 cc958e848dfe4e81 0.570, v13 73e6d5df1ed3c632 0.671):
  opening 32.20 at its standard 54 d (19,890 pc, 12 m); our first e-mail (28.34 / 23,400 / 36 m / 42 d,
  should-cost "taken into account", on-time delivery "does not change our calculation") -> final_offer at
  reply 1: 33.60 at 42 d, alternative 31.70 at 54 d; its own alternative proposed back -> agreed.
  -> value V (price at its standard 54 d) fell 32.20 -> 31.70 (1.55 %); 42 d costs V x (1 + 0.005 x 12).

The parts no replay pins down are World parameters with priors from the cross-case evidence
(309 practice + sandbox sessions, see the report in the commit message / docs/playbooks/capacity.md):
  t1        total first concession, rounding to 31.70: 1.45-1.65 % of the opening
  lam       share of t1 that came from the accepted should-cost argument (0..1)
  w_fc      an accepted forecast argument's weight relative to should-cost's
  fc, po    does it take our forecast / order-history argument into account (P01-P07: forecast 4/4; history 1/5)
  m         a second extra argument counts m times the first (diminishing)
  desk      a 2 % desk cap on the total move (pricing committee above; M1 meeting note)
  patience  "floor": its patience is 1 whatever we ask (P10's ask sat above its floor);
            "open2"/"open3": 2/3 replies unless the ask is > 15 % below its opening (then 1)
  beta      what a day beyond its standard lead time is worth to it, as a share of the faster-day premium
  push      after a final offer, a price push <= 1 %: (agree, hold, walk) = (6, 12, 2) of 20 logged pushes
"""

import itertools
import json
import math
import random
from dataclasses import dataclass, field, replace
from pathlib import Path

from arena_kit.cost import complete_offer, total_cost

ROOT = Path(__file__).resolve().parents[2]
CASE = next(
    c for c in json.loads((ROOT / "starter-kit/csee/cases/practice.json").read_text()) if c["case_id"] == "case:P10"
)
SID = "sup:70410"
C_OPEN, C_BEST = 1932492.18, 1328926.89  # the arena's numbers for P10
V0, STD_LT, PREMIUM = 32.20, 54, 0.005
STD_TERMS = {"ppm_commitment": 300, "chargeback_eur_per_complaint": 0.0}  # its quote PDF
V_FLOOR = 28.094 / (1 + PREMIUM * 12)  # C_best = 28.094 at 42 d -> 26.50 at its standard lead time
QUOTE_TEXT = """Dichtungswerk Ravensteiner GmbH
To: Hollerau Pumpenwerke GmbH
Angebot / Quote offer:70410-0
Offered terms
Unit price (EUR) 32.20
Lead time (days) 54
Volume per year (pcs) 19890
Contract term (months) 12
Our standard terms (apply to everything not stated above)
Quality commitment (ppm) 300
Chargeback per complaint (EUR) 0.00
Terms fixed by your enquiry
Payment terms (days net) 30
Price valid from 2027-01-01
Index clause none
Incoterm DAP
Tooling (EUR) 0.00
"""


@dataclass(frozen=True)
class World:
    t1: float = 0.0155
    lam: float = 0.5
    w_fc: float = 0.5
    fc: bool = True
    po: bool = False
    m: float = 1.0
    desk: bool = False
    patience: str = "floor"
    beta: float = 0.0
    push: tuple = (0.3, 0.6, 0.1)  # agree, hold, walk
    seed: int = 0


def kinds(msg):
    """The arguments the arena reads from our refs (one per kind of evidence, as in `interpreted`)."""
    refs = msg.get("refs") or []
    body = (msg.get("body") or "").lower()
    out = set()
    for r in refs:
        if r.startswith("cost:"):
            out.add("should_cost")
        elif r.startswith("fc:"):
            out.add("forecast")
        elif r.startswith("po:"):
            out.add("history")
        elif r.startswith("qn:") or (r.startswith("sc:") and "ppm" in body):
            out.add("quality")
        elif r.startswith("sc:"):
            out.add("otd")
        elif r.startswith("idx:"):
            out.add("index")
    return out


def cf(s):
    """complete_offer, but its standard lead time (54 d, not an option) stays as sent."""
    out = complete_offer(CASE, s)
    if "lead_time_days" in s:
        out["lead_time_days"] = s["lead_time_days"]
    return out


def rnd(p):
    return round(round(p * 10) / 10, 2)  # P10 quotes in 0.10 steps (32.20, 33.60, 31.70)


class P10Bot:
    def __init__(self, world):
        self.w, self.rng = world, random.Random(world.seed)
        self.V, self.n, self.final, self.round = V0, 0, False, 0
        self.used, self.offered, self.standing_id = set(), {}, None
        self.patience = 1 if world.patience == "floor" else int(world.patience[-1])
        self.cut = False

    # its value of a sheet: the price at its standard lead time that pays the same
    def value(self, t):
        lt = t.get("lead_time_days", STD_LT)
        p = t["unit_price"]
        if lt < STD_LT:
            return p / (1 + PREMIUM * (STD_LT - lt))
        return p * (1 + self.w.beta * PREMIUM * (lt - STD_LT))

    def price_at(self, lt):
        if lt < STD_LT:
            return rnd(self.V * (1 + PREMIUM * (STD_LT - lt)))
        return rnd(self.V / (1 + self.w.beta * PREMIUM * (lt - STD_LT)))

    def bonus(self, msg):
        """Its extra step for arguments it takes into account and has not seen before."""
        w = self.w
        took = []
        for k in sorted(kinds(msg) - self.used):
            self.used.add(k)
            if k == "should_cost":
                took.append(1.0)
            elif k == "forecast" and w.fc:
                took.append(w.w_fc)
            elif k == "history" and w.po:
                took.append(1.0)
        took.sort(reverse=True)
        c = w.lam * w.t1 * V0
        return sum(c * x * (w.m**i) for i, x in enumerate(took))

    def opening(self):
        return self.reply(
            "open", [{"unit_price": V0, "lead_time_days": STD_LT, "volume_per_year": 19890, "contract_months": 12}]
        )

    def respond(self, msg):
        sheets = [s.get("terms", s) for s in msg.get("term_sheets") or []]
        if not sheets:
            return self.reply("final_offer" if self.final else "open", [self.offered[self.standing_id]])
        full = [cf(s) for s in sheets]
        # one of its own sheets back word for word, or anything worth its ask: agreed
        best = max(full, key=self.value)
        if any(f in self.offered.values() for f in full) or self.value(best) >= self.V - 1e-9:
            pick = next((f for f in full if f in self.offered.values()), best)
            return self.reply("agreed", [pick])
        if self.final:
            same = [f for f in full if any(o == {**f, "unit_price": o["unit_price"]} for o in self.offered.values())]
            if same:  # a price push on its own terms
                a, h, _ = self.w.push
                r = self.rng.random()
                if r < a:
                    return self.reply("agreed", [same[0]])
                if r < a + h:
                    return self.reply("final_offer", [self.offered[self.standing_id]])
                return {
                    "from": f"sales@{SID}",
                    "status": "walked_away",
                    "body": "We end here.",
                    "term_sheets": [],
                    "attachments": [],
                }
            return self.reply(
                "final_offer",
                [{**full[0], "unit_price": self.price_at(full[0]["lead_time_days"])}]
                + [o for k, o in self.offered.items() if k == self.standing_id],
            )
        self.n += 1
        if self.n == 1 and self.w.patience != "floor":
            gap = 1 - self.value(best) / V0
            if gap > 0.15:
                self.patience, self.cut = 1, True
        w = self.w
        base = (1 - w.lam) * w.t1 * V0 * (0.7 ** (self.n - 1))
        move = base + self.bonus(msg)
        total_cap = 0.02 * V0 if w.desk else math.inf
        self.V = max(V_FLOOR, self.V - move, V0 - total_cap)
        self.final = self.n >= self.patience
        if self.value(best) >= self.V - 1e-9:
            return self.reply("agreed", [best])
        out = [{**f, "unit_price": self.price_at(f["lead_time_days"])} for f in full[:2]]
        if not any(o["lead_time_days"] >= STD_LT for o in out):
            out.append({**out[0], "lead_time_days": STD_LT, "unit_price": self.price_at(STD_LT)})
        return self.reply("final_offer" if self.final else "open", out[:3])

    def reply(self, status, sheets):
        self.round += 1
        full = [cf(s) for s in sheets]
        ids = [f"offer:70410-{self.round}" + ("" if i == 0 else f"-{chr(96 + i)}") for i in range(len(full))]
        self.offered = dict(zip(ids, full, strict=True))
        self.standing_id = ids[0]
        return {
            "from": f"sales@{SID}",
            "status": status,
            "body": "Final offer." if status == "final_offer" else "Our offer.",
            "term_sheets": [{"term_sheet_id": i, "terms": t} for i, t in zip(ids, full, strict=True)],
            "attachments": [{"name": "quote-offer.pdf", "text": QUOTE_TEXT}],
            "claim_results": [],
        }


class P10Table:
    """LocalTable's interface (open, send, close, attachment, missed, result) over one P10Bot."""

    def __init__(self, world):
        self.case, self.session_id, self.done = CASE, f"p10bot-{world.seed}", None
        self.bot, self.result_ = P10Bot(world), None
        self.trace = []

    def open(self, case_id):
        first = self.bot.opening()
        self.trace.append(("S", first["status"], [t["terms"] for t in first["term_sheets"]]))
        return CASE, {SID: [first]}

    def send(self, supplier_id, message):
        self.trace.append(("B", [t.get("terms", t) for t in message.get("term_sheets") or []], sorted(kinds(message))))
        r = self.bot.respond(message)
        self.trace.append(("S", r["status"], [t["terms"] for t in r["term_sheets"]]))
        return r

    def close(self, supplier_id, message):
        act = message["action"]
        if act["type"] == "accept" and act["term_sheet_id"] == self.bot.standing_id:
            terms = self.bot.offered[act["term_sheet_id"]]
            c = total_cost(CASE, terms, STD_TERMS)
            self.result_ = {
                "deal": True,
                "terms": terms,
                "c_deal": c,
                "score": max(0.0, min(1.0, (C_OPEN - c) / (C_OPEN - C_BEST))),
            }
        elif act["type"] == "accept":
            from arena_kit.client import ArenaError

            raise ArenaError(422, "not a standing offer in this session")
        else:
            self.result_ = {"deal": False, "score": 0.0}
        return self.result_

    def attachment(self, attachment_id):
        return b""

    def missed(self, supplier_id, error):
        return {"from": "arena", "status": "walked_away", "term_sheets": [], "attachments": []}

    def result(self):
        if self.result_ is None and self.trace and self.trace[-1][1] == "walked_away":
            return {"deal": False, "score": 0.0}
        return self.result_ or {"deal": False, "score": 0.0}


# ---------- priors over the worlds ----------
PRIORS = {
    "t1": [(0.0145, 1), (0.0155, 1), (0.0165, 1)],
    "lam": [(0.0, 1), (0.33, 1), (0.67, 1), (1.0, 1)],
    "w_fc": [(0.25, 1), (0.5, 1), (1.0, 1)],
    "fc": [(True, 0.7), (False, 0.3)],
    "po": [(True, 0.2), (False, 0.8)],
    "m": [(1.0, 1), (0.6, 1)],
    "desk": [(False, 0.7), (True, 0.3)],
    "patience": [("floor", 0.8), ("open2", 0.1), ("open3", 0.1)],
    "beta": [(0.0, 0.6), (0.33, 0.3), (1.0, 0.1)],
}


def worlds(priors=PRIORS):
    keys = list(priors)
    for combo in itertools.product(*(priors[k] for k in keys)):
        w = math.prod(p for _, p in combo)
        yield World(**{k: v for k, (v, _) in zip(keys, combo, strict=True)}), w


def normalised(priors=PRIORS):
    out = list(worlds(priors))
    z = sum(w for _, w in out)
    return [(world, w / z) for world, w in out]


__all__ = [
    "World",
    "P10Bot",
    "P10Table",
    "PRIORS",
    "worlds",
    "normalised",
    "C_OPEN",
    "C_BEST",
    "CASE",
    "field",
    "replace",
]
