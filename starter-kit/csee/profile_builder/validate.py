"""Field-by-field agreement of the deterministic hard fields with the curated profiles."""

from collections import defaultdict

from . import facts
from .common import PROFILES, curated, detailed_suppliers


def _num(tol):
    def eq(a, b):
        if a is None or b is None:
            return a is None and b is None
        try:
            return abs(float(a) - float(b)) <= tol
        except (TypeError, ValueError):
            return a == b

    return eq


def _exact(a, b):
    return (a or None) == (b or None) if not isinstance(a, (int, float)) else a == b


def _skonto(a, b):
    """Curated free text vs '2% within 10 days': agree when both are empty or name the same numbers."""
    if not a or not b:
        return not a and not b
    import re

    return re.findall(r"\d+", a)[:2] == re.findall(r"\d+", b)[:2]


def _share(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(0.06, 0.02 * abs(b))


def _set(a, b):
    return sorted(a or []) == sorted(b or [])


def _clauses(a, b):
    def key(c):
        return (
            c.get("id"),
            c.get("series"),
            float(c.get("material_share") or 0),
            float(c.get("deadband_pct") or 0),
        )

    return sorted(map(key, a or [])) == sorted(map(key, b or []))


FIELDS = [  # (label, getter path, comparator)
    ("name", ("name",), _exact),
    ("category", ("category",), _exact),
    ("country", ("country",), _exact),
    ("owner_type", ("owner_type",), _exact),
    ("group_parent", ("group_parent",), _exact),
    ("staff", ("staff",), _exact),
    ("turnover_eur", ("turnover_eur",), _exact),
    ("our_spend_fy2026_eur", ("our_spend_fy2026_eur",), _num(1.0)),
    ("our_share_of_their_turnover_pct", ("our_share_of_their_turnover_pct",), _share),
    ("contract.id", ("contract", "id"), _exact),
    ("contract.valid_to", ("contract", "valid_to"), _exact),
    ("contract.payment_days", ("contract", "payment_days"), _exact),
    ("contract.incoterm", ("contract", "incoterm"), _exact),
    ("contract.notice_days", ("contract", "notice_days"), _exact),
    ("contract.index_clauses", ("contract", "index_clauses"), _clauses),
    ("standard_terms.payment_days", ("standard_terms_hint", "payment_days"), _exact),
    ("standard_terms.incoterm", ("standard_terms_hint", "incoterm"), _exact),
    ("standard_terms.lead_time_days", ("standard_terms_hint", "lead_time_days"), _exact),
    ("standard_terms.skonto", ("standard_terms_hint", "skonto"), _skonto),
    ("quality.latest_scorecard_id", ("quality", "latest_scorecard_id"), _exact),
    ("quality.otd_pct", ("quality", "otd_pct"), _num(0.05)),
    ("quality.ppm", ("quality", "ppm"), _exact),
    ("quality.colour", ("quality", "colour"), _exact),
    ("quality.open_8d_overdue", ("quality", "open_8d_overdue"), _exact),
    ("payment.avg_days_late_by_us", ("payment_behaviour", "avg_days_late_by_us"), _num(0.15)),
    ("financial.equity_ratio_pct", ("financial_health", "equity_ratio_pct"), _num(0.05)),
    ("financial.credit_index", ("financial_health", "credit_index"), _exact),
    ("financial.credit_index_12m_ago", ("financial_health", "credit_index_12m_ago"), _exact),
    ("history.events", ("negotiation_history", "events"), _exact),
    ("history.avg_asked_pct", ("negotiation_history", "avg_asked_pct"), _num(0.015)),
    ("history.avg_settled_pct", ("negotiation_history", "avg_settled_pct"), _num(0.015)),
    ("history.settle_to_ask_ratio", ("negotiation_history", "settle_to_ask_ratio"), _num(0.015)),
]
# The curated profiles were written by two hands with two conventions for these fields. Strict = our
# primary value; convention-aware = also accept the documented alternative (key in the same dict).
ALTERNATIVES = {
    "payment.avg_days_late_by_us": ("payment_behaviour", "avg_days_late_last_12m"),
    "history.events": ("negotiation_history", "events_total"),
}
PART_FIELDS = [
    ("current_price", _num(0.005)),
    ("price_unit", _exact),
    ("quota_pct", _exact),
    ("qualified_alternatives", _set),
    ("should_cost_id", _exact),
    ("should_cost_unit", _num(0.005)),
]


def _get(d, path):
    for k in path:
        d = (d or {}).get(k)
    return d


def compare(built, cur):
    """[(field, ok, ours, theirs)] for one supplier."""
    out = []
    for label, p, cmp in FIELDS:
        ok = cmp(_get(built, p), _get(cur, p))
        if not ok and label in ALTERNATIVES and cmp(_get(built, ALTERNATIVES[label]), _get(cur, p)):
            ok = "alt"
        out.append((label, ok, _get(built, p), _get(cur, p)))
    ours = {p["part_id"]: p for p in built.get("parts", [])}
    theirs = {p["part_id"]: p for p in cur.get("parts", [])}
    out.append(("parts.set", set(ours) == set(theirs), sorted(ours), sorted(theirs)))
    for pid in sorted(set(ours) & set(theirs)):
        for f, cmp in PART_FIELDS:
            out.append(
                (
                    f"parts.{f}",
                    cmp(ours[pid].get(f), theirs[pid].get(f)),
                    f"{pid}={ours[pid].get(f)}",
                    theirs[pid].get(f),
                )
            )
    return out


def run(pkg, suppliers=None, profiles=PROFILES, verbose=True):
    suppliers = suppliers or detailed_suppliers(pkg)
    per_field = defaultdict(lambda: [0, 0, 0])  # strict ok, convention-aware ok, compared
    misses = []
    n = 0
    for s in suppliers:
        cur = curated(s, profiles)
        if not cur:
            continue
        n += 1
        for field, ok, ours, theirs in compare(facts.build(pkg, s), cur):
            per_field[field][0] += ok is True
            per_field[field][1] += bool(ok)
            per_field[field][2] += 1
            if not ok:
                misses.append((s, field, ours, theirs))
    total_ok = sum(v[0] for v in per_field.values())
    total_alt = sum(v[1] for v in per_field.values())
    total = sum(v[2] for v in per_field.values())
    lines = [f"# Hard-field agreement vs curated profiles ({n} suppliers)", ""]
    lines.append(f"**Strict: {total_ok}/{total} field comparisons agree ({100 * total_ok / max(total, 1):.1f} %)**  ")
    lines.append(
        f"**Convention-aware: {total_alt}/{total} ({100 * total_alt / max(total, 1):.1f} %)** "
        f"(accepts {', '.join(f'`{k}` = `{v[1]}`' for k, v in ALTERNATIVES.items())})"
    )
    lines += ["", "| field | strict | conv.-aware | of |", "|---|---:|---:|---:|"]
    for field, (ok, alt, of) in per_field.items():
        lines.append(f"| {field} | {ok} | {alt} | {of} |")
    lines += ["", "## Disagreements (ours vs curated)", ""]
    for s, field, ours, theirs in misses:
        lines.append(f"- {s} `{field}`: ours `{ours}` vs curated `{theirs}`")
    report = "\n".join(lines) + "\n"
    if verbose:
        print(report)
    return {
        "suppliers": n,
        "agree": total_ok,
        "agree_alt": total_alt,
        "total": total,
        "per_field": dict(per_field),
        "misses": misses,
        "report": report,
    }
