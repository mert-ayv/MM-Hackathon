"""Sourced bundle arithmetic, without a supplier-specific negotiation policy.

Only an explicit bill of materials establishes component quantities. Supported sources are a
``bom``/``bundle_components`` list with ``part_id`` and ``quantity_per_kit`` fields, or a memo with
an explicit per-kit heading and lines such as ``- 7 x Washer (part:new-washer)``. Missing parts,
duplicate components and conflicting sources make the quantity report unavailable.

Database row provenance is retained separately from citable fact IDs. A sum of component prices is
a comparison benchmark, never a supplier cost floor, bundled quotation or acceptance prediction.
"""

import math
import re
import sqlite3
from datetime import date

from ..intel import Claim

MAX_PARTS, MAX_DOCUMENTS, MAX_DOCUMENT_CHARS = 12, 6, 12000
MAX_FACTS, MAX_REFERENCES = 1000, 40
PART = r"part:[A-Za-z0-9_.-]+"
BOM_LINE = re.compile(rf"^\s*[-*]\s*(\d+(?:\.\d+)?)\s*[x×]\s*.+?\s*\(({PART})\)\s*$", re.I)
BOM_HEADING = re.compile(r"\b(?:kit|bundle)\s+per\s+(?:unit|kit|bundle)\b|\bper\s+(?:kit|bundle)\b", re.I)
BOM_KEYS = ("bom", "bundle_components", "kit_components", "bill_of_materials")


def _number(value, positive=False):
    try:
        return (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(value)
            and (value > 0 if positive else value >= 0)
        )
    except OverflowError:
        return False


def _quantity(value):
    rounded = round(value, 8)
    return int(rounded) if rounded == int(rounded) else rounded


def _bom(rows, required):
    if not isinstance(rows, list) or len(rows) > MAX_PARTS:
        raise ValueError("BOM must be a bounded list of explicit component quantities")
    quantities = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("BOM components must contain part_id and quantity_per_kit")
        part = row.get("part_id") or row.get("part")
        qty = row.get("quantity_per_kit")
        if not isinstance(part, str) or part not in required or not _number(qty, positive=True):
            raise ValueError("BOM contains an unknown part or an invalid per-kit quantity")
        if part in quantities:
            raise ValueError("BOM repeats a component; quantities cannot be inferred or added")
        quantities[part] = qty
    if set(quantities) != required:
        raise ValueError("BOM does not cover exactly the case's component parts")
    return quantities


def _memo_bom(text, required):
    if not BOM_HEADING.search(text):
        return None
    rows = []
    for line in text.splitlines():
        if not re.match(r"\s*[-*]\s", line) or not re.search(PART, line):
            continue
        match = BOM_LINE.fullmatch(line)
        if not match:
            raise ValueError("component line has no unambiguous quantity per kit")
        rows.append({"part_id": match[2], "quantity_per_kit": float(match[1])})
    return _bom(rows, required)


def _document(desk, ref):
    """At most two bounded pages; never silently accept an incomplete source."""
    text, offset = "", 0
    for _ in range(2):
        page = desk.document(ref, offset)
        chunk = page.get("text")
        if not isinstance(chunk, str) or len(chunk) + len(text) > MAX_DOCUMENT_CHARS:
            raise ValueError("BOM document exceeds the bounded read")
        text += chunk
        following = page.get("next_offset")
        if following is None:
            return text
        if not isinstance(following, int) or following <= offset:
            raise ValueError("invalid document pagination")
        offset = following
    raise ValueError("BOM document is incomplete within the bounded read")


def _literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def _query(desk, sql):
    try:
        rows = desk.query(sql)
        return [row for row in rows[:30] if isinstance(row, dict)]
    except (AttributeError, ValueError, TypeError, KeyError, sqlite3.Error):
        return []


def _provenance(table, row, fields):
    return {"table": table, "key": {key: row.get(key) for key in fields}}


