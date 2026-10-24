const eurFmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const eur2Fmt = new Intl.NumberFormat("en-US", { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2 });

const isNum = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);

/** €1,033,473 */
export function eur(n: unknown, dash = "–"): string {
  return isNum(n) ? eurFmt.format(n).replace("-", "−") : dash;
}

/** €129.90 (unit prices) */
export function eur2(n: unknown, dash = "–"): string {
  return isNum(n) ? eur2Fmt.format(n).replace("-", "−") : dash;
}

/** +€1,234 / −€1,234 */
export function eurDelta(n: unknown, dash = "–"): string {
  if (!isNum(n)) return dash;
  if (Math.abs(n) < 0.5) return "€0";
  return (n > 0 ? "+" : "−") + eurFmt.format(Math.abs(n));
}

/** €1.03M / €982k for axes */
export function eurShort(n: number): string {
  const a = Math.abs(n);
  const sign = n < 0 ? "−" : "";
  if (a >= 1e6) return `${sign}€${(a / 1e6).toFixed(a >= 1e7 ? 1 : 2)}M`;
  if (a >= 1e4) return `${sign}€${Math.round(a / 1e3)}k`;
  if (a >= 1e3) return `${sign}€${(a / 1e3).toFixed(1)}k`;
  return `${sign}€${Math.round(a)}`;
}

export function score(n: unknown, dash = "–"): string {
  return isNum(n) ? n.toFixed(2) : dash;
}

export function pct(n: unknown, digits = 0): string {
  return isNum(n) ? `${(n * 100).toFixed(digits)}%` : "–";
}

export function time(ts: string | null | undefined): string {
  if (!ts) return "–";
  const d = new Date(ts);
  return isNaN(+d) ? ts : d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function dateTime(ts: string | null | undefined): string {
  if (!ts) return "–";
  const d = new Date(ts);
  if (isNaN(+d)) return ts;
  return d.toLocaleString("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit" });
}

export function duration(s: number): string {
  if (!Number.isFinite(s)) return "–";
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${String(Math.round(s % 60)).padStart(2, "0")}s`;
}

export function humanize(key: string): string {
  return key.replace(/_/g, " ").replace(/\b(eur)\b/g, "€");
}

/** Short human labels for term fields */
const TERM_LABEL: Record<string, string> = {
  unit_price: "Price",
  payment_days: "Payment",
  effective_date: "From",
  contract_months: "Term",
  incoterm: "Incoterm",
  lead_time_days: "Lead time",
  volume_per_year: "Volume",
  tooling_eur: "Tooling",
  ppm_commitment: "ppm",
  chargeback_eur_per_complaint: "Chargeback",
  index_clause: "Index",
};

export function termLabel(k: string): string {
  return TERM_LABEL[k] ?? humanize(k);
}

export function termValue(k: string, v: unknown): string {
  if (v === null || v === undefined) return "–";
  if (k === "unit_price") return eur2(v);
  if (k === "payment_days") return `${v} d`;
  if (k === "lead_time_days") return `${v} d`;
  if (k === "contract_months") return `${v} mo`;
  if (k === "tooling_eur" || k === "chargeback_eur_per_complaint") return eur(v);
  if (k === "volume_per_year" && typeof v === "number") return v.toLocaleString("en-US");
  if (k === "effective_date" && typeof v === "string") {
    const d = new Date(v);
    return isNaN(+d) ? v : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function shortSupplier(name: string | undefined, sid: string): string {
  if (!name) return sid;
  // "Gießerei Brandlhuber GmbH & Co. KG" -> "Brandlhuber"
  const stop = /^(gießerei|eisengießerei|odlewnia|präzisionsteile|drehteile|feinguss|slévárna|zerspanung|the)$/i;
  const words = name
    .replace(/,.*$/, "")
    .split(/\s+/)
    .filter((w) => !/^(GmbH|KG|AG|&|Co\.|Sp\.|z|o\.o\.|s\.r\.o\.|a\.s\.|Ltd\.?|A\.Ş\.|SE|Kft\.)$/i.test(w));
  const pick = words.find((w) => !stop.test(w));
  return pick ?? words[0] ?? sid;
}
