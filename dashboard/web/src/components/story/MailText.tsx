import type { ReactNode } from "react";
import type { Terms } from "../../lib/types";
import { eur2, termLabel, termValue } from "../../lib/format";
import { cx } from "../ui";

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

const MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];

// money (EUR 133.11 / €140.00), ISO dates, "1 April 2027", "90 days" (not "51 days' notice")
const TOKEN =
  /(?:EUR|€)\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)|\b(\d{4}-\d{2}-\d{2})\b|\b(\d{1,2}) (January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})\b|(?<!valid (?:for|within) )\b(\d+)\s?(?:days|day)\b(?!['’]?\s*notice)/g;

interface Hit {
  start: number;
  end: number;
  key: string;
  value: number | string;
}

/** Offer terms in an e-mail that match the logged term sheets (so only what was really offered lights up). */
function hits(body: string, sheets: Terms[]): Hit[] {
  const prices = sheets.map((t) => t.unit_price).filter(isNum);
  const dates = new Set(sheets.map((t) => t.effective_date).filter((d): d is string => typeof d === "string"));
  const pay = new Set(sheets.map((t) => t.payment_days).filter(isNum));
  const lead = new Set(sheets.map((t) => t.lead_time_days).filter(isNum));
  const out: Hit[] = [];
  for (const m of body.matchAll(TOKEN)) {
    const start = m.index ?? 0;
    const end = start + m[0].length;
    if (m[1]) {
      const n = Number(m[1].replace(/,/g, ""));
      if (prices.some((p) => Math.abs(p - n) < 0.005)) out.push({ start, end, key: "unit_price", value: n });
    } else if (m[2]) {
      if (dates.has(m[2])) out.push({ start, end, key: "effective_date", value: m[2] });
    } else if (m[3]) {
      const iso = `${m[5]}-${String(MONTHS.indexOf(m[4].toLowerCase()) + 1).padStart(2, "0")}-${m[3].padStart(2, "0")}`;
      if (dates.has(iso)) out.push({ start, end, key: "effective_date", value: iso });
    } else if (m[6]) {
      const n = Number(m[6]);
      if (pay.has(n)) out.push({ start, end, key: "payment_days", value: n });
      else if (lead.has(n)) out.push({ start, end, key: "lead_time_days", value: n });
    }
  }
  return out;
}

function delta(key: string, v: number | string, ref: unknown): string | null {
  if (ref === undefined || ref === null) return null;
  if (key === "unit_price" && isNum(ref) && typeof v === "number") {
    const d = v - ref;
    if (Math.abs(d) < 0.005) return "same";
    return `${d > 0 ? "+" : "−"}${eur2(Math.abs(d))} (${d > 0 ? "+" : "−"}${Math.abs((d / ref) * 100).toFixed(1)} %)`;
  }
  if ((key === "payment_days" || key === "lead_time_days") && isNum(ref) && typeof v === "number") {
    const d = v - ref;
    return d === 0 ? "same" : `${d > 0 ? "+" : "−"}${Math.abs(d)} days`;
  }
  if (key === "effective_date" && typeof ref === "string" && typeof v === "string") {
    const a = new Date(ref);
    const b = new Date(v);
    const mo = Math.round((+b - +a) / (30.44 * 864e5));
    return mo === 0 ? "same" : `${mo > 0 ? "+" : "−"}${Math.abs(mo)} months`;
  }
  return null;
}

/**
 * An e-mail with the offered terms highlighted: orange in ours, ink in theirs. Hovering a term shows
 * what the other side had on the table for it (their previous standing offer / our asks this round).
 */
export function MailText({
  body,
  sheets,
  compare,
  compareLabel,
  ours,
}: {
  body?: string;
  sheets: Terms[]; // the terms this e-mail offered
  compare: Terms[]; // the other side's terms to compare against on hover
  compareLabel: string;
  ours: boolean;
}) {
  if (!body) return <span>–</span>;
  const hs = hits(body, sheets);
  const parts: ReactNode[] = [];
  let at = 0;
  hs.forEach((h, i) => {
    if (h.start > at) parts.push(body.slice(at, h.start));
    const refs = [...new Set(compare.map((t) => t[h.key]).filter((x) => x !== undefined && x !== null).map((x) => JSON.stringify(x)))].map(
      (x) => JSON.parse(x) as unknown,
    );
    parts.push(
      <span
        key={i}
        className={cx(
          "group relative cursor-help rounded px-0.5 font-semibold",
          ours ? "bg-accent-soft text-accent-deep ring-1 ring-accent/30" : "bg-paper-3 text-ink ring-1 ring-line",
        )}
      >
        {body.slice(h.start, h.end)}
        <span className="pointer-events-none absolute bottom-full left-0 z-30 mb-1.5 hidden min-w-[13rem] whitespace-nowrap rounded-lg border border-line bg-white px-3 py-2 font-sans text-[0.72rem] font-normal text-ink-2 shadow-lg group-hover:block">
          <span className="block text-[0.62rem] uppercase tracking-[0.12em] text-ink-4">
            {termLabel(h.key)} · {compareLabel}
          </span>
          {refs.length === 0 ? (
            <span className="block text-ink-3">not on their sheet</span>
          ) : (
            refs.slice(0, 3).map((r, j) => {
              const d = delta(h.key, h.value, r);
              return (
                <span key={j} className="mt-0.5 flex items-baseline justify-between gap-4">
                  <span className="font-mono tabular-nums text-ink">{termValue(h.key, r)}</span>
                  {d && <span className={cx("font-mono tabular-nums", d === "same" ? "text-ink-4" : "text-accent-deep")}>{d === "same" ? "same" : `${ours ? "we" : "they"} ${d}`}</span>}
                </span>
              );
            })
          )}
        </span>
      </span>,
    );
    at = h.end;
  });
  parts.push(body.slice(at));
  return <>{parts}</>;
}
