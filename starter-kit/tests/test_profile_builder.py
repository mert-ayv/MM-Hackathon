"""csee.profile_builder without any LLM call: hard fields, ID/quote guards, fake release, merge, apply."""

import json

import pytest

from csee.profile_builder import common, facts, rehearse, update, validate
from csee.profile_builder.verify import Checker


@pytest.fixture(scope="module")
def pkg():
    try:
        return common.open_package()
    except SystemExit:
        pytest.skip("no data package")


def test_hard_fields_match_curated(pkg):
    res = validate.run(pkg, verbose=False)
    assert res["suppliers"] == 46
    assert res["agree"] / res["total"] > 0.97
    assert res["agree_alt"] / res["total"] > 0.99
    assert facts.build(pkg, "70110") == facts.build(pkg, "sup:70110")  # deterministic


def test_checker_drops_unknown_ids_and_non_verbatim_quotes(pkg):
    c = Checker(pkg)
    out = c.entries([{"type": "cash", "evidence": "x", "ids": ["doc:20260902-70110-M2", "doc:nope"]},
                     {"type": "cash", "evidence": "y", "ids": ["doc:nope"]}], "pressures")  # fmt: skip
    assert [e["ids"] for e in out] == [["doc:20260902-70110-M2"]]
    q = c.quotes([{"id": "doc:20260902-70110-M2", "quote": "Could you pay our invoices within 10 days?"},
                  {"id": "doc:20260902-70110-M2", "quote": "We demand payment in one day."}])  # fmt: skip
    assert len(q) == 1


def test_fake_release_detect_merge_apply(tmp_path, pkg):
    d = rehearse.build(tmp_path / "r", since="2026-09-24")
    rp = common.open_package(d / "package", d / "release-sunday")
    found = update.detect(rp, d / "profiles_before")
    assert "sup:70240" in found["by_supplier"]
    assert all(i["id"] in rp.facts for i in found["items"])  # release facts merged
    items = found["by_supplier"]["sup:70240"]
    cur = common.curated("70240", d / "profiles_before")
    patch = {
        "situation": "Founder-led CZ shop; order intake very strong (doc:20260924-70240-M1), extra volume only "
        "against a binding 12-month commitment. Invented doc:20991231-70240-X is dropped.",
        "add_pressures": [{"type": "capacity", "evidence": "binding 12 months", "ids": ["doc:20260924-70240-M1"]}],
        "what_it_values": [],
        "add_key_quotes": [{"id": "doc:20260924-70240-M1", "quote": "Order intake is very strong."}],
        "removals": [{"field": "noise", "match": cur["noise"][0], "reason": ""}],  # no reason -> ignored
        "change_summary": "test",
    }
    new, log, removed = update.merge(rp, cur, patch, items, "2026-10-04")
    assert "[unverified]" in new["situation"] and not removed
    assert new["what_it_values"] == cur["what_it_values"]  # nothing curated silently lost
    assert new["updated_from"] == ["doc:20260924-70240-M1"]
    prof = tmp_path / "profiles"
    prof.mkdir()
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "70240.json").write_text(common.dump(new))
    update.apply(staged, prof)
    assert json.loads((prof / "70240.json").read_text())["key_quotes"][-1]["quote"] == "Order intake is very strong."
