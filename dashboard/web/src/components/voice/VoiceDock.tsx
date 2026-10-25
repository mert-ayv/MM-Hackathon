// "Ask Tactopus": the ElevenLabs voice copilot, docked bottom-right on every view.
// Live mode talks to the ElevenLabs agent (signed URL from our server, client tools in lib/voice);
// demo mode plays a scripted conversation over the showcase with pre-generated audio, offline.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ConversationProvider, useConversation } from "@elevenlabs/react";
import { cx } from "../ui";
import { CopilotCard } from "./Cards";
import {
  buildContext,
  buildDebrief,
  currentCase,
  loadCase,
  loadDemo,
  makeClientTools,
  mode as viewMode,
  onActivity,
  SHOWCASE,
  type Activity,
  type Card,
} from "../../lib/voice";

type Phase = "idle" | "connecting" | "live" | "demo";
type Bubble = { id: number; role: "user" | "agent"; text: string } | { id: number; role: "card"; card: Card };

export function VoiceDock() {
  return (
    <ConversationProvider>
      <Dock />
    </ConversationProvider>
  );
}

function useHash() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

let bubbleSeq = 0;
const STUDIO_PANEL = 376; // width of Agent Studio's right-hand panel

const CASE_PROMPTS = ["Why did we accept in the end?", "Where did we leave money on the table?", "What would you change in the playbook?"];
const PLAYBOOK_PROMPTS = ["Which case type loses us the most?", "Which step should I tune first?", "Propose one change for raw-material cases"];

