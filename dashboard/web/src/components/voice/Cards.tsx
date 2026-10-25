// Visual answers in the copilot's transcript: each tool result becomes a small card, so the manager sees
// the numbers the voice talks about. All figures come straight from the tool (lib/voice), none are computed here.
import { cx } from "../ui";
import { onShow, type Bar, type Card, type TermDelta } from "../../lib/voice";

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const eur = (n: number) => `€${Math.round(n).toLocaleString("en-US")}`;
const eurK = (n: number) => (Math.abs(n) >= 100_000 ? `€${(n / 1_000_000).toFixed(2)}M` : Math.abs(n) >= 1000 ? `€${(n / 1000).toFixed(1)}k` : `€${Math.round(n)}`);
const signed = (n: number) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${eurK(Math.abs(n))}`;
const pct = (x: number | null) => (x === null ? "–" : `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)} %`);

const TONE: Record<Bar["tone"], string> = { deal: "bg-accent", better: "bg-ink", worse: "bg-ink-4", neutral: "bg-slate" };

function Shell({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cx("animate-rise rounded-xl border border-line bg-white p-3.5 shadow-card", className)}>
      <div className="mb-2 text-[0.62rem] font-medium uppercase tracking-[0.12em] text-ink-3">{label}</div>
      {children}
    </div>
  );
}

/** Cost bars on a cut axis: the differences matter, not the absolute millions. */
function Bars({ bars }: { bars: Bar[] }) {
  if (!bars.length) return null;
  const max = Math.max(...bars.map((b) => b.eur));
  const min = Math.min(...bars.map((b) => b.eur));
  const lo = min - (max - min) * 0.6 || min * 0.98;
  return (
    <div className="space-y-1.5">
      {bars.map((b) => (
        <div key={b.label} className="grid grid-cols-[7.5rem_1fr_4.2rem] items-center gap-2 text-[0.72rem]">
          <span className={cx("truncate", b.tone === "deal" ? "font-semibold text-ink" : "text-ink-2")}>{b.label}</span>
          <span className="h-2.5 overflow-hidden rounded-full bg-paper-3">
            <span className={cx("block h-full rounded-full transition-all duration-700", TONE[b.tone])} style={{ width: `${Math.max(4, ((b.eur - lo) / (max - lo || 1)) * 100)}%` }} />
          </span>
          <span className="text-right font-mono text-[0.68rem] text-ink-2">{eurK(b.eur)}</span>
        </div>
      ))}
    </div>
  );
}

function Terms({ terms, hint }: { terms: TermDelta[]; hint?: string }) {
  if (!terms.length) return null;
  return (
    <div className="mt-2.5">
      {hint && <div className="mb-1 text-[0.65rem] text-ink-3">{hint}</div>}
      <div className="flex flex-wrap gap-1">
        {terms.map((t) => (
          <span key={t.term} className={cx("rounded-md border px-1.5 py-0.5 font-mono text-[0.66rem]", t.eur > 0 ? "border-accent/30 bg-accent-soft text-accent-deep" : "border-line bg-paper-2 text-ink-2")}>
            {t.term} {signed(t.eur)}
          </span>
        ))}
      </div>
    </div>
  );
}

const CLAIM: Record<string, string> = {
  verified: "border-ink bg-ink text-white",
  contradicted: "border-accent bg-accent text-white",
};

export function CopilotCard({ card }: { card: Card }) {
  switch (card.kind) {
    case "verdict":
      return (
        <Shell label={`Outcome · ${card.supplier} · ${card.rounds} rounds`}>
          {card.saved !== null ? (
            <div className="flex items-baseline gap-2">
              <span className="text-[1.35rem] font-semibold tracking-tight text-accent">{eur(card.saved)}</span>
              <span className="text-[0.72rem] text-ink-3">saved vs their opening</span>
            </div>
          ) : (
            <div className="text-[0.95rem] font-semibold">{card.deal ? "Deal" : "No deal"}</div>
          )}
          {card.askPct !== null && card.dealPct !== null && card.askPct > 0 && (
            <div className="mb-2.5 mt-0.5 text-[0.75rem] text-ink-2">
              asked <span className="text-ink-3 line-through">{pct(card.askPct)}</span> → settled <span className="font-semibold text-ink">{pct(card.dealPct)}</span>
            </div>
          )}
          {isNum(card.vsAlt) && card.vsAlt > 0 && (
            <div className="mb-2.5 flex flex-wrap gap-1">
              <span className="rounded-full border border-line bg-paper-2 px-2 py-0.5 text-[0.68rem] text-ink-2">
                <span className="font-semibold text-ink">{eurK(card.vsAlt)}</span> better than our alternative
              </span>
            </div>
          )}
          <Bars bars={card.bars} />
        </Shell>
      );
    case "money":
      return (
        <Shell label="Money left on the table" className="border-accent/40">
          <div className="mb-2.5 text-[1.05rem] font-semibold tracking-tight text-ink">{card.headline}</div>
          <Bars bars={card.bars} />
          <Terms terms={card.terms} hint="Where the gap sits (our deal vs the cheaper sheet)" />
          {card.findings.length > 0 && (
            <ul className="mt-2.5 space-y-1">
              {card.findings.map((f) => (
                <li key={f} className="flex gap-2 text-[0.72rem] leading-snug text-ink-2">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                  {f}
                </li>
              ))}
            </ul>
          )}
        </Shell>
      );
    case "round":
      return (
        <Shell label={`Round ${card.round} · ${card.supplier}${card.status ? ` · ${card.status.replace(/_/g, " ")}` : ""}`}>
          <div className="grid grid-cols-2 gap-2">
            <Move who="We gave" move={card.ourMove} total={card.ourEur} hot={card.ourMove !== null && card.theirMove !== null && card.ourMove > Math.max(card.theirMove, 0) * 1.5} />
            <Move who="They gave" move={card.theirMove} total={card.theirEur} />
          </div>
          {card.claims.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {card.claims.map((c, i) => (
                <span key={i} className={cx("rounded-full border px-2 py-0.5 text-[0.64rem]", CLAIM[c.result] ?? "border-line bg-paper-2 text-ink-3")}>
                  {c.result === "verified" ? "✓ " : c.result === "contradicted" ? "✕ " : ""}
                  {c.text}
                </span>
              ))}
            </div>
          )}
          {card.quote && <div className="mt-2 border-l-2 border-accent/50 pl-2 text-[0.7rem] italic leading-snug text-ink-2">“{card.quote}”</div>}
          <button onClick={() => onShow(card.round)} className="mt-2 text-[0.68rem] font-medium text-accent-deep hover:underline">
            Show on screen →
          </button>
        </Shell>
      );
    case "breakdown": {
      const max = Math.max(1, ...card.terms.map((t) => Math.abs(t.eur)));
      return (
        <Shell label={card.what}>
          <div className="space-y-1">
            {card.terms.map((t) => (
              <div key={t.term} className="grid grid-cols-[6.5rem_1fr_3.8rem] items-center gap-2 text-[0.7rem]">
                <span className="truncate text-ink-2">{t.term}</span>
                <span className="h-2 rounded-full bg-paper-3">
                  <span className={cx("block h-full rounded-full", t.eur > 0 ? "bg-ink-2" : "bg-accent")} style={{ width: `${(Math.abs(t.eur) / max) * 100}%` }} />
                </span>
                <span className="text-right font-mono text-[0.66rem]">{signed(t.eur)}</span>
              </div>
            ))}
          </div>
          {card.total !== null && <div className="mt-2 text-right font-mono text-[0.66rem] text-ink-3">total {eur(card.total)}</div>}
        </Shell>
      );
    }
    case "supplier":
      return (
        <Shell label="Supplier file">
          <div className="text-[0.85rem] font-semibold leading-tight">{card.name}</div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {card.chips.map((c) => (
              <span key={c} className={cx("rounded-full border px-2 py-0.5 text-[0.64rem]", /pressure/.test(c) ? "border-accent/40 bg-accent-soft text-accent-deep" : "border-line text-ink-2")}>
                {c}
              </span>
            ))}
          </div>
          <div className="mt-2 grid grid-cols-2 gap-1.5">
            {card.facts.map((f) => (
              <div key={f.label} className="rounded-lg bg-paper-2 px-2 py-1">
                <div className="text-[0.6rem] uppercase tracking-wider text-ink-3">{f.label}</div>
                <div className="font-mono text-[0.72rem]">{f.value}</div>
              </div>
            ))}
          </div>
        </Shell>
      );
    case "history":
      return <History card={card} />;
    case "proposal":
      return (
        <Shell label={`Proposed change · ${card.node}`} className="border-accent/40">
          <div className="mb-2 text-[0.85rem] font-semibold leading-tight">{card.title}</div>
          <div className="overflow-hidden rounded-lg border border-line font-mono text-[0.68rem]">
            {card.before && <div className="bg-[#FDECEC] px-2 py-1 text-[#9F1D1D]">− {card.before}</div>}
            <div className="bg-[#E9F7EE] px-2 py-1 text-[#17663A]">+ {card.after}</div>
          </div>
          <div className="mt-2 flex items-center justify-between text-[0.66rem]">
            <span className="text-ink-3">{card.evidence}</span>
            <a href="#/studio" className="font-medium text-accent-deep hover:underline">
              Review in Agent Studio →
            </a>
          </div>
        </Shell>
      );
  }
}

function Move({ who, move, total, hot }: { who: string; move: number | null; total: number | null; hot?: boolean }) {
  return (
    <div className={cx("rounded-lg px-2.5 py-1.5", hot ? "bg-accent-soft" : "bg-paper-2")}>
      <div className="text-[0.6rem] uppercase tracking-wider text-ink-3">{who}</div>
      <div className={cx("font-mono text-[0.9rem] font-semibold", hot ? "text-accent-deep" : "text-ink")}>{move === null ? "–" : signed(move).replace("+", "")}</div>
      {total !== null && <div className="font-mono text-[0.6rem] text-ink-3">at {eurK(total)}</div>}
    </div>
  );
}

/** Settled price change per past negotiation with this supplier, this case highlighted. */
function History({ card }: { card: Extract<Card, { kind: "history" }> }) {
  const pts = [...card.rows.map((r) => r.settled ?? 0), card.thisCase?.settled ?? 0, ...card.catSettled];
  const max = Math.max(1, ...pts.map(Math.abs));
  const catAvg = card.catSettled.length ? card.catSettled.reduce((a, b) => a + b, 0) / card.catSettled.length : null;
  const bar = (v: number | null, key: string, label: string, hot?: boolean) => (
    <div key={key} className="flex flex-1 flex-col items-center gap-1">
      <div className="relative flex h-16 w-full items-center justify-center">
        <span className="absolute left-0 right-0 top-1/2 border-t border-dashed border-line" />
        {v !== null && (
          <span
            className={cx("absolute w-3/5 rounded-sm", hot ? "bg-accent" : "bg-ink-3")}
            style={v >= 0 ? { bottom: "50%", height: `${(Math.abs(v) / max) * 50}%` } : { top: "50%", height: `${(Math.abs(v) / max) * 50}%` }}
          />
        )}
      </div>
      <span className={cx("font-mono text-[0.6rem]", hot ? "font-semibold text-accent-deep" : "text-ink-2")}>{v === null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`}</span>
      <span className="text-center text-[0.56rem] leading-tight text-ink-3">{label}</span>
    </div>
  );
  return (
    <Shell label={`Comparable deals · ${card.supplier}`}>
      <div className="flex items-end gap-1">
        {card.rows.map((r, i) => bar(r.settled, `r${i}`, r.date.slice(0, 7)))}
        {card.thisCase && bar(card.thisCase.settled, "this", "this deal", true)}
      </div>
      <div className="mt-1.5 text-[0.66rem] text-ink-3">
        Settled price change with this supplier
        {catAvg !== null && card.category ? ` · ${card.category} average with others: ${catAvg > 0 ? "+" : ""}${catAvg.toFixed(1)} %` : ""}
      </div>
    </Shell>
  );
}
