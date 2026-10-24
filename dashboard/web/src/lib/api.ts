import { useEffect, useRef, useState } from "react";
import type { BaseEvent, RunMeta } from "./types";

const POLL_MS = 2500;

async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

/** Polls /api/version; returns a value that changes whenever a run file changes. */
export function useVersion(): string | null {
  const [v, setV] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await getJSON<{ version: string }>("/api/version");
        if (alive) setV(r.version);
      } catch {
        /* server down: keep last */
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  return v;
}

export interface RunsResponse {
  version: string;
  sources: string[];
  runs: RunMeta[];
}

export function useRuns(version: string | null) {
  const [data, setData] = useState<RunsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    getJSON<RunsResponse>("/api/runs")
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [version]);
  return { data, error };
}

export interface CaseResponse {
  run: RunMeta;
  case_id: string;
  events: BaseEvent[];
}

export function useCase(runId: string, caseId: string, version: string | null) {
  const [data, setData] = useState<CaseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = useRef("");
  useEffect(() => {
    let alive = true;
    const k = `${runId}/${caseId}`;
    if (key.current !== k) {
      key.current = k;
      setData(null);
    }
    getJSON<CaseResponse>(`/api/runs/${encodeURIComponent(runId)}/cases/${encodeURIComponent(caseId)}`)
      .then((d) => {
        if (!alive) return;
        // keep identity when nothing changed, so replays don't reset
        setData((old) => (old && old.events.length === d.events.length && old.case_id === d.case_id ? old : d));
        setError(null);
      })
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, [runId, caseId, version]);
  return { data, error };
}
