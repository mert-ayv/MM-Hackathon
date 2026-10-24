"""Read-only API over the run logs (`docs/run-log.md`) and the built dashboard.

Never writes anything; the runner never depends on it. Run with `dashboard` (see dashboard/README.md).
"""

import argparse
import hashlib
import json
import os
import threading
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
DASHBOARD = HERE.parents[1]  # dashboard/
REPO = DASHBOARD.parent
DEFAULT_RUNS = REPO / "runs"
FIXTURES = DASHBOARD / "fixtures" / "runs"
WEB_DIST = DASHBOARD / "web" / "dist"


@dataclass
class Source:
    name: str  # "runs" | "fixtures"
    root: Path


@dataclass
class Config:
    sources: list[Source] = field(default_factory=list)
    fixtures_fallback: bool = True  # show fixtures when no real runs exist
    dist: Path = WEB_DIST


def read_events(path: Path) -> list[dict]:
    """Parse a JSONL case log. A half-written last line (the agent is still writing) is skipped."""
    events = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return events
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and "type" in ev:
            events.append(ev)
    return events


def summarize(events: list[dict], path: Path) -> dict:
    """What the run table needs from a case log."""
    # the file names the case within its run ("case_D01~2" = the second play of case:D01); events carry the real id
    key = path.stem.replace("_", ":", 1)
    real = next((e.get("case_id") for e in events if e.get("case_id")), None) or key.split("~")[0]
    s = {"case_id": key, "real_case_id": real, "repeat": int(key.split("~")[1]) if "~" in key and key.split("~")[1].isdigit() else 1,
         "file": path.name, "events": len(events), "status": "running",
         "title": None, "type": None, "suppliers": [], "rounds": 0, "deal": None, "score": None,
         "c_open": None, "c_deal": None, "c_best": None, "c_alt": None, "saved": None, "end_reason": None,
         "supplier_id": None, "supplier_name": None, "errors": 0,
         "first_ts": events[0].get("ts") if events else None, "last_ts": events[-1].get("ts") if events else None}
    names = {}
    for e in events:
        t = e.get("type")
        if t == "case_opened":
            case = e.get("case") or {}
            s["title"], s["type"] = case.get("title"), case.get("type")
            s["suppliers"] = case.get("suppliers") or list((e.get("opening") or {}).keys())
            s["c_alt"] = e.get("c_alt")
            for sid, o in (e.get("opening") or {}).items():
                names[sid] = (o or {}).get("supplier_name")
            opened = [((o or {}).get("priced") or {}).get("c") for o in (e.get("opening") or {}).values()]
            opened = [c for c in opened if isinstance(c, int | float)]
            if opened:
                s["c_open"] = min(opened)
        elif t == "decision" and isinstance(e.get("round"), int):
            s["rounds"] = max(s["rounds"], e["round"])
        elif t == "error":
            s["errors"] += 1
        elif t == "result":
            s["status"] = "ended"
            for k in ("deal", "score", "c_open", "c_deal", "c_best", "c_alt", "end_reason", "supplier_id"):
                if e.get(k) is not None or k in ("deal", "supplier_id"):
                    s[k] = e.get(k)
            if s["deal"] and isinstance(s["c_open"], int | float) and isinstance(s["c_deal"], int | float):
                s["saved"] = round(s["c_open"] - s["c_deal"], 2)
    s["supplier_name"] = names.get(s["supplier_id"])
    return s


