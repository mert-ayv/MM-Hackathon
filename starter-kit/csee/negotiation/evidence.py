"""Compact, attributed records for research. Figures are read/calculated, never model-authored."""

from .. import intel
from .preparation import claim_id


def records(case, package, claims):
    out = {}
    for claim in claims:
        facts = []
        for ref in claim.ids:
            fact = intel._fact(case, package, ref)
            if isinstance(fact, dict):
                facts.append({"ref": ref, **fact})
        record = {
            "kind": claim.kind,
            "metric": claim.tag or claim.kind,
            "statement": claim.sentence,
            "sources": list(claim.ids),
            "observations": facts,
            "scope": {
                "suppliers": sorted(
                    {
                        str(f.get("supplier") or f.get("supplier_id"))
                        for f in facts
                        if f.get("supplier") or f.get("supplier_id")
                    }
                ),
                "parts": sorted(
                    {str(f.get("part") or f.get("part_id")) for f in facts if f.get("part") or f.get("part_id")}
                ),
            },
            "periods": sorted(
                {str(f.get("date") or f.get("month") or f.get("quarter") or f["ref"].partition("@")[2]) for f in facts}
                - {""}
            ),
            "status": "documented" if len(facts) == len(claim.ids) else "incomplete_sources",
            "uncertainty": "Source accuracy and commercial relevance remain unverified by the supplier.",
        }
        if claim.kind == "index" and len(facts) == len(claim.ids) == 2:
            a, b = facts
            if isinstance(a.get("value"), (int, float)) and a["value"] > 0 and isinstance(b.get("value"), (int, float)):
                record["calculation"] = {
                    "formula": "100 * (end / start - 1)",
                    "start": a["value"],
                    "end": b["value"],
                    "change_pct": round(100 * (b["value"] / a["value"] - 1), 3),
                }
                record["status"] = "calculated_from_documents"
        if claim.kind == "should_cost":
            record["uncertainty"] = "Buyer estimate, not a supplier reservation price or guaranteed production cost."
        if claim.source == "history":
            record["uncertainty"] = (
                "Historical observation; not a current commitment or evidence of willingness to concede."
            )
        out[claim_id(claim)] = record
    return out


def digests(case, package, sid, claims):
    """Bounded, scope-specific tables supplement source excerpts; missing tables stay missing."""
    parts = case.get("parts", [])
    economics, history = [], []
    for part in parts[:6]:
        economics.extend(intel._q(package, "SELECT * FROM should_cost WHERE part_id = ?", (part,))[:4])
        history.extend(
            intel._q(
                package,
                "SELECT * FROM price_conditions WHERE supplier_id = ? AND part_id = ? ORDER BY valid_from DESC LIMIT 6",
                (sid, part),
            )
        )
    invoices = intel._q(
        package, "SELECT * FROM invoices WHERE supplier_id = ? ORDER BY invoice_date DESC LIMIT 12", (sid,)
    )
    past = intel._q(
        package, "SELECT * FROM negotiation_history WHERE supplier_id = ? ORDER BY date DESC LIMIT 6", (sid,)
    )
    evidence = records(case, package, claims)
    return {
        "economics": {
            "should_cost_estimates": economics,
            "price_history": history,
            "measured_indices": {k: v for k, v in evidence.items() if v["kind"] == "index"},
        },
        "counterpart": {
            "invoice_observations": invoices,
            "past_negotiations": past,
            "caution": "Past payment delays are observations, not a prohibition on offering faster payment.",
        },
        "evidence": {"claim_records": evidence},
        "competition": {
            "price_history": history,
            "past_negotiations": past,
            "caution": "Historical prices are not live rival bids or supplier floors.",
        },
    }
