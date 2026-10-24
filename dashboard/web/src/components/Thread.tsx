import type { ReactNode } from "react";
import { claimText, previousStanding, sentClaims, type RoundData, type Thread } from "../lib/model";
import { eur, eurDelta, termValue, time, duration } from "../lib/format";
import type { Dossier, Priced } from "../lib/types";
import { ClaimBadge, cx, Label, Mono, StatusBadge } from "./ui";

export function sheetSummary(p: Priced): string {
  const t = p.terms ?? {};
  const order = ["unit_price", "payment_days", "effective_date", "contract_months", "incoterm"];
  const keys = [...order.filter((k) => k in t), ...Object.keys(t).filter((k) => !order.includes(k))];
  return keys.map((k) => termValue(k, t[k])).join(" · ");
}

export function SheetChip({
  p,
  selected,
  onClick,
  delta,
  tag,
}: {
  p: Priced;
  selected?: boolean;
  onClick?: () => void;
  delta?: number | null;
  tag?: string;
}) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
      className={cx(
        "group inline-flex items-stretch overflow-hidden rounded-lg border text-left transition-all",
        selected ? "border-ink ring-2 ring-ink/10" : "border-line hover:border-ink-3",
      )}
      title="Show C by term"
    >
      {tag && <span className="flex items-center bg-paper-3 px-2 text-[0.62rem] font-semibold uppercase tracking-wider text-ink-3">{tag}</span>}
      <span className="px-2.5 py-1.5 font-mono text-[0.72rem] tabular-nums text-ink-2">{sheetSummary(p)}</span>
      <span className={cx("flex items-center gap-2 px-2.5 font-mono text-[0.75rem] font-semibold tabular-nums", selected ? "bg-ink text-white" : "bg-paper-2 text-ink")}>
        C {eur(p.c)}
        {typeof delta === "number" && Math.abs(delta) >= 0.5 && (
          <span className={cx("font-medium", delta < 0 ? "text-accent" : selected ? "text-white/60" : "text-ink-3")}>{eurDelta(delta)}</span>
        )}
      </span>
    </button>
  );
}

