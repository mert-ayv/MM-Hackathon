import { useEffect, useState } from "react";
import { useCase, useRuns, useVersion } from "./lib/api";
import { useRoute } from "./lib/router";
import { RunsView } from "./views/RunsView";
import { CaseView } from "./views/CaseView";
import { ReplayView } from "./views/ReplayView";
import { cx } from "./components/ui";

function usePresentation(): [boolean, (v: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem("presentation") === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    document.documentElement.classList.toggle("presentation", on);
    try {
      localStorage.setItem("presentation", on ? "1" : "0");
    } catch {
      /* private mode */
    }
  }, [on]);
  return [on, setOn];
}

export function App() {
  const route = useRoute();
  const version = useVersion();
  const runs = useRuns(version);
  const [presentation, setPresentation] = usePresentation();
  const live = runs.data?.runs.some((r) => r.running);

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.key === "p" && !(e.target instanceof HTMLInputElement)) setPresentation(!presentation);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [presentation, setPresentation]);

  return (
    <div className="min-h-screen bg-paper">
      <header className="sticky top-0 z-30 border-b border-line bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1680px] items-center justify-between px-8">
          <a href="#/" className="flex items-center gap-3">
            <span className="relative flex h-7 w-7 items-center justify-center rounded-lg bg-ink">
              <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-accent" />
            </span>
            <span className="text-[0.95rem] font-semibold tracking-tight">Negotiation Desk</span>
            <span className="hidden text-[0.8rem] text-ink-3 sm:inline">Hollerau Pumpenwerke · Tacto Arena</span>
          </a>
          <div className="flex items-center gap-5 text-[0.8rem]">
            <span className="hidden items-center gap-1.5 text-ink-3 md:inline-flex">
              <span className={cx("h-1.5 w-1.5 rounded-full", version ? (live ? "animate-pulsedot bg-accent" : "bg-ink") : "bg-ink-4")} />
              {version ? (live ? "watching · run in progress" : "watching runs/") : "connecting…"}
            </span>
            <button
              onClick={() => setPresentation(!presentation)}
              title="Presentation mode (P)"
              className={cx(
                "rounded-full border px-3 py-1 font-medium transition-colors",
                presentation ? "border-ink bg-ink text-white" : "border-line text-ink-2 hover:border-ink",
              )}
            >
              Presentation
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1680px] px-8 py-8">
        {route.name === "runs" && <RunsView data={runs.data} error={runs.error} />}
        {route.name === "case" && <CaseRoute runId={route.runId} caseId={route.caseId} version={version} />}
        {route.name === "replay" && <ReplayRoute runId={route.runId} caseId={route.caseId} at={route.at} version={version} />}
      </main>
    </div>
  );
}

function CaseRoute({ runId, caseId, version }: { runId: string; caseId: string; version: string | null }) {
  const { data, error } = useCase(runId, caseId, version);
  return <CaseView key={`${runId}/${caseId}`} data={data} error={error} runId={runId} caseId={caseId} />;
}

function ReplayRoute({ runId, caseId, at, version }: { runId: string; caseId: string; at?: number; version: string | null }) {
  // replays a snapshot: later file changes don't restart the playback
  const { data, error } = useCase(runId, caseId, null);
  void version;
  return <ReplayView key={`${runId}/${caseId}`} data={data} error={error} runId={runId} caseId={caseId} at={at} />;
}
