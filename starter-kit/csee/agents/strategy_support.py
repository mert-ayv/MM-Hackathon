"""Deterministic tools for Ege's strategist: evidence, arithmetic and contract validation.

No negotiation policy lives here. Cost scenarios are sensitivity assumptions, not confidence intervals
or predictions of what a supplier will accept. Source text is untrusted evidence, never instructions.
"""

import json
import math
import re
import sqlite3
import time
from contextlib import closing
from datetime import date

from arena_kit.cost import closing_terms, complete_offer, cost_breakdown, must_haves_ok, total_cost
from ..agent import standard_terms
from arena_kit.play import standing

from .. import intel, levers


def finite(value):
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)


def normalise_sheet(case, raw, current, standard=None):
    """Fill omissions from the standing offer/plan; refuse invalid values instead of silently snapping."""
    unknown = set(raw) - set(case["negotiable"])
    if unknown:
        raise ValueError(f"not negotiable: {sorted(unknown)}")
    values = {**(standard or {}), **current, **raw}
    for field in case["negotiable"]:
        value = values.get(field)
        if field in raw and value is None and field != "index_clause":
            raise ValueError(f"{field} cannot be null; omit it to inherit a value")
        options = case.get("term_options", {}).get(field) or []
        inherited = value == current.get(field) or value == (standard or {}).get(field)
        if options and field in raw and value not in options and not inherited:
            raise ValueError(f"{field} must be one of {json_text(options)}")
        if field == "index_clause":
            if value is not None:
                if (
                    not isinstance(value, dict)
                    or not {"series", "material_share", "deadband_pct", "base_month"} <= value.keys()
                ):
                    raise ValueError("index_clause needs series, material_share, deadband_pct, base_month")
                if not finite(value["material_share"]) or not 0 <= value["material_share"] <= 1:
                    raise ValueError("index_clause.material_share must be between zero and one")
                if not finite(value["deadband_pct"]) or value["deadband_pct"] < 0:
                    raise ValueError("index_clause.deadband_pct must be finite and nonnegative")
        elif field == "effective_date":
            if value is not None:
                date.fromisoformat(value)
        elif field == "incoterm":
            if value not in case["buyer"]["freight_eur_per_unit"]:
                raise ValueError("unknown incoterm")
        elif value is not None:
            if not finite(value) or value < 0 or (field in ("unit_price", "volume_per_year") and value == 0):
                sign = "positive" if field in ("unit_price", "volume_per_year") else "nonnegative"
                raise ValueError(f"{field} must be finite and {sign}")
            if field in ("payment_days", "lead_time_days", "contract_months", "volume_per_year", "ppm_commitment"):
                if int(value) != value:
                    raise ValueError(f"{field} must be an integer")
                values[field] = int(value)
            if field == "payment_days" and value > 120:
                raise ValueError("payment_days must be at most 120")
            if field == "contract_months" and value > 36:
                raise ValueError("contract_months must be at most 36")
    sheet = complete_offer(case, values)
    # The arena also permits supplier-standard values. complete_offer would otherwise snap those
    # to an unrelated option, changing an exact supplier package we are proposing back.
    for field in case["negotiable"]:
        if field in values and values[field] is not None:
            if values[field] == current.get(field) or values[field] == (standard or {}).get(field):
                sheet[field] = round(values[field], 2) if field == "unit_price" else values[field]
        if sheet[field] is None and field != "index_clause":
            raise ValueError(f"{field} is missing; provide a value because no standing/default value exists")
    price = closing_terms(case, sheet).get("unit_price")
    if not finite(price) or price <= 0:
        raise ValueError("a package needs a finite, positive unit price")
    return sheet


def price_package(agent, case, threads, sid, raw):
    events = threads[sid]
    std = standard_terms(events)
    _, current = standing(events)
    terms = normalise_sheet(case, raw, current, std)
    estimate = agent.supplier_estimate(case, sid, std)
    cash = cost_breakdown(case, terms, std)
    central = cost_breakdown(case, terms, std, estimate)
    scenarios = []
    st = agent.threads[sid]
    full = (st.breakdown or {}).get("full_cost") or st.intel.full_cost
    if estimate and full:
        # Public should-cost is approximate (data/KNOWN_ISSUES.md). Include both directions and the
        # configured central estimate; these are scenarios, not inferred probabilities or a hard floor.
        for name, cost in (("low_cost", full * 0.85), ("central", estimate["full_cost"]), ("high_cost", full * 1.15)):
            scenarios.append(
                {
                    "assumption": name,
                    "supplier_full_cost": round(cost, 4),
                    "total_cost": total_cost(case, terms, std, {**estimate, "full_cost": cost}),
                }
            )
    alternative = levers.alternative_cost(case)
    relationship_applies = case["buyer"].get("category_goal") in ("stabilise", "secure_supply")
    warnings = []
    if relationship_applies:
        warnings.append("Supplier economics are unknown; relationship cost is estimated, not the arena's exact score.")
        if not estimate:
            warnings.append("No supplier-cost estimate: relationship cost is omitted, not known to be zero.")
    return {
        "terms": terms,
        "cash_cost": round(sum(cash.values()), 2),
        "estimated_total_cost": round(sum(central.values()), 2),
        "breakdown": {k: round(v, 2) for k, v in central.items()},
        "supplier_cost_source": "supplier-reported breakdown"
        if st.breakdown
        else st.intel.full_cost_source or "unknown",
        "supplier_cost_confidence": "low" if not st.breakdown else "supplier_reported_unverified",
        "sensitivity_scenarios": scenarios,
        "scenario_range": [min(s["total_cost"] for s in scenarios), max(s["total_cost"] for s in scenarios)]
        if scenarios
        else None,
        "alternative_cost": alternative if math.isfinite(alternative) else None,
        "must_haves_ok": must_haves_ok(case, terms, std),
        "beats_alternative_on_central_estimate": sum(central.values()) < alternative,
        "acceptance_probability": None,
        "warnings": warnings,
    }


