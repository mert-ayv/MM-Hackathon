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
