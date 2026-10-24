import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard_server.app import FIXTURES, Config, Source, create_app


def write_run(root: Path, run_id="20261024-153012-A", lines=None, meta=True):
    d = root / run_id
    d.mkdir(parents=True)
    if meta:
        (d / "run.json").write_text(json.dumps({"run_id": run_id, "agent": "A", "agent_version": "abc", "set": "sim",
                                                "started_at": "2026-10-24T15:30:12+02:00", "ended_at": None,
                                                "cases": ["case:P01"], "notes": ""}))
    base = {"run_id": run_id, "agent": "A", "case_id": "case:P01", "session_id": "s1"}
    lines = lines if lines is not None else [
        {"type": "case_opened", "case": {"title": "T", "type": "price_increase", "suppliers": ["sup:1"]},
         "opening": {"sup:1": {"offer_id": "o0", "supplier_name": "Sup One", "priced": {"c": 1000.0}}}, "c_alt": None},
        {"type": "decision", "round": 1, "supplier_id": "sup:1", "kind": "send"},
        {"type": "some_future_type", "x": 1},
        {"type": "result", "deal": True, "supplier_id": "sup:1", "c_open": 1000.0, "c_deal": 900.0, "c_best": 800.0,
         "c_alt": None, "score": 0.5, "end_reason": "accepted"},
    ]
    with (d / "case_P01.jsonl").open("w") as f:
        for i, ln in enumerate(lines):
            f.write(json.dumps({"ts": f"2026-10-24T15:30:{10 + i:02d}.000+02:00", "seq": i, **base, **ln}) + "\n")
    return d


@pytest.fixture
def runs_dir(tmp_path):
    return tmp_path / "runs"


def client(runs_dir, fallback=False):
    return TestClient(create_app(Config(sources=[Source("runs", runs_dir)], fixtures_fallback=fallback,
                                        dist=runs_dir / "no-dist")))


def test_lists_runs_with_case_summaries(runs_dir):
    write_run(runs_dir)
    r = client(runs_dir).get("/api/runs").json()
    assert [x["run_id"] for x in r["runs"]] == ["20261024-153012-A"]
    s = r["runs"][0]["case_summaries"][0]
    assert s["case_id"] == "case:P01" and s["status"] == "ended"
    assert s["score"] == 0.5 and s["saved"] == 100.0 and s["rounds"] == 1 and s["supplier_name"] == "Sup One"
    assert r["runs"][0]["mean_score"] == 0.5


def test_case_events_skip_partial_last_line_and_keep_unknown_types(runs_dir):
    d = write_run(runs_dir)
    with (d / "case_P01.jsonl").open("a") as f:
        f.write('{"ts": "2026-10-24T15:31:00+02:00", "type": "rep')  # still being written
    r = client(runs_dir).get("/api/runs/20261024-153012-A/cases/case:P01")
    assert r.status_code == 200
    types = [e["type"] for e in r.json()["events"]]
    assert types == ["case_opened", "decision", "some_future_type", "result"]


def test_running_case_without_result(runs_dir):
    write_run(runs_dir, lines=[{"type": "case_opened", "case": {}, "opening": {}, "c_alt": None}])
    s = client(runs_dir).get("/api/runs").json()["runs"][0]
    assert s["running"] and s["case_summaries"][0]["status"] == "running"


def test_run_without_run_json(runs_dir):
    write_run(runs_dir, run_id="20261024-160000-C", meta=False)
    r = client(runs_dir).get("/api/runs").json()["runs"][0]
    assert r["run_id"] == "20261024-160000-C" and r["agent"] == "C"


def test_unknown_and_traversal_paths_404(runs_dir):
    write_run(runs_dir)
    c = client(runs_dir)
    assert c.get("/api/runs/nope/cases/case:P01").status_code == 404
    assert c.get("/api/runs/20261024-153012-A/cases/..%2Frun").status_code == 404
    assert c.get("/api/runs/..%2F..%2Fetc/cases/passwd").status_code == 404


def test_version_changes_when_files_change(runs_dir):
    d = write_run(runs_dir)
    c = client(runs_dir)
    v1 = c.get("/api/version").json()["version"]
    with (d / "case_P01.jsonl").open("a") as f:
        f.write(json.dumps({"type": "trace", "trace": []}) + "\n")
    assert c.get("/api/version").json()["version"] != v1


def test_falls_back_to_fixtures_when_runs_is_empty(runs_dir):
    r = client(runs_dir, fallback=True).get("/api/runs").json()
    assert r["sources"] == ["fixtures"]
    assert {x["agent"] for x in r["runs"]} >= {"A", "C"}


@pytest.mark.skipif(not FIXTURES.is_dir(), reason="no fixtures")
def test_every_fixture_follows_the_contract():
    required = {"ts", "seq", "run_id", "agent", "case_id", "session_id", "type"}
    for f in FIXTURES.glob("*/*.jsonl"):
        lines = [json.loads(ln) for ln in f.read_text().splitlines()]
        assert [e["seq"] for e in lines] == list(range(len(lines)))
        assert all(required <= e.keys() for e in lines), f
        assert lines[0]["type"] == "case_opened"
        assert any(e["type"] == "result" for e in lines), f


