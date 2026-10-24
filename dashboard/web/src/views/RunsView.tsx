import { useEffect, useMemo, useState } from "react";
import type { RunsResponse } from "../lib/api";
import { eur, eurShort, dateTime, score as fmtScore } from "../lib/format";
import { href } from "../lib/router";
import type { CaseSummary, RunMeta } from "../lib/types";
import { Card, cx, Empty, Label, Mono, StatusBadge } from "../components/ui";

export function RunsView({ data, error }: { data: RunsResponse | null; error: string | null }) {
  const all = data?.runs ?? [];
  const [setF, setSetF] = useState<string>("all");
  const [authorF, setAuthorF] = useState<string>("all");
  const sets = useMemo(() => [...new Set(all.map((r) => r.set ?? "–"))].sort(), [all]);
  const authors = useMemo(() => [...new Set(all.map((r) => r.author ?? (r.source === "imported" ? "unknown" : "local")))].sort(), [all]);
  const runs = useMemo(
    () =>
      all.filter(
        (r) => (setF === "all" || (r.set ?? "–") === setF) && (authorF === "all" || (r.author ?? (r.source === "imported" ? "unknown" : "local")) === authorF),
      ),
    [all, setF, authorF],
  );
  const [chosen, setChosen] = useState<string[] | null>(null);
  const [baseline, setBaseline] = useState<string | null>(null);

  // default: the 4 latest runs; new runs that appear get added automatically
  const [known, setKnown] = useState<string[]>([]);
  useEffect(() => {
    const ids = all.map((r) => r.run_id);
    const fresh = ids.filter((id) => !known.includes(id));
    if (fresh.length) {
      setKnown(ids);
      setChosen((c) => (c === null ? ids.slice(0, 4) : [...fresh, ...c]));
    }
  }, [all, known]);

  const selected = useMemo(
    () => runs.filter((r) => (chosen ?? []).includes(r.run_id)).sort((a, b) => (a.started_at ?? "").localeCompare(b.started_at ?? "")),
    [runs, chosen],
  );
  // default baseline: the run before the newest selected one (new vs previous)
  const base = selected.find((r) => r.run_id === baseline) ?? selected[Math.max(0, selected.length - 2)];
  const caseIds = useMemo(() => {
    const ids: string[] = [];
    for (const r of selected) for (const c of r.case_summaries) if (!ids.includes(c.case_id)) ids.push(c.case_id);
    // repeats of a case ("case:D01~2") sort right after it
    return ids.sort();
  }, [selected]);

  if (error && !data) return <Empty>Can't reach the dashboard server: {error}</Empty>;
  if (!data) return <div className="py-20 text-center text-ink-3">Loading runs…</div>;
  if (!all.length) return <Empty>No runs yet. Runs appear here as soon as the agent writes to <Mono>runs/</Mono>.</Empty>;

  const toggle = (id: string) => setChosen((c) => ((c ?? []).includes(id) ? (c ?? []).filter((x) => x !== id) : [...(c ?? []), id]));

  return (
    <div className="space-y-10">
      <section>
        <div className="mb-4 flex items-end justify-between">
          <div>
            <h1 className="text-[1.75rem] font-semibold tracking-tight">Runs</h1>
            <p className="mt-1 text-sm text-ink-3">Pick the runs to compare. Regressions are measured against the baseline (default: the run before the newest).</p>
          </div>
          {data.sources.includes("fixtures") && (
            <span className="rounded-full border border-dashed border-ink-4 px-3 py-1 text-xs text-ink-3">Showing fixture runs</span>
          )}
        </div>
        {(sets.length > 1 || authors.length > 1) && (
          <div className="mb-4 flex flex-wrap items-center gap-5 text-xs">
            {sets.length > 1 && (
              <Filter label="Set" value={setF} options={["all", ...sets]} onChange={setSetF} />
            )}
            {authors.length > 1 && (
              <Filter label="Author" value={authorF} options={["all", ...authors]} onChange={setAuthorF} />
            )}
            <button className="text-ink-3 underline decoration-line underline-offset-2 hover:text-ink" onClick={() => setChosen(runs.slice(0, 4).map((r) => r.run_id))}>
              Compare the 4 latest shown
            </button>
          </div>
        )}
        <div className="grid grid-cols-[repeat(auto-fill,minmax(17rem,1fr))] gap-3">
          {runs.map((r) => (
            <RunCard key={r.run_id} r={r} on={(chosen ?? []).includes(r.run_id)} isBase={base?.run_id === r.run_id} onToggle={() => toggle(r.run_id)} onBase={() => setBaseline(r.run_id)} />
          ))}
        </div>
      </section>

      <section>
        <div className="mb-4 flex items-end justify-between">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Comparison</h2>
            <p className="mt-1 text-sm text-ink-3">Cases × runs. Click a cell to open the case.</p>
          </div>
          <div className="flex items-center gap-4 text-xs text-ink-3">
            <span className="inline-flex items-center gap-1.5"><span className="text-accent">▼</span> regression vs baseline</span>
            <span className="inline-flex items-center gap-1.5"><span className="text-ink">▲</span> improvement</span>
          </div>
        </div>
        {selected.length === 0 ? (
          <Empty>Select at least one run above.</Empty>
        ) : (
          <Card className="overflow-x-auto">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-line">
                  <th className="sticky left-0 z-[1] min-w-[16rem] bg-paper px-5 py-3 align-bottom"><Label>Case</Label></th>
                  {selected.map((r) => (
                    <th key={r.run_id} className="min-w-[13.5rem] px-4 py-3 align-bottom">
                      <div className="flex items-center gap-2">
                        <AgentMark agent={r.variant ?? r.agent} />
                        <div>
                          <Mono className="block text-[0.72rem] font-medium text-ink">{r.author ? `${r.author} · ${r.agent_name && r.agent_name !== "base" ? r.agent_name + "." : ""}${r.variant}` : r.run_id}</Mono>
                          <span className="text-[0.68rem] text-ink-3">
                            {r.agent_version ?? "–"} · {r.set ?? "–"} · {dateTime(r.started_at)}
                            {base?.run_id === r.run_id && <span className="ml-1.5 font-semibold text-ink">baseline</span>}
                          </span>
                        </div>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {caseIds.map((cid) => {
                  const title = selected.map((r) => r.case_summaries.find((c) => c.case_id === cid)?.title).find(Boolean);
                  const [realId, rep] = cid.split("~");
                  const type = selected.map((r) => r.case_summaries.find((c) => c.case_id === cid)?.type).find(Boolean);
                  const b = base?.case_summaries.find((c) => c.case_id === cid);
                  return (
                    <tr key={cid} className="border-b border-line-2 last:border-0">
                      <td className="sticky left-0 z-[1] bg-paper px-5 py-4 align-top">
                        <Mono className="text-[0.75rem] font-semibold text-ink">{realId}</Mono>
                        {rep && <span className="ml-2 rounded-full bg-paper-3 px-1.5 py-0.5 text-[0.65rem] text-ink-3">play {rep}</span>}
                        <div className="mt-0.5 text-[0.82rem] leading-snug text-ink-2">{title ?? "–"}</div>
                        {type && <div className="mt-1 text-[0.68rem] uppercase tracking-wider text-ink-4">{type.replace("_", " ")}</div>}
                      </td>
                      {selected.map((r) => {
                        const c = r.case_summaries.find((x) => x.case_id === cid);
                        return (
                          <td key={r.run_id} className="px-2 py-2 align-top">
                            {c ? <Cell r={r} c={c} base={r.run_id === base?.run_id ? undefined : b} /> : <div className="px-2 py-3 text-sm text-ink-4">not played</div>}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
                <tr className="bg-paper-2">
                  <td className="sticky left-0 z-[1] bg-paper-2 px-5 py-3"><Label>Mean score · € saved</Label></td>
                  {selected.map((r) => (
                    <td key={r.run_id} className="px-4 py-3">
                      <Mono className="text-lg font-semibold">{r.mean_score === null ? "–" : (r.mean_score * 100).toFixed(1)}</Mono>
                      <Mono className="ml-2 text-xs text-ink-3">{eurShort(r.saved_total)}</Mono>
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </Card>
        )}
      </section>
    </div>
  );
}

export function AgentMark({ agent, size = "md" }: { agent: string | null; size?: "md" | "lg" }) {
  const a = (agent ?? "?").slice(0, 5);
  const accent = a === "A" || a === "base";
  return (
    <span
      className={cx(
        "inline-flex shrink-0 items-center justify-center rounded-lg font-mono font-semibold",
        size === "lg" ? "h-10 min-w-10 px-2 text-base" : "h-8 min-w-8 px-1.5 text-[0.75rem]",
        accent ? "bg-accent text-white" : a === "C" ? "bg-ink text-white" : "border border-line bg-paper-3 text-ink-2",
      )}
    >
      {a}
    </span>
  );
}

function RunCard({ r, on, isBase, onToggle, onBase }: { r: RunMeta; on: boolean; isBase: boolean; onToggle: () => void; onBase: () => void }) {
  const ended = r.case_summaries.filter((c) => c.status === "ended").length;
  return (
    <Card className={cx("cursor-pointer p-4 transition-all", on ? "border-ink ring-1 ring-ink" : "opacity-70 hover:opacity-100")} onClick={onToggle}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <AgentMark agent={r.variant ?? r.agent} />
          <div>
            <Mono className="block text-[0.78rem] font-medium">
              {r.author ? `${r.author} · ${r.agent_name && r.agent_name !== "base" ? r.agent_name + "." : ""}${r.variant}` : r.run_id}
            </Mono>
            <div className="text-[0.7rem] text-ink-3">
              {dateTime(r.started_at)} · {r.set ?? "–"} · <Mono>{r.agent_version ?? "–"}</Mono>
            </div>
          </div>
        </div>
        <span className={cx("mt-1 flex h-4 w-4 items-center justify-center rounded border text-[0.6rem]", on ? "border-ink bg-ink text-white" : "border-ink-4")}>{on ? "✓" : ""}</span>
      </div>
      <div className="mt-4 flex items-end justify-between">
        <div>
          <Label>Mean score</Label>
          <Mono className="text-[1.6rem] font-semibold leading-tight">{r.mean_score === null ? "–" : (r.mean_score * 100).toFixed(1)}</Mono>
        </div>
        <div className="text-right text-[0.72rem] text-ink-3">
          <div>
            <Mono className="text-ink">{ended}</Mono>/{r.case_summaries.length} cases ended
          </div>
          <div>
            saved <Mono className="text-ink">{eur(r.saved_total)}</Mono>
          </div>
          {r.running && (
            <div className="mt-0.5 inline-flex items-center gap-1 text-accent-deep">
              <span className="h-1.5 w-1.5 animate-pulsedot rounded-full bg-accent" /> running
            </div>
          )}
        </div>
      </div>
      {r.notes && <p className="mt-3 line-clamp-2 text-[0.75rem] text-ink-3">{r.notes}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-3">
      {r.source === "imported" && (
        <span className="inline-block rounded-full border border-dashed border-ink-4 px-2 py-0.5 text-[0.62rem] uppercase tracking-wider text-ink-3">
          imported · arena
        </span>
      )}
      {on && !isBase && (
        <button
          className="text-[0.7rem] text-ink-3 underline decoration-line underline-offset-2 hover:text-ink"
          onClick={(e) => {
            e.stopPropagation();
            onBase();
          }}
        >
          Use as baseline
        </button>
      )}
      </div>
    </Card>
  );
}

function Cell({ r, c, base }: { r: RunMeta; c: CaseSummary; base?: CaseSummary }) {
  const d = base && c.score !== null && base.score !== null ? c.score - base.score : null;
  const reg = d !== null && d < -0.02;
  const imp = d !== null && d > 0.02;
  return (
    <a
      href={href({ name: "case", runId: r.run_id, caseId: c.case_id })}
      className={cx("block rounded-lg border px-3 py-2.5 transition-colors hover:border-ink-3 hover:bg-paper-2", reg ? "border-accent/50 bg-accent-soft/40" : "border-transparent")}
    >
      <div className="flex items-baseline justify-between gap-2">
        <Mono className="text-[1.35rem] font-semibold leading-none">{c.status === "running" ? "…" : fmtScore(c.score)}</Mono>
        {d !== null && (reg || imp) && (
          <Mono className={cx("text-[0.75rem] font-semibold", reg ? "text-accent-deep" : "text-ink")}>
            {reg ? "▼" : "▲"} {Math.abs(d).toFixed(2)}
          </Mono>
        )}
      </div>
      <div className="mt-1.5 h-1 rounded-full bg-paper-3">
        <div className={cx("h-full rounded-full", c.deal ? "bg-ink" : "bg-ink-4")} style={{ width: `${Math.max(0, Math.min(1, c.score ?? 0)) * 100}%` }} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.7rem] text-ink-3">
        {c.status === "running" ? (
          <span className="inline-flex items-center gap-1 text-accent-deep">
            <span className="h-1.5 w-1.5 animate-pulsedot rounded-full bg-accent" /> live
          </span>
        ) : c.deal ? (
          <StatusBadge status="accepted" />
        ) : (
          <span className="rounded-full border border-line px-2 py-0.5 font-medium text-ink-2">No deal</span>
        )}
        <span>{c.rounds} rd</span>
        {c.saved !== null && <Mono className="text-ink-2">{eurShort(c.saved)} saved</Mono>}
      </div>
      <div className="mt-1 truncate text-[0.68rem] text-ink-4">
        {c.end_reason ?? ""}
        {c.supplier_name ? ` · ${c.supplier_name}` : ""}
        {c.errors ? ` · ${c.errors} error${c.errors > 1 ? "s" : ""}` : ""}
      </div>
    </a>
  );
}

function Filter({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <div className="flex items-center gap-2">
      <span className="uppercase tracking-[0.12em] text-ink-3">{label}</span>
      <div className="flex flex-wrap gap-1">
        {options.map((o) => (
          <button
            key={o}
            onClick={() => onChange(o)}
            className={cx("rounded-full border px-2.5 py-0.5 transition-colors", value === o ? "border-ink bg-ink text-white" : "border-line text-ink-2 hover:border-ink-3")}
          >
            {o}
          </button>
        ))}
      </div>
    </div>
  );
}