def _price(row, source):
    price, unit = row.get("price"), row.get("price_unit")
    supplier = row.get("supplier_id") or row.get("supplier")
    valid_from = row.get("valid_from")
    if (
        not _number(price, positive=True)
        or not _number(unit, positive=True)
        or int(unit) != unit
        or row.get("currency") != "EUR"
        or not isinstance(supplier, str)
        or not supplier
    ):
        return None
    if valid_from is not None:
        if not isinstance(valid_from, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valid_from):
            return None
        try:
            date.fromisoformat(valid_from)
        except ValueError:
            return None
    return {
        "supplier_id": supplier,
        "price_eur": price,
        "price_unit": int(unit),
        "eur_per_component": round(price / unit, 8),
        "valid_from": valid_from,
        "source": source,
    }


def bundle_context(case, desk):
    """Return a bounded, JSON-serializable report from actual sources, or available=False.

    ``desk`` supplies ``lookup(ref)``, ``document(ref, offset=0)``, optional ``query(sql)``, and
    ``sid``. No search/model/network call is made. Case-local structured facts take precedence
    through the desk. Prices require explicit EUR and price_unit; absent values stay unknown.
    """
    report = {
        "available": False,
        "source_ids": [],
        "annual_kits": None,
        "annual_kits_source": None,
        "parts": [],
        "supplier_incumbent_spend": [],
        "warnings": [],
        "verification_scope": "Source-checked arithmetic only; arena checker support for BOM claims is unknown.",
    }
    parts = case.get("parts") or []
    if (
        case.get("type") != "bundling"
        or not isinstance(parts, list)
        or not 1 < len(parts) <= MAX_PARTS
        or not all(isinstance(part, str) and re.fullmatch(PART, part) for part in parts)
        or len(set(parts)) != len(parts)
    ):
        report["warnings"].append("Requires a bounded multi-part bundling case with distinct parts.")
        return report
    required = set(parts)
    facts = case.get("facts") or {}
    refs = case.get("refs") or []
    if (
        not isinstance(facts, dict)
        or not isinstance(refs, list)
        or any(not isinstance(ref, str) for ref in refs)
        or (case.get("trigger_doc") is not None and not isinstance(case["trigger_doc"], str))
    ):
        report["warnings"].append("Bundle source references or facts are malformed; no quantities are inferred.")
        return report
    explicit = list(dict.fromkeys([case.get("trigger_doc"), *refs]))
    if len(facts) > MAX_FACTS or len(explicit) > MAX_REFERENCES:
        report["warnings"].append("Case evidence exceeds the bounded bundle review; narrow the source references.")
        return report
    structured = [ref for ref, row in facts.items() if isinstance(row, dict) and any(k in row for k in BOM_KEYS)]
    sources, errors, candidates = [], [], []
    # Bounded case-local facts and the explicit trigger/references avoid scanning unrelated documents.
    if len(structured) > MAX_DOCUMENTS:
        report["warnings"].append("Too many structured BOM sources to establish one unambiguous bundle.")
        return report
    for ref in list(dict.fromkeys([*structured, *explicit])):
        if not ref:
            continue
        row = desk.lookup(ref)
        if isinstance(row, dict):
            for key in BOM_KEYS:
                if key in row:
                    try:
                        candidates.append((_bom(row[key], required), ref))
                    except ValueError as exc:
                        errors.append(f"{ref}: {exc}")
        if ref.startswith(("doc:", "attachment:")):
            sources.append(ref)
    if len(sources) > MAX_DOCUMENTS:
        errors.append("Too many referenced documents to verify the complete BOM.")
    # Explicit structured case facts describe the current bundle, even if the package contains an
    # older memo with the same ID. Do not replace or reinterpret those quantities from prose.
    for ref in sources[:MAX_DOCUMENTS] if not structured else []:
        try:
            text = _document(desk, ref)
            quantities = _memo_bom(text, required)
            if quantities is not None:
                candidates.append((quantities, ref))
        except (ValueError, KeyError, TypeError, FileNotFoundError) as exc:
            errors.append(f"{ref}: {exc}")
    if candidates and any(qty != candidates[0][0] for qty, _ in candidates[1:]):
        errors.append("BOM sources disagree on component quantities.")
    if errors or not candidates:
        report["warnings"].extend(errors or ["No complete explicit per-kit BOM found; quantities are unknown."])
        return report
    quantities = candidates[0][0]
    report["source_ids"] = list(dict.fromkeys(ref for _, ref in candidates))
    buyer, fixed = case.get("buyer") or {}, case.get("fixed_terms") or {}
    need, volume = buyer.get("need_per_year"), fixed.get("volume_per_year")
    if not _number(need, positive=True):
        report["warnings"].append("Annual kit demand is missing; annual component requirements are unknown.")
    elif volume is not None and (not _number(volume, positive=True) or volume != need):
        report["warnings"].append("Fixed annual volume differs from demand; no annual commitment is inferred.")
    elif not all(_number(quantity * need) for quantity in quantities.values()):
        report["warnings"].append("Annual component arithmetic is not finite; annual requirements are unknown.")
    else:
        report["annual_kits"] = need
        report["annual_kits_source"] = "case.buyer.need_per_year"
        report["annual_volume_is_fixed"] = volume == need

    in_parts = ",".join(_literal(part) for part in parts)
    prices = _query(
        desk,
        "SELECT * FROM price_conditions WHERE part_id IN (" + in_parts + ") "
        "AND valid_to IS NULL ORDER BY valid_from DESC LIMIT 30",
    )
    sourcing = _query(desk, "SELECT * FROM sourcing WHERE part_id IN (" + in_parts + ") LIMIT 30")
    if len(prices) == 30 or len(sourcing) == 30:
        report["warnings"].append("Database evidence hit its row bound; component comparisons may be incomplete.")
    price_rows = [
        (row, _provenance("price_conditions", row, ("part_id", "supplier_id", "valid_from"))) for row in prices
    ]
    sourcing_rows = [(row, _provenance("sourcing", row, ("part_id", "supplier_id"))) for row in sourcing]
    for ref, row in facts.items():
        if not isinstance(row, dict):
            continue
        part = row.get("part_id") or row.get("part")
        if not isinstance(part, str) or part not in required:
            continue
        if row.get("type") == "price_condition" and row.get("valid_to") is None:
            price_rows.append((row, {"id": ref}))
        if row.get("type") == "sourcing":
            sourcing_rows.append((row, {"id": ref}))
    for part in parts:
        benchmarks = []
        for row, source in price_rows:
            if (row.get("part_id") or row.get("part")) == part:
                normalized = _price(row, source)
                if normalized is not None:
                    benchmarks.append(normalized)
                else:
                    report["warnings"].append(
                        f"Invalid price condition for {part} omitted: require explicit EUR, supplier, positive "
                        "price unit, and an ISO date when valid_from is supplied."
                    )
        # Most recent active condition per supplier; never mix currencies or infer a missing price unit.
        benchmarks.sort(key=lambda row: row.get("valid_from") or "", reverse=True)
        latest = {}
        for row in benchmarks:
            latest.setdefault(row["supplier_id"], row)
        incumbents = []
        for row, source in sourcing_rows:
            quota = row.get("quota_pct")
            if (
                (row.get("part_id") or row.get("part")) == part
                and row.get("status") == "active"
                and _number(quota)
                and quota <= 100
            ):
                incumbents.append(
                    {"supplier_id": row.get("supplier_id") or row.get("supplier"), "quota_pct": quota, "source": source}
                )
        report["parts"].append(
            {
                "part_id": part,
                "quantity_per_kit": _quantity(quantities[part]),
                "annual_units": _quantity(quantities[part] * report["annual_kits"])
                if report["annual_kits"] is not None
                else None,
                "quantity_source_ids": report["source_ids"],
                "price_benchmarks": list(latest.values()),
                "incumbent_sourcing": incumbents,
            }
        )
    if all(part["price_benchmarks"] for part in report["parts"]):
        report["component_price_benchmark"] = {
            "eur_per_kit": round(
                sum(
                    part["quantity_per_kit"] * min(p["eur_per_component"] for p in part["price_benchmarks"])
                    for part in report["parts"]
                ),
                6,
            ),
            "meaning": "Sum of lowest sourced component prices; not a bundle quotation or supplier cost floor.",
        }
    sid = getattr(desk, "sid", None)
    if sid:
        spends = _query(
            desk,
            "SELECT * FROM spend_cube WHERE supplier_id = " + _literal(sid) + " ORDER BY fiscal_year DESC LIMIT 3",
        )
        for row in spends:
            if _number(row.get("spend_eur")):
                report["supplier_incumbent_spend"].append(
                    {
                        "spend_eur": row["spend_eur"],
                        "fiscal_year": row.get("fiscal_year"),
                        "category": row.get("category"),
                        "scope": "Supplier/category spend, not necessarily this kit or its component parts.",
                        "source": _provenance("spend_cube", row, ("supplier_id", "fiscal_year", "category")),
                    }
                )
    report["available"] = True
    report["warnings"].append(
        "Bundle scope is already part of the case requirement. Do not assert extra annual kits, "
        "automatic savings, supplier margin or acceptance from these calculations."
    )
    return report