def test_repeated_case_plays_and_imported_source(runs_dir):
    d = write_run(runs_dir)
    meta = json.loads((d / "run.json").read_text())
    (d / "run.json").write_text(json.dumps({**meta, "source": "imported", "author": "ege", "variant": "v5"}))
    (d / "case_P01~2.jsonl").write_text((d / "case_P01.jsonl").read_text())
    c = client(runs_dir)
    run = c.get("/api/runs").json()["runs"][0]
    assert run["source"] == "imported" and run["author"] == "ege" and run["variant"] == "v5"
    keys = [s["case_id"] for s in run["case_summaries"]]
    assert keys == ["case:P01", "case:P01~2"]
    assert run["case_summaries"][1]["real_case_id"] == "case:P01" and run["case_summaries"][1]["repeat"] == 2
    r = c.get("/api/runs/20261024-153012-A/cases/case:P01~2")
    assert r.status_code == 200 and r.json()["events"][0]["case_id"] == "case:P01"


def test_importer_converts_a_saved_session(tmp_path):
    """The importer's conversion on a minimal arena session (no network)."""
    import importlib.util
    import sys

    path = Path(__file__).resolve().parents[2] / "import_sessions.py"
    try:
        import arena_kit  # noqa: F401
    except ImportError:
        pytest.skip("arena_kit not installed in this env (run with uv run --project ../../starter-kit)")
    spec = importlib.util.spec_from_file_location("import_sessions", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["import_sessions"] = mod
    spec.loader.exec_module(mod)
    case = {"case_id": "case:X", "negotiable": ["unit_price"], "fixed_terms": {"volume_per_year": 100, "contract_months": 12},
            "term_options": {}, "suppliers": ["sup:1"],
            "buyer": {"need_per_year": 100, "horizon_years": 1, "fallback_unit_price": 12, "interest_rate": 0.08,
                      "reference_payment_days": 60, "need_lead_time_days": 30, "freight_eur_per_unit": {"EXW": 1, "FCA": 0.5, "DAP": 0},
                      "alternative": {"kind": "none", "terms": {}}}}
    sheet = lambda oid, p: {"term_sheet_id": oid, "terms": {"unit_price": p}}  # noqa: E731
    state = {"session_id": "s1", "case_id": "case:X", "end_reason": "accepted", "created_at": 1792840266.0,
             "quote_terms": {"sup:1": {"standard": {"payment_days": 60, "incoterm": "DAP", "lead_time_days": 30}}},
             "messages": {"sup:1": [
                 {"from": "sales@1", "from_name": "Owner, Sup One GmbH", "body": "quote", "term_sheets": [sheet("offer:1-0", 10.0)]},
                 {"from": "buyer", "subject": "s", "body": "lower", "term_sheets": [{"terms": {"unit_price": 9.0}}]},
                 {"from": "sales@1", "status": "final_offer", "body": "ok", "term_sheets": [sheet("offer:1-1", 9.5)], "claim_results": []},
                 {"from": "buyer", "action": {"type": "accept", "term_sheet_id": "offer:1-1"}},
                 {"from": "sales@1", "status": "agreed", "body": "thanks", "term_sheets": [sheet("offer:1-1", 9.5)]}]},
             "result": {"deal": True, "supplier_id": "sup:1", "offer_id": "offer:1-1", "c_open": 1000.0, "c_deal": 950.0,
                        "c_best": 900.0, "score": 0.5, "cost_breakdown": {},
                        "trace": [{"round": 0, "actor": "sup:1", "move": {}, "reasons": ["r0"]},
                                  {"round": 1, "actor": "buyer", "move": {"type": "message", "supplier_id": "sup:1",
                                                                          "interpreted": {"claims": [{"type": "index_change", "refs": ["idx:A@1"]}]}}},
                                  {"round": 1, "actor": "sup:1", "move": {}, "reasons": ["r1"]},
                                  {"round": 1, "actor": "buyer", "move": {"type": "accept", "supplier_id": "sup:1"}}]}}
    events, check = mod.convert(state, case, None, "https://arena.example")
    types = [e["type"] for e in events]
    assert types == ["case_opened", "message_sent", "reply", "decision", "reply", "result", "trace"]
    assert events[0]["opening"]["sup:1"]["supplier_name"] == "Sup One GmbH"
    assert events[0]["opening"]["sup:1"]["priced"]["c"] == 1000.0  # 100 x 10.00, DAP, 60 days
    assert events[1]["claims"][0]["id"] == "idx:A@1" and events[2]["reasons"] == ["r1"]
    assert events[3]["round"] == 2 and events[3]["kind"] == "accept" and events[4]["round"] == 2
    assert check["open"] == (1000.0, 1000.0) and check["deal"] == (950.0, 950.0)
