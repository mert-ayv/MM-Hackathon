import { useEffect, useState } from "react";

export type Route =
  | { name: "runs" }
  | { name: "case"; runId: string; caseId: string }
  | { name: "replay"; runId: string; caseId: string; at?: number };

export function parse(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/").map(decodeURIComponent);
  if (parts[0] === "case" && parts[1] && parts[2]) return { name: "case", runId: parts[1], caseId: parts[2] };
  if (parts[0] === "replay" && parts[1] && parts[2]) {
    // #/replay/<run>/<case>?at=<event number|end> jumps to a moment (handy for the pitch)
    const at = new URLSearchParams(query).get("at");
    return { name: "replay", runId: parts[1], caseId: parts[2], at: at === "end" ? Infinity : at ? Number(at) || undefined : undefined };
  }
  return { name: "runs" };
}

export function href(r: Route): string {
  if (r.name === "runs") return "#/";
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
