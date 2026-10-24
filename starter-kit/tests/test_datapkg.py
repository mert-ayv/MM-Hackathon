"""The shared data package under concurrency: what every case prepares at a wave start must not
depend on how many cases prepare at the same moment. No arena calls, no LLM."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from arena_kit.data import DataPackage
from csee import intel
from csee.datapkg import SharedPackage, shared

CASES = Path(__file__).parents[1] / "csee" / "cases" / "practice.json"
DATA = next(
    (p for p in (Path(__file__).parents[1] / "data" / "package", Path(__file__).parents[2] / "data") if p.exists()),
    None,
)
pytestmark = pytest.mark.skipif(not CASES.exists() or DATA is None, reason="no case files or data package")


def _jobs():
    cases = json.loads(CASES.read_text())
    cases = cases if isinstance(cases, list) else cases.get("cases", list(cases.values()))
    return [(c, sid) for c in cases for sid in c["suppliers"]]


def _fingerprint(info):
    return (info.full_cost, info.full_cost_source, info.country, [c.sentence for c in info.claims])


def test_shared_wrapper_passes_through():
    pkg = shared(DataPackage(DATA))
    assert isinstance(pkg, SharedPackage) and shared(pkg) is pkg and shared(None) is None
    assert pkg.facts is pkg._pkg.facts  # plain attributes are the package's own
    assert pkg.lookup("sup:70110") == pkg._pkg.lookup("sup:70110")


def test_concurrent_prepare_matches_sequential():
    jobs = _jobs()
    pkg = shared(DataPackage(DATA))
    pkg.lookup("")  # the ID index, built once as csee.__main__ does
    sequential = [_fingerprint(intel.build(c, pkg, sid)) for c, sid in jobs]
    for _ in range(3):
        with ThreadPoolExecutor(max_workers=16) as pool:
            parallel = list(pool.map(lambda j: _fingerprint(intel.build(j[0], pkg, j[1])), jobs))
        assert parallel == sequential