function Dock() {
  const hash = useHash();
  // `?voice=1` in the hash opens the dock on load (handy for recordings)
  // `?voice=1` opens the dock on load; `?voice=demo` also plays the offline demo (recordings)
  const [open, setOpen] = useState(() => /[?&]voice=(1|demo)/.test(window.location.hash));
  const [phase, setPhase] = useState<Phase>("idle");
  const [muted, setMuted] = useState(false);
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [chips, setChips] = useState<Extract<Activity, { kind: "tool" | "toast" }>[]>([]);
  const [toast, setToast] = useState<Activity | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [caseLabel, setCaseLabel] = useState<string>("");
  const demoStop = useRef<(() => void) | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [bubbles]);
  const demoLevel = useRef<() => number>(() => 0);
  const tools = useMemo(() => makeClientTools(), []);

  const say = useCallback((role: "user" | "agent", text: string) => {
    setBubbles((b) => [...b.slice(-9), { id: ++bubbleSeq, role, text }]);
  }, []);

  const convo = useConversation({
    micMuted: muted,
    clientTools: tools,
    onMessage: (m) => say(m.role === "user" || m.source === "user" ? "user" : "agent", m.message),
    onConnect: () => setPhase("live"),
    onDisconnect: () => setPhase((p) => (p === "live" || p === "connecting" ? "idle" : p)),
    onError: (message) => {
      setNote(`Voice error: ${String(message)}`);
      setPhase("idle");
    },
  });

  useEffect(() => {
    fetch("/api/voice/status")
      .then((r) => r.json())
      .then((s: { configured: boolean }) => setConfigured(!!s.configured))
      .catch(() => setConfigured(false));
  }, []);

  useEffect(
    () =>
      onActivity((a) => {
        if (a.kind === "card") {
          const c = a.card;
          setBubbles((b) => [...b.slice(-9), { id: ++bubbleSeq, role: "card", card: c }]);
        } else if (a.kind === "toast") {
          setToast(a);
          window.setTimeout(() => setToast((t) => (t?.id === a.id ? null : t)), 6000);
        } else setChips((c) => [...c.slice(-2), a]);
      }),
    [],
  );

  // what the dock is about: the open negotiation, or the playbook
  const playbook = hash.startsWith("#/studio");
  useEffect(() => {
    const ref = currentCase();
    if (playbook) setCaseLabel("Playbook · all negotiations");
    else if (!ref) setCaseLabel("No negotiation open · showcase P01");
    else
      loadCase(ref)
        .then((m) => setCaseLabel(`${ref.caseId.replace(/^case:/, "")} · ${m.threads.find((t) => t.sid === m.result?.supplier_id)?.short ?? m.threads[0]?.short ?? ""}`))
        .catch(() => setCaseLabel(ref.caseId));
  }, [hash, playbook]);

  // V toggles the dock
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.key !== "v" || e.metaKey || e.ctrlKey || e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      setOpen((o) => !o);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  const startLive = async () => {
    setNote(null);
    setBubbles([]);
    setChips([]);
    setPhase("connecting");
    try {
      const ref = currentCase() ?? SHOWCASE;
      const m = await loadCase(ref);
      const pb = viewMode() === "playbook";
      const debrief = pb
        ? "I'm looking at the playbook. Ask me where the agent loses money across negotiations, or what I'd change in a step."
        : buildDebrief(m);
      const r = await fetch("/api/voice/session");
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail ?? `session ${r.status}`);
      const { signed_url } = (await r.json()) as { signed_url: string };
      convo.startSession({
        signedUrl: signed_url,
        clientTools: tools,
        dynamicVariables: { debrief, case_context: await buildContext(m), mode: pb ? "playbook" : "negotiation" },
      });
    } catch (e) {
      setNote(`Live voice unavailable (${e instanceof Error ? e.message : String(e)}). Playing the demo instead.`);
      void startDemo();
    }
  };

  const startDemo = async () => {
    setBubbles([]);
    setChips([]);
    const demo = await loadDemo();
    if (!demo) {
      setNote("No demo script found (/voice/demo.json).");
      setPhase("idle");
      return;
    }
    setPhase("demo");
    let stopped = false;
    let audio: HTMLAudioElement | null = null;
    demoStop.current = () => {
      stopped = true;
      audio?.pause();
      window.speechSynthesis?.cancel();
      demoLevel.current = () => 0;
      setPhase("idle");
    };
    const here = currentCase();
    const onShowcase = here && here.runId === demo.case.runId && here.caseId === demo.case.caseId;
    if (!onShowcase && !window.location.hash.startsWith("#/studio"))
      window.location.hash = `#/n/${encodeURIComponent(demo.case.runId)}/${encodeURIComponent(demo.case.caseId)}`;
    const wait = (ms: number) => new Promise((res) => window.setTimeout(res, ms));
    for (const line of demo.lines) {
      if (stopped) return;
      if (line.role === "user") {
        await wait(700);
        say("user", line.text);
        await wait(900);
        continue;
      }
      if (line.tool) await tools[line.tool.name]?.(line.tool.params).catch(() => undefined);
      say("agent", line.text);
      await speak(line.text, line.audio, (a) => (audio = a), demoLevel);
      if (stopped) return;
      await wait(350);
    }
    demoLevel.current = () => 0;
    if (!stopped) setPhase("idle");
  };

  const autoDemo = useRef(/[?&]voice=demo/.test(window.location.hash));
  useEffect(() => {
    if (!autoDemo.current) return;
    const t = window.setTimeout(() => {
      autoDemo.current = false;
      void startDemo();
    }, 1200);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stop = () => {
    if (phase === "demo") demoStop.current?.();
    else void convo.endSession();
    setPhase("idle");
  };

  const active = phase !== "idle";
  const hasCards = bubbles.some((b) => b.role === "card");
  const level = useCallback(() => {
    if (phase === "live") return Math.max(convo.getOutputVolume?.() ?? 0, (convo.getInputVolume?.() ?? 0) * 0.6);
    if (phase === "demo") return demoLevel.current();
    return 0;
  }, [phase, convo]);
  const speaking = phase === "live" ? convo.isSpeaking : phase === "demo";

  return (
    // on Agent Studio the dock sits left of the suggestions panel, so it never covers Accept / Reject
    <div
      className="pointer-events-none fixed bottom-6 z-50 flex flex-col items-end gap-3 transition-[right] duration-300"
      style={{ right: playbook ? STUDIO_PANEL + 24 : 24 }}
    >
      {toast && (
        <a
          href="#/studio"
          className="pointer-events-auto flex animate-rise items-center gap-3 rounded-full border border-accent/40 bg-white py-2 pl-3 pr-4 text-[0.8rem] font-medium text-ink shadow-lg"
        >
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent text-[0.75rem] text-white">↗</span>
          {toast.text}
          <span className="text-accent-deep">Review →</span>
        </a>
      )}

      {open ? (
        <div className={cx("pointer-events-auto flex max-h-[calc(100vh-96px)] flex-col overflow-hidden transition-[width] duration-300", hasCards ? "w-[440px]" : "w-[380px]", " rounded-2xl border border-line bg-white shadow-[0_24px_60px_-20px_rgba(11,11,12,0.35)]")}>
          <div className="flex items-start justify-between gap-3 px-5 pt-5">
            <div>
              <div className="text-[0.68rem] font-medium uppercase tracking-[0.12em] text-ink-3">Tactopus · copilot</div>
              <div className="mt-0.5 text-[0.95rem] font-semibold tracking-tight">{caseLabel}</div>
            </div>
            <button onClick={() => setOpen(false)} className="rounded-full px-2 text-ink-3 hover:text-ink" title="Close (V)">
              ✕
            </button>
          </div>

          <div className={cx("flex items-center px-5 pb-2", hasCards ? "gap-3 pt-3" : "flex-col pt-4")}>
            <Orb level={level} active={active} speaking={speaking} size={hasCards ? 48 : 112} />
            <div className={cx("h-5 text-[0.8rem] text-ink-3", !hasCards && "mt-3")}>
              {phase === "idle" && (configured === false ? "Voice offline · demo available" : "Ask why, or what to change")}
              {phase === "connecting" && "Connecting…"}
              {phase === "live" && (convo.isSpeaking ? "Speaking" : muted ? "Mic muted" : "Listening…")}
              {phase === "demo" && "Demo · showcase replay"}
            </div>
          </div>

          <div className={cx("flex flex-wrap gap-1.5 px-5", hasCards ? "justify-start" : "justify-center", active && !hasCards && "min-h-[3.5rem]")}>
            {chips.map((c) => (
              <span key={c.id} className="inline-flex animate-rise items-center gap-1.5 rounded-full border border-line bg-paper-2 px-2.5 py-1 text-[0.7rem] text-ink-2">
                <span className={cx("h-1.5 w-1.5 rounded-full", c.text.startsWith("Proposed") ? "bg-accent" : "bg-ink")} />
                {c.text}
              </span>
            ))}
          </div>

          {(phase === "idle" || phase === "live") && bubbles.length === 0 && (
            <div className="space-y-1.5 px-5 pb-4">
              {(playbook ? PLAYBOOK_PROMPTS : CASE_PROMPTS).map((q) => (
                <button
                  key={q}
                  onClick={() => (phase === "live" ? convo.sendUserMessage(q) : configured ? void startLive() : void startDemo())}
                  className="flex w-full items-center justify-between rounded-xl border border-line px-3.5 py-2 text-left text-[0.8rem] text-ink-2 transition-colors hover:border-ink hover:text-ink"
                >
                  {q}
                  <span className="text-ink-4">↵</span>
                </button>
              ))}
            </div>
          )}

          <div ref={scroller} className={cx("min-h-0 space-y-2 overflow-y-auto px-5 pb-4 pt-2", hasCards ? "flex-1" : "max-h-[260px]")}>
            {bubbles.map((b) =>
              b.role === "card" ? (
                <CopilotCard key={b.id} card={b.card} />
              ) : (
              <div key={b.id} className={cx("flex animate-rise", b.role === "user" ? "justify-end" : "justify-start")}>
                <div
                  className={cx(
                    "max-w-[85%] rounded-2xl px-3.5 py-2 text-[0.82rem] leading-snug",
                    b.role === "user" ? "rounded-br-sm bg-ink text-white" : "rounded-bl-sm bg-paper-3 text-ink",
                  )}
                >
                  {b.text}
                </div>
              </div>
              ),
            )}
            {note && <div className="text-center text-[0.72rem] text-ink-3">{note}</div>}
          </div>

          <div className="flex items-center gap-2 border-t border-line bg-paper-2 px-4 py-3">
            {active ? (
              <button onClick={stop} className="flex-1 rounded-full bg-ink py-2.5 text-[0.85rem] font-semibold text-white hover:bg-ink-2">
                End
              </button>
            ) : (
              <button
                onClick={() => (configured ? void startLive() : void startDemo())}
                className="flex-1 rounded-full bg-accent py-2.5 text-[0.85rem] font-semibold text-white hover:bg-accent-deep"
              >
                {configured ? "Start talking" : "Play demo debrief"}
              </button>
            )}
            {phase === "live" && (
              <button
                onClick={() => setMuted(!muted)}
                className={cx("rounded-full border px-3 py-2.5 text-[0.8rem] font-medium", muted ? "border-accent text-accent-deep" : "border-line text-ink-2")}
                title="Mute the microphone"
              >
                {muted ? "Unmute" : "Mute"}
              </button>
            )}
            {!active && configured && (
              <button onClick={() => void startDemo()} className="rounded-full border border-line px-3 py-2.5 text-[0.8rem] text-ink-2 hover:border-ink" title="Scripted offline demo">
                Demo
              </button>
            )}
          </div>
        </div>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className="pointer-events-auto flex items-center gap-3 rounded-full border border-line bg-white py-2 pl-2 pr-5 shadow-[0_12px_32px_-12px_rgba(11,11,12,0.35)] transition-transform hover:-translate-y-0.5"
          title="Ask Tactopus (V)"
        >
          <Orb level={level} active={active} speaking={speaking} size={36} />
          <span className="text-left">
            <span className="block text-[0.82rem] font-semibold leading-tight">Ask Tactopus</span>
            <span className="block text-[0.68rem] leading-tight text-ink-3">{active ? "In conversation" : playbook ? "Voice · playbook" : "Voice debrief"}</span>
          </span>
        </button>
      )}
    </div>
  );
}

/** Play the pre-generated clip; without it, the browser's own voice; feeds the orb's level. */
function speak(text: string, src: string | undefined, onAudio: (a: HTMLAudioElement) => void, level: { current: () => number }): Promise<void> {
  return new Promise((resolve) => {
    const fallback = () => {
      const synth = window.speechSynthesis;
      if (!synth) {
        window.setTimeout(resolve, Math.min(9000, 60 * text.length));
        return;
      }
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "en-GB";
      u.rate = 1.05;
      const t0 = performance.now();
      level.current = () => 0.35 + 0.25 * Math.abs(Math.sin((performance.now() - t0) / 140));
      u.onend = () => resolve();
      u.onerror = () => resolve();
      synth.speak(u);
    };
    if (!src) return fallback();
    const a = new Audio(src);
    onAudio(a);
    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new Ctx();
      const node = ctx.createMediaElementSource(a);
      const an = ctx.createAnalyser();
      an.fftSize = 256;
      node.connect(an);
      an.connect(ctx.destination);
      const buf = new Uint8Array(an.frequencyBinCount);
      level.current = () => {
        an.getByteFrequencyData(buf);
        let s = 0;
        for (let i = 0; i < buf.length; i++) s += buf[i];
        return Math.min(1, (s / buf.length / 255) * 2.4);
      };
      a.addEventListener("ended", () => void ctx.close());
    } catch {
      /* no WebAudio: the orb just pulses */
    }
    a.onended = () => resolve();
    a.onerror = () => fallback();
    a.play().catch(() => fallback());
  });
}

