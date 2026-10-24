"""P10's second (final) reply, fitted on the three real R2 points, and a sweep of (R1, R2) asks.

Facts (practice #2, #3, #5; R1 counter always 31.70 at 54 d, final at reply 2, 0.10 price grid):
  our R2 step backwards -> its move 0.00 (31.70); +0.48 (29.30 -> 29.78) -> 0.10 (31.60);
  +2.00 (29.30 -> 31.30) -> 0.20 (31.50, "in response to your movement").
Candidate rules for its move m (its final = round(31.70 - m) on the grid, or our ask if that is >= its new
price: "agreed"), each with the parameter range that fits all three points:
  prop      m = k x step                              k in [0.104, 0.125)
  rel       m = a x step / (31.70 - R1)               a in [0.25, 0.30)
  halfcap   m = min(k x step, (31.70 - R2) / 2)       k in [0.104, 0.31)
  floor     prop, but never below a floor in (31.30, 31.50]; an ask >= the floor is agreed
Weights: prop 0.3, rel 0.2, halfcap 0.3, floor 0.2. Rounding: half up (conservative).

    python experiments/capacity/p10_r2fit.py
"""

import math

C_OPEN, C_BEST, PER_EUR, FIXED = 1932492.18, 1328926.89, 47112.0, 34135.2  # C = PER_EUR x price + FIXED at 54 d
P1 = 31.70
FACTS = [(29.30, 29.78, 31.60), (29.30, 31.30, 31.50)]  # (R1, R2, its final)


def score(price):
    return (C_OPEN - (PER_EUR * price + FIXED)) / (C_OPEN - C_BEST)


def grid(x):
    return math.floor(x * 10 + 0.5 + 1e-9) / 10


def final(rule, par, r1, r2):
    step = r2 - r1
    if step <= 0:
        return P1
    if rule == "prop":
        m = par * step
    elif rule == "rel":
        m = par * step / (P1 - r1)
    elif rule == "halfcap":
        m = min(par[0] * step, (P1 - r2) / 2)
    else:  # floor
        k, fl = par
        if r2 >= fl:
            return r2  # agreed at our ask
        return max(fl, grid(P1 - k * step))
    v = P1 - m
    return r2 if r2 >= v - 1e-9 else grid(v)


def worlds(n=24):
    def span(lo, hi):
        return [lo + (hi - lo) * (i + 0.5) / n for i in range(n)]

    out = [("prop", k, 0.3 / n) for k in span(0.104, 0.125)]
    out += [("rel", a, 0.2 / n) for a in span(0.25, 0.30)]
    out += [("halfcap", (k,), 0.3 / n) for k in span(0.104, 0.31)]
    floors = [31.35, 31.40, 31.45, 31.50]
    out += [("floor", (k, f), 0.2 / n / len(floors)) for k in span(0.104, 0.125) for f in floors]
    return out


def check_fit():
    for rule, par, _ in worlds():
        for r1, r2, want in FACTS:
            got = final(rule, par, r1, r2)
            assert abs(got - want) < 1e-6, (rule, par, r1, r2, got, want)


def main():
    check_fit()
    ws = worlds()
    rows = []
    for r1 in (29.30, 28.34):
        for r2 in (31.00, 31.10, 31.20, 31.25, 31.30, 31.34, 31.40, 31.45):
            res = [(final(rule, par, r1, r2), w) for rule, par, w in ws]
            mean = sum(score(p) * w for p, w in res)
            beat = sum(w for p, w in res if p <= 31.34 + 1e-9)
            tie = sum(w for p, w in res if abs(p - 31.40) < 1e-6)
            worst = max(p for p, _ in res)
            by = {}
            for (rule, _, w), (p, _) in zip(ws, res, strict=True):
                by.setdefault(rule, {}).setdefault(p, 0)
                by[rule][p] += w
            rows.append((mean, r1, r2, beat, tie, worst, by))
    for mean, r1, r2, beat, tie, worst, by in sorted(rows, reverse=True):
        dist = "; ".join(f"{r} " + ",".join(f"{p:.2f}" for p in sorted(d)) for r, d in by.items())
        print(
            f"R1 {r1:.2f} R2 {r2:.2f}: mean {mean:.4f}  P(<=31.34, beats) {beat:.2f}  P(31.40 tie) {tie:.2f}  "
            f"worst {worst:.2f} ({score(worst):.3f})  | {dist}"
        )


if __name__ == "__main__":
    main()
