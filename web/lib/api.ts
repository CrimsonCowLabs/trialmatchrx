// Typed client for the FastAPI backend. Types come from lib/api-types.ts (`make types`).
import type { components, paths } from "./api-types";

export type Schemas = components["schemas"];
export type TraceEvent = Schemas["TraceEvent"];
export type RunSummary = Schemas["RunSummary"];
export type RunDone = Schemas["RunDone"];
export type MatchRequest = Schemas["MatchRequest"];
export type RunStarted = Schemas["RunStarted"];

// Called directly (not through a Next rewrite) so the SSE stream is never buffered.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type JsonBody<P extends keyof paths, M extends "post"> = paths[P][M] extends {
  requestBody?: { content: { "application/json": infer B } };
}
  ? B
  : never;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} -> ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as T;
}

export const api = {
  startMatch: (body: JsonBody<"/api/match", "post">) =>
    request<RunStarted>("/api/match", { method: "POST", body: JSON.stringify(body) }),
  getRun: (runId: string) => request<RunSummary>(`/api/runs/${encodeURIComponent(runId)}`),
  getTrace: (runId: string) =>
    request<TraceEvent[]>(`/api/runs/${encodeURIComponent(runId)}/trace`),
  eventsUrl: (runId: string) => `${API_URL}/api/runs/${encodeURIComponent(runId)}/events`,
};
