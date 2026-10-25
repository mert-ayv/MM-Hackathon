import { useEffect, useState } from "react";

export type Route =
  | { name: "studio"; nodeId?: string }
  | { name: "negotiations" }
  | { name: "negotiation"; runId: string; caseId: string; round?: number }
  | { name: "runs" }
  | { name: "case"; runId: string; caseId: string }
  | { name: "replay"; runId: string; caseId: string; at?: number };

export function parse(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/").map(decodeURIComponent);
  const q = new URLSearchParams(query);
  if (parts[0] === "studio") return { name: "studio", nodeId: parts[1] || undefined };
  if (parts[0] === "n" && parts[1] && parts[2]) {
    const round = q.get("round");
    return { name: "negotiation", runId: parts[1], caseId: parts[2], round: round ? Number(round) || undefined : undefined };
  }
  if (parts[0] === "n") return { name: "negotiations" };
  if (parts[0] === "runs") return { name: "runs" };
  if (parts[0] === "case" && parts[1] && parts[2]) return { name: "case", runId: parts[1], caseId: parts[2] };
  if (parts[0] === "replay" && parts[1] && parts[2]) {
    // #/replay/<run>/<case>?at=<event number|end> jumps to a moment (handy for the pitch)
    const at = q.get("at");
    return { name: "replay", runId: parts[1], caseId: parts[2], at: at === "end" ? Infinity : at ? Number(at) || undefined : undefined };
  }
  return { name: "studio" };
}

export function href(r: Route): string {
  if (r.name === "studio") return r.nodeId ? `#/studio/${encodeURIComponent(r.nodeId)}` : "#/studio";
  if (r.name === "negotiations") return "#/n";
  if (r.name === "runs") return "#/runs";
  if (r.name === "negotiation")
    return `#/n/${encodeURIComponent(r.runId)}/${encodeURIComponent(r.caseId)}${r.round ? `?round=${r.round}` : ""}`;
  return `#/${r.name}/${encodeURIComponent(r.runId)}/${encodeURIComponent(r.caseId)}`;
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function go(r: Route) {
  window.location.hash = href(r);
}