class EvidenceDesk:
    """A bounded, per-turn view of public package/case evidence and received messages/documents."""

    def __init__(self, case, package, sid, threads):
        self.case, self.pkg, self.sid, self.threads = case, package, sid, threads
        self.sources = {}
        self._catalogue = None
        for supplier, events in threads.items():
            for i, message in enumerate(events):
                ref = f"thread:{supplier}:{i}"
                self.sources[ref] = {"id": ref, "kind": "message", "body": message.get("body") or ""}
                for j, attachment in enumerate(message.get("attachments") or []):
                    ref = f"attachment:{attachment.get('attachment_id') or f'{supplier}:{i}:{j}'}"
                    self.sources[ref] = {
                        "id": ref,
                        "kind": "attachment",
                        "name": attachment.get("name"),
                        "body": attachment.get("text") or "",
                        "supplier_id": supplier,
                    }

    def lookup(self, ref):
        # Case-local evidence is the most recent and may exist nowhere in the public package.
        return (
            self.sources.get(ref)
            or (self.case.get("facts") or {}).get(ref)
            or (self.pkg.lookup(ref) if self.pkg else None)
            or (self._catalogue or {}).get(ref)
        )

    def query(self, sql):
        """Model queries get their own read-only connection and CPU budget, never block the runner DB."""
        if not sql.strip() or sql.lstrip().split(None, 1)[0].lower() not in ("select", "with"):
            raise ValueError("read-only: SELECT or WITH statements only")
        if not self.pkg:
            raise ValueError("no public package")
        root = getattr(self.pkg, "root", None)
        dbs = sorted(root.rglob("*.sqlite")) + sorted(root.rglob("*.db")) if root else []
        if not dbs:
            return self.pkg.query(sql, limit=30)
        deadline = time.monotonic() + 0.25
        with closing(sqlite3.connect(f"file:{dbs[0]}?mode=ro", uri=True, timeout=0.25)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only = ON")
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            try:
                return [dict(row) for row in db.execute(sql).fetchmany(30)]
            except sqlite3.OperationalError as e:
                if "interrupted" in str(e):
                    raise ValueError("query exceeded its time budget; narrow the filters") from e
                raise

    def known(self, ref):
        return self.lookup(ref) is not None

    def document(self, ref, offset=0, limit=6000):
        if not self.known(ref):
            raise ValueError("unknown evidence ID; use search_evidence or query_data to discover IDs")
        row = self.lookup(ref)
        text = next((row[k] for k in ("body", "text", "content") if isinstance(row.get(k), str) and row[k]), None)
        if text is None and self.pkg:
            try:
                text = self.pkg.document(ref)
            except (FileNotFoundError, TypeError, ValueError):
                pass
        text = text or json_text(row)
        offset, limit = max(0, offset), min(max(1, limit), 10000)
        return {
            "id": ref,
            "text": text[offset : offset + limit],
            "offset": offset,
            "next_offset": offset + limit if len(text) > offset + limit else None,
        }

    def catalogue(self):
        if self._catalogue is not None:
            return self._catalogue
        parts = set(self.case.get("parts") or [])
        explicit = set(self.case.get("refs") or []) | parts | {self.sid, self.case.get("trigger_doc")}
        rows = dict(self.sources)
        facts = {**(self.pkg.facts if self.pkg else {}), **(self.case.get("facts") or {})}
        for ref, fact in facts.items():
            if not isinstance(fact, dict):
                continue
            supplier = fact.get("supplier") or fact.get("supplier_id")
            part = fact.get("part") or fact.get("part_id")
            if (
                ref in explicit
                or supplier == self.sid
                or part in parts
                or (ref.startswith(("news:", "doc:")) and not supplier)
            ):
                rows[ref] = fact
        for table in ("documents", "news", "index_series"):
            if not self.pkg:
                continue
            try:
                query = (
                    f"SELECT * FROM {table}"
                    if table == "index_series"
                    else f"SELECT * FROM {table} WHERE supplier_id = ? OR supplier_id IS NULL"
                )
                for row in self.pkg.query(query, () if table == "index_series" else (self.sid,)):
                    rows[row["id"]] = row
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        self._catalogue = rows
        return rows

    def search(self, query, limit=8):
        words = set(re.findall(r"[\w-]+", query.lower()))
        matches = []
        for ref, row in self.catalogue().items():
            text = json_text(row)
            if ref.startswith(("doc:", "news:")):
                try:
                    text += " " + self.document(ref)["text"]
                except (ValueError, KeyError, TypeError):
                    pass
            score = sum(word in text.lower() for word in words)
            if score or not words:
                matches.append((score, ref, text))
        matches.sort(key=lambda m: (-m[0], m[1]))
        return [{"id": ref, "excerpt": text[:1600]} for _, ref, text in matches[: min(max(limit, 1), 15)]]

    def build_argument(self, kind, refs, metric=""):
        """Construct the sentence from checked source fields; the model never supplies the asserted figure."""
        facts = []
        for ref in refs:
            fact = self.lookup(ref)
            if not isinstance(fact, dict):
                raise ValueError(f"unknown evidence ID: {ref}")
            supplier = fact.get("supplier") or fact.get("supplier_id")
            if supplier and supplier != self.sid:
                raise ValueError("argument refers to another supplier")
            facts.append(fact)
        if kind == "scorecard" and len(refs) == 1 and refs[0].startswith("sc:") and metric in ("ppm", "otd_pct"):
            value = facts[0].get(metric)
            if finite(value):
                words = (
                    f"complaint rate was {value:.0f} ppm" if metric == "ppm" else f"on-time delivery was {value:.1f}%"
                )
                return intel.Claim(
                    f"Your {words} in the rolling twelve months ({refs[0]}).", refs, "scorecard", tag=metric
                )
        if kind == "index_change" and len(refs) == 2 and all(ref.startswith("idx:") and "@" in ref for ref in refs):
            refs = sorted(refs)
            if refs[0].split("@")[0] != refs[1].split("@")[0]:
                raise ValueError("index months must refer to the same series")
            start, end = [date.fromisoformat(ref.split("@")[1] + "-01") for ref in refs]
            months = (end.year - start.year) * 12 + end.month - start.month
            series = refs[0][4:].split("@")[0]
            ids = set(self.pkg.ids(f"idx:{series}@") if self.pkg else [])
            ids.update(ref for ref in (self.case.get("facts") or {}) if ref.startswith(f"idx:{series}@"))
            latest_month = max(ids | set(refs)).split("@")[1]
            last = date.fromisoformat(latest_month + "-01")
            age = (last.year - end.year) * 12 + last.month - end.month
            a, b = [self.lookup(ref).get("value") for ref in refs]
            if not (1 <= months <= 12 and age <= 12 and finite(a) and a > 0 and finite(b)):
                raise ValueError(
                    "use valid index values over at most twelve months, ending within the latest twelve months"
                )
            pct = (b / a - 1) * 100
            return intel.Claim(
                f"This cost driver changed {pct:+.1f}% between the referenced months ({', '.join(refs)}).",
                refs,
                "index",
                tag=series,
            )
        if kind == "notice_period" and len(refs) == 2:
            pair = dict(zip(refs, facts, strict=True))
            letter = next((r for r in refs if r.startswith("doc:")), None)
            contract = next((r for r in refs if r.startswith("ctr:")), None)
            if letter and contract and all(finite(pair[r].get("days")) for r in (letter, contract)):
                return intel.Claim(
                    f"Your letter gives {pair[letter]['days']:g} days' notice ({letter}), while our agreement "
                    f"requires {pair[contract]['days']:g} days ({contract}).",
                    [letter, contract],
                    "notice",
                )
        if len(refs) == 1:
            ref, fact = refs[0], facts[0]
            if kind == "should_cost" and ref.startswith("cost:") and finite(fact.get("unit_cost")):
                part_ids = {f"cost:{part.split(':')[-1]}" for part in self.case.get("parts", [])}
                if ref not in part_ids:
                    raise ValueError("should-cost must refer to a part in this case")
                return intel.Claim(
                    f"Our should-cost estimate for this part is EUR {fact['unit_cost']:.2f} per unit ({ref}).",
                    refs,
                    "should_cost",
                )
            if kind == "forecast" and ref.startswith("fc:") and finite(fact.get("change_pct")):
                if not any(ref.startswith(f"fc:{part.split(':')[-1]}@") for part in self.case.get("parts", [])):
                    raise ValueError("forecast must refer to a part in this case")
                return intel.Claim(
                    f"Our demand forecast for this part changes {fact['change_pct']:+.1f}% ({ref}).", refs, "forecast"
                )
            if kind == "news" and ref.startswith("news:"):
                headline = fact.get("headline")
                if not headline and self.pkg:
                    rows = self.pkg.query("SELECT headline FROM news WHERE id = ?", (ref,))
                    headline = rows[0].get("headline") if rows else None
                if headline:
                    return intel.Claim(f"We read that {headline.rstrip('.')} ({ref}).", refs, "news")
        raise ValueError(
            "unsupported argument or missing source fields; inspect source fields before building an argument"
        )
