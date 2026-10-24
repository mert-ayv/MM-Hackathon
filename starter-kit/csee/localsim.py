"""A free, in-process supplier simulator over the practice case files: no network, no quota.

Tacto: "build your own supplier simulator from the public data". Our suppliers behave as the hosted
ones did in our replays and back offices: a cost floor (should-cost, country factor, noise), an
opening ask, concessions of about half the gap per round capped by an approval band, positions held
on terms they care about (payment days for the cash-short, an index clause on long contracts), an
alternative sheet now and then, a final offer near the floor - and a walk if pushed past it.

It is a proxy for direction and robustness, not the truth: promote a variant only after a practice
run. `LocalTable` speaks the same interface as `arena_kit.play.RemoteTable`, so `play_case` runs on it.
"""

import json
import math
import random
from pathlib import Path

from arena_kit.cost import closing_terms, complete_offer, must_haves_ok, score, total_cost

from . import intel as intel_mod
from . import levers

CASES = Path(__file__).parent / "cases" / "practice.json"
OPEN_ASK = {
    "price_increase": 0.08,
    "renewal": 0.04,
    "raw_material": 0.06,
    "capacity": 0.07,
    "quality": 0.02,
    "bundling": 0.03,
    "rfq": 0.06,
}


class Supplier:
    def __init__(self, case, sid, pkg, rng):
        self.case, self.sid, self.rng = case, sid, rng
        b = case["buyer"]
        profile = intel_mod.load_profile(sid)
        pressures = " ".join(p.get("type", "") for p in profile.get("pressures", []))
        self.cash_short = "cash" in pressures
        self.rate = 0.15 if self.cash_short else 0.08
        row = (pkg.query("SELECT * FROM suppliers WHERE id = ?", (sid,)) or [{}])[0] if pkg else {}
        country = row.get("country") or "DE"
        base = b.get("current_unit_price") or b["fallback_unit_price"]
        full, _ = intel_mod.estimate_full_cost(case, pkg, sid, country)
        self.full = (full or base / 1.1) * rng.uniform(0.95, 1.05)
        self.min_margin = rng.uniform(0.02, 0.05)
        ask = OPEN_ASK.get(case.get("type"), 0.05) + rng.uniform(-0.02, 0.03)
        self.p0 = round(max(base * (1 + ask), self.full * (1 + self.min_margin) * 1.04), 2)
        self.std = {
            "payment_days": row.get("payment_days") or 30,
            "incoterm": row.get("incoterm") or "FCA",
            "lead_time_days": row.get("standard_lead_time_days") or b["need_lead_time_days"],
            "contract_months": 12,
            "volume_per_year": b["need_per_year"],
            "ppm_commitment": 1000,
            "chargeback_eur_per_complaint": 0,
            "tooling_eur": 0,
            "index_clause": None,
        }
        opts = case.get("term_options", {})
        self.want_clause = bool(opts.get("index_clause")) and rng.random() < 0.6
        self.hold_payment = self.cash_short or rng.random() < 0.3
        self.band = 0.02 * self.p0  # a bigger step needs the boss
        owner = (profile.get("owner_type") or "").lower()
        # owner-led shops close much of the gap (D02's owner); family firms and groups give a fixed step (D01)
        self.gap_closer = owner in ("founder", "private") or (profile.get("staff") or 999) < 80
        self.patience = rng.randint(5, 7)
        self.prev_buyer = None
        self.ask_value = self.value({"unit_price": self.p0})
        self.floor = self.full * (1 + self.min_margin)
        self.final, self.round, self.n = False, 0, 0

    def terms(self, t):
        return closing_terms(self.case, t, self.std)

    def value(self, t):
        """What the sheet is worth to the supplier per unit, in price terms (cash, at its own rate)."""
        t = self.terms(t)
        b = self.case["buyer"]
        v = t["unit_price"] * (1 - self.rate * (t["payment_days"] - self.std["payment_days"]) / 360)
        fr = b["freight_eur_per_unit"]
        v -= fr.get(t["incoterm"], 0) - fr.get(self.std["incoterm"], 0)  # it pays the freight leg
        v -= max(0, self.std["lead_time_days"] - t["lead_time_days"]) * 0.002 * t["unit_price"]
        v -= max(0, self.std["ppm_commitment"] - (t.get("ppm_commitment") or 0)) / 1e6 * 200
        v -= (t.get("chargeback_eur_per_complaint") or 0) * 0.0005
        if t.get("index_clause") and self.want_clause:
            v += 0.01 * t["unit_price"]
        if t.get("effective_date") and b.get("current_unit_price"):
            months_late = max(0, (int(t["effective_date"][:4]) - 2026) * 12 + int(t["effective_date"][5:7]) - 11)
            v -= (t["unit_price"] - b["current_unit_price"]) * min(months_late, 12) / 12
        return v

    def price_for_value(self, t, target):
        lo, hi = 0.0, self.p0 * 3
        for _ in range(50):
            mid = (lo + hi) / 2
            if self.value({**t, "unit_price": mid}) < target:
                lo = mid
            else:
                hi = mid
        return round(hi, 2)

    def opening(self):
        sheet = {"unit_price": self.p0}
        if "effective_date" in self.case["negotiable"]:
            sheet["effective_date"] = (self.case["term_options"].get("effective_date") or [None])[0]
        return self.reply_msg("open", [sheet], "Our quote.")

    def respond(self, msg):
        self.n += 1
        sheets = [s.get("terms", s) for s in msg.get("term_sheets") or []]
        if not sheets:
            return self.reply_msg("final_offer" if self.final else "open", [self.standing], "Please make an offer.")
        verified = [c for c in (msg.get("refs") or [])]
        if verified and self.n <= 3:
            self.ask_value -= 0.004 * self.p0 * min(len(verified), 2)  # "we did not know that - a fair point"
        best = max(sheets, key=self.value)
        # patience: an offer far below its cost, or a buyer who barely moves, ends the haggling sooner
        bv = self.value(best)
        if bv < self.floor * 0.93:
            self.patience -= 1
        if self.prev_buyer is not None and self.n > 1:
            their_last = getattr(self, "last_step", 0) or 0.01 * self.p0
            if bv - self.prev_buyer < 0.25 * their_last:
                self.patience -= 1
        self.prev_buyer = bv
        if self.hold_payment and "payment_days" in best and best["payment_days"] > self.std["payment_days"]:
            best = {**best, "payment_days": self.std["payment_days"]}
        if self.want_clause and "index_clause" in self.case["negotiable"] and best.get("index_clause") is None:
            clauses = [c for c in self.case["term_options"].get("index_clause", []) if c]
            best = {**best, "index_clause": clauses[0] if clauses else None}
        if self.value(best) >= self.ask_value - 1e-9 and best in sheets:
            return self.reply_msg("agreed", [best], "We agree.")
        if self.final:  # replays: 0 walk-aways in ~350 supplier messages - it repeats its final offer
            return self.reply_msg("final_offer", [self.standing], "Our final offer stands.")
        gap = self.ask_value - self.value(best)
        step = min(0.6 * gap, self.band) if self.gap_closer else min(0.01 * self.p0, gap)
        before = self.ask_value
        self.ask_value = max(self.floor, self.ask_value - max(step, 0))
        self.last_step = before - self.ask_value
        if self.ask_value <= self.floor * 1.003 or self.n >= self.patience:
            self.final = True
        counter = {**best, "unit_price": self.price_for_value(best, self.ask_value)}
        out = [counter]
        if "payment_days" in self.case["negotiable"] and counter.get("payment_days", 99) > self.std["payment_days"]:
            alt = {**counter, "payment_days": self.std["payment_days"]}
            alt["unit_price"] = self.price_for_value(alt, self.ask_value - 0.003 * self.p0)
            out.append(alt)
        return self.reply_msg("final_offer" if self.final else "open", out, "Our counter-offer.")

    def reply_msg(self, status, sheets, body):
        self.round += 1
        full = [complete_offer(self.case, {**self.std_for_sheet(), **s}) for s in sheets]
        ids = [f"offer:{self.sid}-{self.round}" + ("" if i == 0 else f"-{chr(96 + i)}") for i in range(len(full))]
        if full:
            self.standing, self.standing_id = full[0], ids[0]
            self.offered = dict(zip(ids, full, strict=True))
        return {
            "from": f"sales@{self.sid}",
            "status": status,
            "body": body,
            "term_sheets": [{"term_sheet_id": i, "terms": t} for i, t in zip(ids, full, strict=True)],
            "attachments": [],
            "claim_results": [],
        }

    def std_for_sheet(self):
        return {k: v for k, v in self.std.items() if k in self.case["negotiable"]}

    def best_cost(self):
        """C_best for this supplier: our best terms at the price that just meets its floor."""
        t = levers.best_terms(self.case, {"unit_price": self.floor}, self.std)
        for _ in range(2):
            t["unit_price"] = self.price_for_value(t, self.floor)
            t = levers.best_terms(self.case, t, self.std)
        t["unit_price"] = self.price_for_value(t, self.floor)
        return total_cost(self.case, t, self.std) if must_haves_ok(self.case, t, self.std) else math.inf


