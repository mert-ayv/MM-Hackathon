import { useEffect, useState } from "react";
import { useCase, useRuns, useVersion } from "./lib/api";
import { useRoute, type Route } from "./lib/router";
import { useStudio } from "./lib/studio";
import { RunsView } from "./views/RunsView";
import { CaseView } from "./views/CaseView";
import { ReplayView } from "./views/ReplayView";
import { StudioView } from "./views/StudioView";
import { NegotiationsView } from "./views/NegotiationsView";
import { NegotiationView } from "./views/NegotiationView";
import { VoiceDock } from "./components/voice/VoiceDock";
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

const TABS: { label: string; href: string; match: Route["name"][] }[] = [
  { label: "Agent Studio", href: "#/studio", match: ["studio"] },
  { label: "Negotiations", href: "#/n", match: ["negotiations", "negotiation"] },
  { label: "Debug", href: "#/runs", match: ["runs", "case", "replay"] },
];

export function App() {
  const route = useRoute();
  const version = useVersion();
  const runs = useRuns(version);
  const { suggestions } = useStudio();
  const [presentation, setPresentation] = usePresentation();
  const live = runs.data?.runs.some((r) => r.running);
  const pending = suggestions.filter((s) => s.status === "pending").length;
  const wide = route.name === "studio";

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const t = e.target;
      if (t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement) return;
      if (e.key === "p") setPresentation(!presentation);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [presentation, setPresentation]);

  return (
    <div className="min-h-screen bg-paper">
      <header className="sticky top-0 z-30 border-b border-line bg-white/90 backdrop-blur">
        <div className={cx("mx-auto flex h-14 items-center justify-between gap-6 px-8", !wide && "max-w-[1680px]")}>
          <div className="flex items-center gap-8">
            <a href="#/studio" className="flex items-center gap-3">
              <span className="relative flex h-7 w-7 items-center justify-center rounded-lg bg-ink">
                <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-accent" />
              </span>
              <span className="text-[0.95rem] font-semibold tracking-tight">Negotiation Copilot</span>
              <span className="hidden text-[0.8rem] text-ink-3 lg:inline">Hollerau Pumpenwerke</span>
            </a>
            <nav className="flex items-center gap-1 rounded-full border border-line bg-paper-2 p-1 text-[0.8rem]">
              {TABS.map((t) => {
                const on = t.match.includes(route.name);
                return (
                  <a
                    key={t.href}
                    href={t.href}
                    className={cx(
                      "relative rounded-full px-3.5 py-1 font-medium transition-colors",
                      on ? "bg-ink text-white" : "text-ink-2 hover:text-ink",
                    )}
                  >
                    {t.label}
                    {t.label === "Agent Studio" && pending > 0 && (
                      <span className="ml-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[0.62rem] font-semibold text-white">
                        {pending}
                      </span>
                    )}
                  </a>
                );
              })}
            </nav>
          </div>
          <div className="flex items-center gap-5 text-[0.8rem]">
            <span className="hidden items-center gap-1.5 text-ink-3 md:inline-flex">
              <span className={cx("h-1.5 w-1.5 rounded-full", version ? (live ? "animate-pulsedot bg-accent" : "bg-ink") : "bg-ink-4")} />
              {version ? (live ? "negotiating now" : "agent online") : "connecting…"}
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
      {route.name === "studio" ? (
        <StudioView nodeId={route.nodeId} />
      ) : (
        <main className="mx-auto max-w-[1680px] px-8 py-8">
          {route.name === "negotiations" && <NegotiationsView version={version} />}
          {route.name === "negotiation" && (
            <NegotiationView runId={route.runId} caseId={route.caseId} round={route.round} version={version} />
          )}
          {route.name === "runs" && <RunsView data={runs.data} error={runs.error} />}
          {route.name === "case" && <CaseRoute runId={route.runId} caseId={route.caseId} version={version} />}
          {route.name === "replay" && <ReplayRoute runId={route.runId} caseId={route.caseId} at={route.at} version={version} />}
        </main>
      )}
      <VoiceDock />
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