def bundle_claim(report):
    """Render source-checked BOM quantities and derived demand, without claiming extra volume.

    References establish the BOM; annual quantities additionally use the explicit case demand. This
    is source-backed reasoning, not a promise that the arena's limited fact checker supports BOMs.
    """
    if not report.get("available") or not report.get("source_ids") or not report.get("parts"):
        return None
    pieces = [f"{part['quantity_per_kit']:g} of {part['part_id']}" for part in report["parts"]]
    refs = list(report["source_ids"])
    sentence = "The bundle specification contains " + ", ".join(pieces) + " per kit"
    if report.get("annual_kits") is not None:
        annual = [f"{part['annual_units']:g} of {part['part_id']}" for part in report["parts"]]
        sentence += f"; at the case's annual requirement of {report['annual_kits']:g} kits this represents "
        sentence += ", ".join(annual) + " per year"
    sentence += " (" + ", ".join(refs) + ")."
    return Claim(sentence, refs, "bundle_scope", strength=1.2, source="source_derived_bundle")


def claim_is_comparable(case, claim, desk):
    """Filter unqualified component-price comparisons from a whole-kit negotiation.

    Genuine aggregate price facts must explicitly declare scope=kit/bundle, uom=kit/bundle, a price
    per one kit and the exact aggregate part_ids. Existence alone is insufficient. Other families pass.
    """
    if case.get("type") != "bundling" or len(case.get("parts") or []) < 2:
        return True
    if claim.kind not in ("history", "price_history", "should_cost"):
        return True
    if not all(isinstance(ref, str) for ref in claim.ids):
        return False
    relevant = [ref for ref in claim.ids if ref.startswith(("po:", "cost:", "quote:"))]
    if not relevant:
        return False
    if not all(isinstance(part, str) for part in case["parts"]):
        return False
    required = set(case["parts"])
    for ref in relevant:
        fact = desk.lookup(ref)
        if not isinstance(fact, dict):
            return False
        scope = fact.get("scope")
        uom = fact.get("uom") or fact.get("price_uom")
        parts = fact.get("part_ids")
        unit = fact.get("price_unit")
        if (
            scope not in ("kit", "bundle")
            or uom not in ("kit", "bundle")
            or not isinstance(parts, list)
            or not all(isinstance(part, str) for part in parts)
            or set(parts) != required
            or len(parts) != len(required)
            or not _number(unit, positive=True)
            or unit != 1
        ):
            return False
    return True