class LocalTable:
    """`RemoteTable`'s interface over local suppliers: open, send, close, attachment, missed, result."""

    def __init__(self, case, pkg, seed=0):
        self.case, self.session_id, self.done = case, f"local-{case['case_id']}-{seed}", None
        rng = random.Random(f"{case['case_id']}-{seed}")
        self.sup = {s: Supplier(case, s, pkg, rng) for s in case["suppliers"]}
        self.result_ = None

    def open(self, case_id):
        self.threads = {s: [sp.opening()] for s, sp in self.sup.items()}
        self.c_open = min(
            total_cost(self.case, self.threads[s][0]["term_sheets"][0]["terms"], sp.std) for s, sp in self.sup.items()
        )
        return self.case, json.loads(json.dumps(self.threads))

    def send(self, supplier_id, message):
        return self.sup[supplier_id].respond(message)

    def close(self, supplier_id, message):
        b = self.case["buyer"]
        c_alt = levers.alternative_cost(self.case)
        c_best = min([c_alt] + [sp.best_cost() for sp in self.sup.values()])
        act = message["action"]
        if act["type"] == "accept":
            sp = self.sup[supplier_id]
            terms = sp.offered.get(act["term_sheet_id"])
            if terms is None:
                return {"deal": False, "error": "unknown term sheet"}
            c = total_cost(self.case, terms, sp.std)
            ok = must_haves_ok(self.case, terms, sp.std)
            s = score(self.c_open, c, c_best) if ok and c <= self.c_open else 0.0
            self.result_ = {
                "deal": True,
                "supplier_id": supplier_id,
                "terms": terms,
                "c_open": self.c_open,
                "c_deal": c,
                "c_best": c_best,
                "score": s,
            }
        else:
            s = score(self.c_open, c_alt, c_best) if c_alt < math.inf else 0.0
            self.result_ = {
                "deal": False,
                "c_open": self.c_open,
                "c_deal": None,
                "c_alt": c_alt,
                "c_best": c_best,
                "score": s if b.get("alternative") else 0.0,
            }
        return self.result_

    def attachment(self, attachment_id):
        return b""

    def missed(self, supplier_id, error):
        return {"from": "arena", "status": "walked_away", "term_sheets": [], "attachments": []}

    def result(self):
        return self.result_ or {"deal": False, "score": 0.0}


def cases():
    return json.loads(CASES.read_text())
