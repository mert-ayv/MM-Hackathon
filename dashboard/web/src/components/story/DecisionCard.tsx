import { useState } from "react";
import type { Thread } from "../../lib/model";
import type { RoundStory } from "../../lib/story";
import { MOVE_ICON, reasonParts, sheetChips, whyLine } from "../../lib/story";
import type { Specialists } from "../../lib/types";
import { eur, eur2, eurDelta, humanize } from "../../lib/format";
import { cx, Label, StatusBadge } from "../ui";
import { IconChip } from "./visuals";

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

const MOOD: Record<RoundStory["mood"], { icon: string; label: string; cls: string }> = {
  moved: { icon: "↓", label: "Moved towards us", cls: "bg-ink text-white" },
  small: { icon: "↘", label: "Small step", cls: "bg-paper-3 text-ink" },
  held: { icon: "■", label: "Held firm", cls: "bg-paper-3 text-ink-2" },
  final: { icon: "!", label: "Final offer", cls: "bg-accent text-white" },
  agreed: { icon: "✓", label: "Agreed", cls: "bg-ink text-white" },
  walked: { icon: "✕", label: "Walked away", cls: "bg-accent text-white" },
  none: { icon: "·", label: "No reply yet", cls: "bg-paper-3 text-ink-3" },
};

const CLAIM_TONE: Record<string, { tone: string; icon: string }> = {
  verified: { tone: "ink", icon: "✓" },
  contradicted: { tone: "bad", icon: "✕" },
  duplicate: { tone: "muted", icon: "↺" },
  irrelevant: { tone: "muted", icon: "∅" },
};