class Store:
    """Scans the run folders; caches per-file summaries by (mtime, size)."""

    def __init__(self, config: Config):
        self.config = config
        self._cache: dict[Path, tuple[tuple[int, int], dict]] = {}
        self._lock = threading.Lock()

    def active_sources(self) -> list[Source]:
        srcs = [s for s in self.config.sources if s.root.is_dir()]
        real = [s for s in srcs if s.name != "fixtures"]
        has_real = any(self._run_dirs(s.root) for s in real)
        if not has_real and self.config.fixtures_fallback and FIXTURES.is_dir():
            if not any(s.name == "fixtures" for s in srcs):
                srcs.append(Source("fixtures", FIXTURES))
        return srcs

    @staticmethod
    def _run_dirs(root: Path) -> list[Path]:
        try:
            return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
        except OSError:
            return []

    def _summary(self, path: Path) -> dict:
        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
        with self._lock:
            hit = self._cache.get(path)
            if hit and hit[0] == key:
                return hit[1]
        s = summarize(read_events(path), path)
        with self._lock:
            self._cache[path] = (key, s)
        return s

    def version(self) -> str:
        h = hashlib.sha1()
        for src in self.active_sources():
            for d in self._run_dirs(src.root):
                for f in sorted(d.iterdir()):
                    try:
                        st = f.stat()
                    except OSError:
                        continue
                    h.update(f"{f}:{st.st_mtime_ns}:{st.st_size};".encode())
        return h.hexdigest()[:16]

    def _meta(self, d: Path, source: str) -> dict:
        meta = {}
        try:
            meta = json.loads((d / "run.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        if not isinstance(meta, dict):
            meta = {}
        agent = meta.get("agent") or (d.name.rsplit("-", 1)[-1] if "-" in d.name else None)
        return {"run_id": meta.get("run_id") or d.name, "agent": agent, "agent_version": meta.get("agent_version"),
                "set": meta.get("set"), "started_at": meta.get("started_at"), "ended_at": meta.get("ended_at"),
                "cases": meta.get("cases") or [], "notes": meta.get("notes"), "source": meta.get("source") or source,
                "folder": source, "dir": d.name, "author": meta.get("author"), "variant": meta.get("variant"),
                "agent_name": meta.get("agent_name"), "commit": meta.get("commit")}

    def runs(self) -> list[dict]:
        out, seen = [], set()
        for src in self.active_sources():
            for d in self._run_dirs(src.root):
                if not ((d / "run.json").exists() or any(d.glob("*.jsonl"))):
                    continue
                meta = self._meta(d, src.name)
                if meta["run_id"] in seen:  # runs/ wins over fixtures
                    continue
                seen.add(meta["run_id"])
                summaries = {}
                for f in sorted(d.glob("*.jsonl")):
                    s = self._summary(f)
                    summaries[s["case_id"]] = s
                order = [c for c in meta["cases"] if c in summaries] + [c for c in summaries if c not in meta["cases"]]
                meta["case_summaries"] = [summaries[c] for c in order]
                scores = [s["score"] for s in meta["case_summaries"] if isinstance(s["score"], int | float)]
                meta["mean_score"] = round(sum(scores) / len(scores), 4) if scores else None
                meta["saved_total"] = round(sum(s["saved"] or 0 for s in meta["case_summaries"]), 2)
                meta["running"] = meta["ended_at"] is None or any(
                    s["status"] == "running" for s in meta["case_summaries"])
                out.append(meta)
        out.sort(key=lambda m: (m["started_at"] or m["run_id"]), reverse=True)
        return out

    def find_run_dir(self, run_id: str) -> tuple[Path, str] | None:
        for src in self.active_sources():
            root = src.root.resolve()
            for d in self._run_dirs(src.root):
                if d.name == run_id or self._meta(d, src.name)["run_id"] == run_id:
                    r = d.resolve()
                    if root in r.parents:
                        return r, src.name
        return None

    def case(self, run_id: str, case_id: str) -> dict | None:
        found = self.find_run_dir(run_id)
        if not found:
            return None
        d, source = found
        name = case_id.replace(":", "_", 1)
        if "/" in name or "\\" in name or name.startswith("."):
            return None
        path = (d / f"{name}.jsonl").resolve()
        if path.parent != d or not path.is_file():
            return None
        return {"run": self._meta(d, source), "case_id": case_id, "events": read_events(path)}


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config(sources=[Source("runs", DEFAULT_RUNS)])
    store = Store(config)
    app = FastAPI(title="Hollerau negotiation dashboard", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.store = store

    @app.get("/api/health")
    def health():
        return {"ok": True, "sources": [{"name": s.name, "root": str(s.root)} for s in store.active_sources()]}

    @app.get("/api/version")
    def version():
        return {"version": store.version()}

    @app.get("/api/runs")
    def runs():
        return JSONResponse({"version": store.version(),
                             "sources": [s.name for s in store.active_sources()],
                             "runs": store.runs()}, headers={"Cache-Control": "no-store"})

    @app.get("/api/runs/{run_id}/cases/{case_id}")
    def case(run_id: str, case_id: str):
        data = store.case(run_id, case_id)
        if data is None:
            raise HTTPException(404, f"no case {case_id} in run {run_id}")
        return JSONResponse(data, headers={"Cache-Control": "no-store"})

    dist = config.dist
    if (dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
    else:
        @app.get("/", include_in_schema=False)
        def no_build():
            return JSONResponse({"error": "dashboard/web/dist missing: run `npm run build` in dashboard/web "
                                          "(or ./dashboard/run.sh, which builds it)"}, status_code=503)

    return app


def main(argv=None):
    p = argparse.ArgumentParser(prog="dashboard", description="Negotiation dashboard over runs/ (read-only)")
    p.add_argument("--runs", default=os.environ.get("DASHBOARD_RUNS", str(DEFAULT_RUNS)),
                   help="run log folder (default: <repo>/runs)")
    p.add_argument("--fixtures", action="store_true", help="also show dashboard/fixtures/runs")
    p.add_argument("--fixtures-only", action="store_true", help="show only the fixtures")
    p.add_argument("--no-fallback", action="store_true", help="never fall back to fixtures when runs/ is empty")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("DASHBOARD_PORT", 8787)))
    p.add_argument("--open", action="store_true", help="open the browser")
    a = p.parse_args(argv)

    sources = [] if a.fixtures_only else [Source("runs", Path(a.runs).resolve())]
    if a.fixtures or a.fixtures_only:
        sources.append(Source("fixtures", FIXTURES))
    config = Config(sources=sources, fixtures_fallback=not a.no_fallback)

    import uvicorn

    url = f"http://{a.host}:{a.port}/"
    print(f"Dashboard: {url}  (runs: {', '.join(f'{s.name}={s.root}' for s in sources)})")
    if a.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(config), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