/** Audio-reactive orb: an orange core and a ring of bars that follow the voice level. */
function Orb({ level, active, speaking, size }: { level: () => number; active: boolean; speaking: boolean; size: number }) {
  const core = useRef<HTMLDivElement>(null);
  const ring = useRef<SVGSVGElement>(null);
  const smooth = useRef(0);
  const BARS = 28;

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const target = active ? level() : 0;
      smooth.current += (target - smooth.current) * 0.25;
      const v = smooth.current;
      const t = performance.now() / 1000;
      if (core.current) core.current.style.transform = `scale(${0.78 + v * 0.32 + (active ? 0.02 * Math.sin(t * 2.4) : 0)})`;
      if (ring.current) {
        const bars = ring.current.children;
        for (let i = 0; i < bars.length; i++) {
          const wobble = 0.5 + 0.5 * Math.sin(t * 5 + i * 1.7);
          const h = 0.08 + (active ? 0.06 : 0) + v * (0.35 + 0.65 * wobble);
          (bars[i] as SVGLineElement).setAttribute("y1", String(-0.62 - h * 0.34));
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active, level]);

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg ref={ring} viewBox="-1 -1 2 2" className="absolute inset-0 h-full w-full">
        {Array.from({ length: BARS }, (_, i) => (
          <line
            key={i}
            x1={0}
            x2={0}
            y1={-0.66}
            y2={-0.6}
            transform={`rotate(${(360 / BARS) * i})`}
            stroke={speaking ? "#FF5A1F" : "#0B0B0C"}
            strokeOpacity={active ? 0.85 : 0.18}
            strokeWidth={0.045}
            strokeLinecap="round"
          />
        ))}
      </svg>
      <div
        ref={core}
        className="absolute rounded-full"
        style={{
          inset: size * 0.24,
          background: active
            ? "radial-gradient(circle at 35% 30%, #FFB08F 0%, #FF5A1F 45%, #D9430E 100%)"
            : "radial-gradient(circle at 35% 30%, #3A3A3D 0%, #0B0B0C 70%)",
          boxShadow: active ? "0 0 0 4px rgba(255,90,31,0.12), 0 8px 24px -6px rgba(255,90,31,0.6)" : "none",
          transition: "background 300ms",
        }}
      />
    </div>
  );
}