/** One round as a visual decision: our move, our arguments, their reaction. */
export function DecisionCard({ story, thread, flash }: { story: RoundStory; thread: Thread; flash?: boolean }) {
  const [mail, setMail] = useState(false);
  const mood = MOOD[story.mood];
  const ref = thread.standing.filter((s) => s.round < story.round).pop()?.priced?.terms ?? thread.opening?.standard_terms;
  const specialists = thread.rounds.find((r) => r.round === story.round)?.specialists;

  return (
    <div className={cx("rounded-2xl border bg-white shadow-card transition-shadow", flash ? "border-accent ring-4 ring-accent/25" : "border-line")}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-ink text-lg text-white">{MOVE_ICON[story.move]}</span>
          <div>
            <div className="text-[0.7rem] uppercase tracking-[0.14em] text-ink-3">
              Round {story.round} · {thread.short}
            </div>
            <div className="flex flex-wrap items-baseline gap-x-3">
              <span className="text-[1.15rem] font-semibold tracking-tight text-ink">{story.moveLabel}</span>
              <span className="text-[0.85rem] text-ink-2">{whyLine(story)}</span>
            </div>
          </div>
        </div>
        <button onClick={() => setMail(!mail)} className="rounded-full border border-line px-3 py-1 text-[0.75rem] font-medium text-ink-2 hover:border-ink">
          {mail ? "Hide e-mails" : "Read e-mails"}
        </button>
      </div>

      {story.reason && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-accent-soft/60 px-6 py-3">
          <span className="text-[0.66rem] font-semibold uppercase tracking-[0.14em] text-accent-deep">Agent's reasoning</span>
          {reasonParts(story.reason).map((p, i) => (
            <span key={i} title={p} className="inline-flex max-w-[34rem] items-center gap-1.5 rounded-lg border border-accent/30 bg-white px-2.5 py-1 text-[0.76rem] text-ink">
              <span className="font-mono text-[0.66rem] text-accent-deep">{i + 1}</span>
              <span className="truncate">{p}</span>
            </span>
          ))}
        </div>
      )}

      <div className="grid gap-0 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)_minmax(0,1.1fr)]">
        {/* our move: the packages we put on the table */}
        <section className="min-w-0 border-line p-5 lg:border-r">
          <Label className="mb-3">Our offer {story.sheets.length > 1 ? `· ${story.sheets.length} packages` : ""}</Label>
          {story.sheets.length === 0 && <div className="text-sm text-ink-3">No terms in this message.</div>}
          <div className="grid gap-2.5 sm:grid-cols-2 2xl:grid-cols-3">
            {story.sheets.map((p, i) => {
              const picked = story.chosen === i;
              const diff = isNum(p.c) && isNum(story.supplierBefore) ? p.c - story.supplierBefore : null;
              return (
                <div key={i} className={cx("relative rounded-xl border p-3", picked ? "border-accent bg-accent-soft" : "border-line bg-paper-2")}>
                  {picked && <span className="absolute -top-2 right-2 rounded-full bg-accent px-1.5 py-0.5 text-[0.6rem] font-semibold uppercase tracking-wide text-white">they picked</span>}
                  <div className="font-mono text-[1.15rem] font-semibold tabular-nums text-ink">{p.terms?.unit_price !== undefined ? eur2(p.terms.unit_price) : "–"}</div>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {sheetChips(p, ref).map((c) => (
                      <span key={c.k} className={cx("whitespace-nowrap rounded-md px-1.5 py-0.5 text-[0.66rem]", c.changed ? "bg-ink text-white" : "bg-white text-ink-3")}>
                        {c.label} {c.value}
                      </span>
                    ))}
                  </div>
                  {isNum(diff) && (
                    <div className="mt-2 text-[0.68rem] text-ink-3">
                      <span className="font-mono text-ink">{eurDelta(diff)}</span> vs their offer
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {specialists?.outputs && <LeverBars s={specialists} />}
        </section>

        {/* arguments */}
        <section className="min-w-0 border-line p-5 lg:border-r">
          <Label className="mb-3">Arguments</Label>
          {story.claims.length === 0 ? (
            <div className="text-[0.8rem] text-ink-3">No data cited this round.</div>
          ) : (
            <div className="flex flex-col gap-2">
              {story.claims.map((c, i) => {
                const t = CLAIM_TONE[c.result ?? ""] ?? { tone: "muted", icon: "·" };
                return (
                  <div key={i} className="flex items-center justify-between gap-2 rounded-xl border border-line bg-paper-2 px-3 py-2">
                    <div className="min-w-0">
                      <div title={c.label} className="truncate text-[0.82rem] font-medium text-ink first-letter:uppercase">{c.label}</div>
                      {c.value && <div className="truncate font-mono text-[0.7rem] text-ink-3">{c.value}</div>}
                    </div>
                    <IconChip icon={t.icon} label={c.result ?? "not checked"} tone={t.tone} />
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* their reaction */}
        <section className="min-w-0 p-5">
          <Label className="mb-3">Their reaction</Label>
          <div className="flex items-center gap-3">
            <span className={cx("flex h-11 w-11 items-center justify-center rounded-full text-lg font-semibold", mood.cls)}>{mood.icon}</span>
            <div>
              <div className="text-[0.95rem] font-semibold text-ink">{mood.label}</div>
              {isNum(story.supplierStep) && Math.abs(story.supplierStep) > 0.5 && (
                <div className="font-mono text-[0.78rem] tabular-nums text-ink-2">
                  {eurDelta(-story.supplierStep)} {isNum(story.supplierStepPct) && `(${(-story.supplierStepPct * 100).toFixed(1)} %)`}
                </div>
              )}
            </div>
            {story.supplierStatus && (
              <span className="ml-auto">
                <StatusBadge status={story.supplierStatus} />
              </span>
            )}
          </div>
          {isNum(story.supplierAfter) && (
            <div className="mt-3 text-[0.75rem] text-ink-3">
              Now at <span className="font-mono text-ink">{eur(story.supplierAfter)}</span>
            </div>
          )}
          {story.mind.length > 0 && (
            <div className="mt-4">
              <div className="mb-1.5 text-[0.66rem] uppercase tracking-[0.12em] text-ink-4">Supplier's back office</div>
              <div className="flex flex-wrap gap-1.5">
                {story.mind.map((m, i) => (
                  <IconChip key={i} icon="💭" label={`My call: ${m}`} tone={/final|walk/i.test(m) ? "accent" : "muted"} />
                ))}
              </div>
            </div>
          )}
          {cleanQuotes(story.reasons).length > 0 && (
            <div className="mt-4 flex flex-col gap-1.5">
              <div className="text-[0.66rem] uppercase tracking-[0.12em] text-ink-4">What they said</div>
              {cleanQuotes(story.reasons).map((r, i) => (
                <div key={i} title={r} className="line-clamp-2 rounded-lg bg-paper-2 px-2.5 py-1.5 text-[0.75rem] text-ink-2">
                  “{r}”
                </div>
              ))}
            </div>
          )}
          {story.alternatives.length > 0 && (
            <div className="mt-3 text-[0.72rem] text-ink-3">
              + {story.alternatives.length} alternative package{story.alternatives.length > 1 ? "s" : ""} (best {eur(Math.min(...story.alternatives.map((a) => a.c ?? Infinity)))})
            </div>
          )}
        </section>
      </div>

      {mail && (
        <div className="grid gap-4 border-t border-line bg-paper-2 p-5 md:grid-cols-2">
          <Mail who="Our e-mail" body={story.emailOut} />
          <Mail who={thread.short} body={story.emailIn} />
        </div>
      )}
    </div>
  );
}

function Mail({ who, body }: { who: string; body?: string }) {
  return (
    <div className="rounded-xl border border-line bg-white p-4">
      <Label className="mb-2">{who}</Label>
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap font-sans text-[0.8rem] leading-relaxed text-ink-2">{body ?? "–"}</pre>
    </div>
  );
}

/** Specialists' levers: € the lever is worth to us vs to the supplier. */
function LeverBars({ s }: { s: Specialists }) {
  const rows = Object.entries(s.outputs ?? {}).filter(([, o]) => isNum(o?.value_for_us_eur) || isNum(o?.value_for_supplier_eur));
  if (!rows.length) return null;
  const max = Math.max(1, ...rows.flatMap(([, o]) => [Math.abs(o.value_for_us_eur ?? 0), Math.abs(o.value_for_supplier_eur ?? 0)]));
  return (
    <div className="mt-4">
      <div className="mb-1.5 flex justify-between text-[0.66rem] uppercase tracking-[0.12em] text-ink-4">
        <span>Levers</span>
        <span>
          <span className="text-accent-deep">for us</span> · for them
        </span>
      </div>
      {rows.map(([k, o]) => (
        <div key={k} className="grid grid-cols-[72px_1fr_1fr] items-center gap-2 py-0.5 text-[0.7rem]">
          <span className="truncate capitalize text-ink-2">{humanize(o.lever ?? k)}</span>
          <div className="flex justify-end">
            <div className="h-2 rounded-l-full bg-accent" style={{ width: `${(Math.abs(o.value_for_us_eur ?? 0) / max) * 100}%` }} />
          </div>
          <div className="h-2 rounded-r-full bg-ink" style={{ width: `${(Math.abs(o.value_for_supplier_eur ?? 0) / max) * 100}%` }} />
        </div>
      ))}
    </div>
  );
}

/** Whole first sentences only; drops template text with gaps ("€... per unit"). */
function cleanQuotes(reasons: string[]): string[] {
  return reasons
    .filter((r) => !/(\.\.\.|…)/.test(r))
    .map((r) => r.match(/^.*?[.!?](?=\s|$)/)?.[0] ?? r)
    .slice(0, 3);
}
