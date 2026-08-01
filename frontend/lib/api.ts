// Same-origin by default (the packaged exe serves UI + API from one
// FastAPI process). Dev falls back to :8000; override via NEXT_PUBLIC_*.
const _envApi = process.env.NEXT_PUBLIC_API_URL;
const _sameOrigin =
  typeof window !== "undefined" ? window.location.origin : "http://localhost:8000";

export const API_URL =
  _envApi ?? (typeof window !== "undefined" && window.location.port !== "3000"
    ? "" // served by the same server -> relative URLs
    : "http://localhost:8000");

export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ??
  (typeof window !== "undefined" && window.location.port !== "3000"
    ? _sameOrigin.replace(/^http/, "ws") + "/ws"
    : "ws://localhost:8000/ws");

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function apiSend<T>(
  path: string,
  body: unknown,
  method: "POST" | "PATCH" = "POST",
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${detail.slice(0, 200)}`);
  }
  return res.json();
}

/** Say by hand whether someone is grouped with you.
 *
 * "ignore" is not the opposite of "add" — it holds only until a join line,
 * an invite or a word in group chat proves otherwise, since those are the
 * signals that would have added them anyway. */
export async function trustMember(name: string, action: "add" | "ignore") {
  return apiSend<{
    name: string;
    trusted?: boolean;
    ignored?: boolean;
    adopted?: number;
    group: string[];
  }>("/api/group/trust", { name, action, trust: action === "add" });
}

/** Apply one verdict to everyone currently on the not-counted list.
 *
 * Server-side rather than looping single calls: the list ages and grows as
 * the log moves, so iterating a snapshot fetched a moment ago would act on
 * names that have since left it and miss ones that arrived. */
export async function trustAll(action: "add" | "ignore") {
  return apiSend<{ action: string; names: string[]; group: string[]; over_cap: boolean }>(
    "/api/group/trust-all",
    { action },
  );
}
