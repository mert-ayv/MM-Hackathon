import { useEffect, useRef, useState, type ReactNode } from "react";

export function cx(...xs: (string | false | null | undefined)[]) {
  return xs.filter(Boolean).join(" ");
}

export function Label({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("text-[0.68rem] font-medium uppercase tracking-[0.12em] text-ink-3", className)}>{children}</div>;
}

export function Card({ children, className, ...rest }: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("rounded-xl border border-line bg-paper shadow-card", className)} {...rest}>
      {children}
    </div>
  );
}

export function SectionTitle({ title, hint, right }: { title: string; hint?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex items-end justify-between gap-4">
      <div>
        <h3 className="text-[0.95rem] font-semibold tracking-tight text-ink">{title}</h3>
        {hint && <div className="mt-0.5 text-[0.78rem] text-ink-3">{hint}</div>}
      </div>
      {right}
    </div>
  );
}

const STATUS: Record<string, { label: string; cls: string; dot?: string }> = {
  open: { label: "Open", cls: "border-line text-ink-2 bg-paper", dot: "bg-ink-4" },
  final_offer: { label: "Final offer", cls: "border-accent/40 text-accent-deep bg-accent-soft", dot: "bg-accent" },
  agreed: { label: "Agreed", cls: "border-ink bg-ink text-white", dot: "bg-white" },
  accepted: { label: "Accepted", cls: "border-ink bg-ink text-white", dot: "bg-accent" },
  walked_away: { label: "Walked away", cls: "border-ink-2 text-ink-2 bg-paper-3 line-through decoration-ink-4", dot: "bg-ink-2" },
  no_bid: { label: "No bid", cls: "border-line text-ink-3 bg-paper-3", dot: "bg-ink-4" },
};

export function StatusBadge({ status, size = "sm" }: { status?: string; size?: "sm" | "lg" }) {
  const s = STATUS[status ?? ""] ?? { label: status ?? "–", cls: "border-line text-ink-2" };
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border font-medium",
        size === "lg" ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-[0.7rem]",
        s.cls,
      )}
    >
      {s.dot && <span className={cx("h-1.5 w-1.5 rounded-full", s.dot)} />}
      {s.label}
    </span>
  );
}

const CLAIM: Record<string, { cls: string; icon: string }> = {
  verified: { cls: "bg-ink text-white border-ink", icon: "✓" },
  contradicted: { cls: "bg-accent text-white border-accent", icon: "✕" },
  irrelevant: { cls: "bg-paper text-ink-3 border-line", icon: "∅" },
  duplicate: { cls: "bg-paper-3 text-ink-2 border-line", icon: "↺" },
};

export function ClaimBadge({ result }: { result: string }) {
  const c = CLAIM[result] ?? { cls: "border-line text-ink-2", icon: "?" };
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[0.68rem] font-semibold uppercase tracking-wide", c.cls)}>
      <span aria-hidden>{c.icon}</span>
      {result}
    </span>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx("font-mono tabular-nums", className)}>{children}</span>;
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  size = "sm",
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
  size?: "sm" | "lg";
}) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-paper-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            "rounded-md font-medium transition-colors",
            size === "lg" ? "px-3.5 py-1.5 text-sm" : "px-2.5 py-1 text-xs",
            value === o.value ? "bg-ink text-white shadow-sm" : "text-ink-3 hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Pill({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cx("inline-flex items-center rounded-full border border-line px-2 py-0.5 text-[0.7rem] text-ink-2", className)}>{children}</span>;
}

/** Smoothly animates a number towards `target`. */
export function useTween(target: number | null, ms = 700): number | null {
  const [v, setV] = useState(target);
  const from = useRef(target);
  const raf = useRef(0);
  useEffect(() => {
    if (target === null) {
      setV(null);
      from.current = null;
      return;
    }
    const start = from.current ?? target;
    if (start === target) {
      setV(target);
      return;
    }
    const t0 = performance.now();
    cancelAnimationFrame(raf.current);
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / ms);
      const e = 1 - Math.pow(1 - k, 3);
      const x = start + (target - start) * e;
      setV(x);
      from.current = x;
      if (k < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [target, ms]);
  return v;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-line px-5 py-8 text-center text-sm text-ink-3">{children}</div>;
}