export function DossierCard({ d, compact = false }: { d?: Dossier; compact?: boolean }) {
  if (!d) return null;
  const p = d.persona ?? {};
  const list = (title: string, xs?: string[]) =>
    xs && xs.length > 0 ? (
      <div>
        <Label className="mb-1">{title}</Label>
        <ul className="space-y-0.5 text-[0.8rem] text-ink-2">
          {xs.map((x, i) => (
            <li key={i} className="flex gap-1.5">
              <span className="text-ink-4">–</span>
              {x}
            </li>
          ))}
        </ul>
      </div>
    ) : null;
  return (
    <div className="rounded-xl border border-line bg-paper-2 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Label>Dossier · {d.supplier_name ?? d.supplier_id}</Label>
        <div className="flex gap-2 text-[0.7rem] text-ink-3">
          {p.owner_type && <span className="rounded-full border border-line bg-white px-2 py-0.5">{p.owner_type}</span>}
          {p.style && <span className="rounded-full border border-line bg-white px-2 py-0.5">{p.style}</span>}
        </div>
      </div>
      {d.summary && <p className="mt-2 text-[0.88rem] leading-relaxed text-ink">{d.summary}</p>}
      {!compact && (
        <>
          <div className="mt-3 grid gap-4 sm:grid-cols-3">
            {list("Pressures", p.pressures)}
            {list("What moves it", p.what_moves_it)}
            {list("Avoid", p.avoid)}
          </div>
          <div className="mt-3 flex flex-wrap items-baseline gap-x-2 border-t border-line pt-3 text-[0.78rem]">
            <span className="text-ink-3">Floor estimate</span>
            <Mono className="font-semibold">{typeof d.floor_estimate === "number" ? `€${d.floor_estimate.toFixed(2)}/unit` : "–"}</Mono>
            {d.floor_source && <span className="text-ink-3">· {d.floor_source}</span>}
          </div>
          {d.facts && d.facts.length > 0 && (
            <div className="mt-2 grid gap-1">
              {d.facts.map((f) => (
                <div key={f.id} className="flex gap-2 text-[0.75rem]">
                  <Mono className="shrink-0 text-ink-3">{f.id}</Mono>
                  <span className="text-ink-2">{f.text}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Mail({
  from,
  to,
  subject,
  body,
  ts,
  ours,
  right,
  children,
}: {
  from: string;
  to?: string;
  subject?: string;
  body?: string;
  ts?: string;
  ours?: boolean;
  right?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className={cx("rounded-xl border bg-white", ours ? "border-ink/80" : "border-line")}>
      <div className={cx("flex items-center justify-between gap-3 border-b px-4 py-2.5", ours ? "border-ink/10 bg-ink text-white" : "border-line-2 bg-paper-2")}>
        <div className="min-w-0 text-[0.75rem]">
          <span className={cx("font-semibold", ours ? "text-white" : "text-ink")}>{from}</span>
          {to && <span className={ours ? "text-white/50" : "text-ink-3"}> → {to}</span>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {right}
          {ts && <Mono className={cx("text-[0.68rem]", ours ? "text-white/50" : "text-ink-4")}>{time(ts)}</Mono>}
        </div>
      </div>
      <div className="px-4 py-3">
        {subject && <div className="mb-1.5 text-[0.85rem] font-semibold text-ink">{subject}</div>}
        {body && <div className="whitespace-pre-wrap text-[0.85rem] leading-relaxed text-ink-2">{body}</div>}
        {children}
      </div>
    </div>
  );
}

export interface Pick {
  priced: Priced;
  label: string;
  round: number;
  sid: string;
}

export function ThreadTimeline({
  t,
  selectedRound,
  picked,
  onSelectRound,
  onPick,
}: {
  t: Thread;
  selectedRound: number | null;
  picked: Pick | null;
  onSelectRound: (r: number) => void;
  onPick: (p: Pick) => void;
}) {
  const open = t.standing.find((s) => s.round === 0);
  return (
    <div className="space-y-5">
      <DossierCard d={t.dossier} />
      {t.opening && (
        <Step label="Open" active={selectedRound === 0} onClick={() => onSelectRound(0)}>
          <Mail from={t.name} to="Hollerau" subject="Opening quote" body={t.opening.body} ts={open?.ts} right={<StatusBadge status="open" />}>
            {t.opening.reasons && t.opening.reasons.length > 0 && (
              <div className="mt-3 rounded-lg bg-paper-2 px-3 py-2 text-[0.78rem] text-ink-2">
                <Label className="mb-1">Supplier's reasons</Label>
                {t.opening.reasons.join(" · ")}
              </div>
            )}
            {t.opening.priced && (
              <div className="mt-3">
                <SheetChip
                  p={t.opening.priced}
                  tag="quote"
                  selected={picked?.priced === t.opening.priced}
                  onClick={() => onPick({ priced: t.opening!.priced!, label: "Opening quote", round: 0, sid: t.sid })}
                />
              </div>
            )}
          </Mail>
        </Step>
      )}
      {t.rounds.map((rd) => (
        <RoundBlock key={rd.round} t={t} rd={rd} active={selectedRound === rd.round} picked={picked} onSelect={() => onSelectRound(rd.round)} onPick={onPick} />
      ))}
      {t.status === "walked_away" || t.status === "no_bid" || t.status === "accepted" ? (
        <div className="pl-14">
          <div className="inline-flex items-center gap-2 text-sm text-ink-3">
            Thread closed {t.closedBy === "us" ? "by us" : "by the supplier"} <StatusBadge status={t.status} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Step({ label, active, onClick, children }: { label: string; active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <div className="group relative grid cursor-pointer grid-cols-[2.75rem_1fr] gap-3" onClick={onClick}>
      <div className="relative flex justify-center">
        <div className="absolute inset-y-0 w-px bg-line" />
        <div
          className={cx(
            "relative z-[1] mt-2 flex h-8 w-8 items-center justify-center rounded-full border font-mono text-[0.7rem] font-semibold transition-colors",
            active ? "border-accent bg-accent text-white" : "border-line bg-white text-ink-2 group-hover:border-ink-3",
          )}
        >
          {label}
        </div>
      </div>
      <div className={cx("min-w-0 space-y-3 rounded-2xl p-1 transition-colors", active && "bg-accent-soft/40")}>{children}</div>
    </div>
  );
}

function RoundBlock({
  t,
  rd,
  active,
  picked,
  onSelect,
  onPick,
}: {
  t: Thread;
  rd: RoundData;
  active: boolean;
  picked: Pick | null;
  onSelect: () => void;
  onPick: (p: Pick) => void;
}) {
  const prev = previousStanding(t, rd.round);
  const dec = rd.decision;
  const msg = rd.message;
  const rp = rd.reply;
  const claimsSent = sentClaims(rd);
  const results = rp?.claim_results ?? [];
  return (
    <Step label={`R${rd.round}`} active={active} onClick={onSelect}>
      {dec && (
        <div className="flex gap-3 rounded-xl border border-dashed border-line px-4 py-2.5">
          <div className="pt-0.5">
            <span
              className={cx(
                "rounded-md px-1.5 py-0.5 text-[0.62rem] font-semibold uppercase tracking-wider",
                dec.kind === "send" ? "bg-paper-3 text-ink-2" : "bg-accent text-white",
              )}
            >
              {dec.kind.replace("_", " ")}
            </span>
          </div>
          <div className="min-w-0 text-[0.82rem] leading-snug text-ink-2">
            <span className="mr-1.5 text-ink-3">Strategist{dec.candidate_id ? ` (${dec.candidate_id})` : ""}:</span>
            {dec.reason || <span className="italic text-ink-4">no reason logged</span>}
            {typeof dec.decided_in_s === "number" && <Mono className="ml-2 text-[0.68rem] text-ink-4">{duration(dec.decided_in_s)}</Mono>}
          </div>
        </div>
      )}
      {msg && (
        <Mail from="Hollerau" to={t.short} subject={msg.subject} body={msg.body} ts={msg.ts} ours>
          {(msg.sheets?.length ?? 0) > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {msg.sheets!.map((s, i) => (
                <SheetChip
                  key={i}
                  p={s}
                  tag={`ask ${i + 1}`}
                  selected={picked?.priced === s}
                  onClick={() => onPick({ priced: s, label: `R${rd.round} · our sheet ${i + 1}`, round: rd.round, sid: t.sid })}
                />
              ))}
            </div>
          )}
          {claimsSent.length > 0 && (
            <div className="mt-3 space-y-1 border-t border-line-2 pt-2.5">
              <Label>Claims</Label>
              {claimsSent.map((c, i) => {
                const r = results.find((x) => x.index === i);
                return (
                  <div key={i} className="flex items-start gap-2 text-[0.78rem]">
                    <span className="w-[6.5rem] shrink-0">{r ? <ClaimBadge result={r.result} /> : <span className="text-ink-4">{rp ? "not read" : "pending"}</span>}</span>
                    <span className="text-ink-2">{c.text}</span>
                  </div>
                );
              })}
            </div>
          )}
          {msg.refs && msg.refs.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {msg.refs.map((r) => (
                <Mono key={r} className="rounded bg-paper-3 px-1.5 py-0.5 text-[0.65rem] text-ink-3">
                  {r}
                </Mono>
              ))}
            </div>
          )}
        </Mail>
      )}
      {rd.errors.map((e, i) => (
        <div key={i} className="rounded-lg border border-accent/40 bg-accent-soft px-4 py-2 text-[0.8rem] text-accent-deep">
          <Mono className="mr-2 font-semibold">{e.status ?? "error"}</Mono>
          {e.detail}
        </div>
      ))}
      {rp && (
        <Mail from={rp.from ?? t.short} to="Hollerau" subject={rp.subject} body={rp.body} ts={rp.ts} right={<StatusBadge status={rp.status} />}>
          {rp.standing?.priced && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <SheetChip
                p={rp.standing.priced}
                tag="standing"
                delta={prev?.c != null && rp.standing.priced.c != null ? rp.standing.priced.c - prev.c : null}
                selected={picked?.priced === rp.standing.priced}
                onClick={() => onPick({ priced: rp.standing!.priced!, label: `R${rd.round} · standing offer`, round: rd.round, sid: t.sid })}
              />
              {rp.standing.offer_id && <Mono className="text-[0.68rem] text-ink-4">{rp.standing.offer_id}</Mono>}
              {rp.alternatives?.map((a, i) =>
                a.priced ? (
                  <SheetChip
                    key={i}
                    p={a.priced}
                    tag={`alt ${i + 1}`}
                    delta={prev?.c != null && a.priced.c != null ? a.priced.c - prev.c : null}
                    selected={picked?.priced === a.priced}
                    onClick={() => onPick({ priced: a.priced!, label: `R${rd.round} · alternative ${i + 1}`, round: rd.round, sid: t.sid })}
                  />
                ) : null,
              )}
            </div>
          )}
          {rp.reasons && rp.reasons.length > 0 && (
            <div className="mt-3 rounded-lg bg-paper-2 px-3 py-2.5">
              <Label className="mb-1">Supplier's reasons (arena trace)</Label>
              <ul className="space-y-0.5 text-[0.78rem] text-ink-2">
                {rp.reasons.map((x, i) => (
                  <li key={i} className="flex gap-1.5">
                    <span className="text-ink-4">–</span>
                    {x}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {results.length > 0 && claimsSent.length === 0 && (
            <div className="mt-3 space-y-1 border-t border-line-2 pt-2.5">
              <Label>Claim results</Label>
              {results.map((r) => (
                <div key={r.index} className="flex items-center gap-2 text-[0.78rem]">
                  <ClaimBadge result={r.result} />
                  <span className="text-ink-2">{claimText(rd, r.index) ?? `Claim #${r.index}`}</span>
                  {r.ref && <Mono className="text-[0.68rem] text-ink-4">{r.ref}</Mono>}
                </div>
              ))}
            </div>
          )}
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[0.7rem] text-ink-3">
            {rp.missing_fields && rp.missing_fields.length > 0 && <span>Missing: {rp.missing_fields.join(", ")}</span>}
            {rp.attachments?.map((a) => (
              <span key={a.attachment_id} className="inline-flex items-center gap-1">
                <span className="rounded bg-paper-3 px-1 font-mono text-[0.6rem] uppercase">{a.type}</span>
                {a.name}
              </span>
            ))}
            {rp.signals && typeof rp.signals.reply_delay_days === "number" && <span>Real reply in {rp.signals.reply_delay_days as number} d</span>}
            {typeof rp.latency_s === "number" && <span>Latency {duration(rp.latency_s)}</span>}
          </div>
        </Mail>
      )}
      {rd.backoffice.length > 0 && (
        <details className="group/bo rounded-xl border border-dashed border-line px-4 py-2.5 text-[0.78rem]">
          <summary className="cursor-pointer list-none text-ink-3 hover:text-ink">
            <span className="mr-1.5 inline-block transition-transform group-open/bo:rotate-90">›</span>
            Supplier back office · {rd.backoffice.length} note{rd.backoffice.length > 1 ? "s" : ""}
          </summary>
          <ul className="mt-2 space-y-1">
            {rd.backoffice.map((n, i) => (
              <li key={i} className="flex gap-2">
                <span className="shrink-0 font-medium text-ink-2">
                  {n.from ?? "?"} → {n.to ?? "?"}
                </span>
                <span className="text-ink-2">{n.text}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Step>
  );
}
