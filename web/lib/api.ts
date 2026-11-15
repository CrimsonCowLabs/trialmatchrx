// Typed client for the FastAPI backend. Types come from lib/api-types.ts (`make types`).
import type { components, paths } from "./api-types";

export type Schemas = components["schemas"];
export type TraceEvent = Schemas["TraceEvent"];
export type RunSummary = Schemas["RunSummary"];
export type RunDone = Schemas["RunDone"];
export type MatchRequest = Schemas["MatchRequest"];
export type RunStarted = Schemas["RunStarted"];
export type EvalLatest = Schemas["EvalLatest"];
export type Criterion = Schemas["Criterion"];
export type FeasibilityRequest = Schemas["FeasibilityRequest"];
export type FeasibilityResult = Schemas["FeasibilityResult"];

// Called directly (not through a Next rewrite) so the SSE stream is never buffered.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type JsonBody<P extends keyof paths, M extends "post"> = paths[P][M] extends {
  requestBody?: { content: { "application/json": infer B } };
}
  ? B
  : never;

/** How a failed call reads on the page. */
export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** A non-2xx answer; `status` lets a page react to e.g. 404 (not compiled) vs 503. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const message = `${init?.method ?? "GET"} ${path} -> ${res.status}: ${await res.text()}`;
    throw new ApiError(message, res.status);
  }
  return (await res.json()) as T;
}

export const api = {
  startMatch: (body: JsonBody<"/api/match", "post">) =>
    request<RunStarted>("/api/match", { method: "POST", body: JSON.stringify(body) }),
  getRun: (runId: string) => request<RunSummary>(`/api/runs/${encodeURIComponent(runId)}`),
  getTrace: (runId: string) =>
    request<TraceEvent[]>(`/api/runs/${encodeURIComponent(runId)}/trace`),
  getEvalLatest: () => request<EvalLatest>("/api/eval/latest"),
  eventsUrl: (runId: string) => `${API_URL}/api/runs/${encodeURIComponent(runId)}/events`,
  feasibility: (nct: string, body: FeasibilityRequest, signal?: AbortSignal) =>
    request<FeasibilityResult>(`/api/feasibility/${encodeURIComponent(nct)}`, {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    }),
  compileTrial: (nct: string) =>
    request<Criterion[]>(`/api/trials/${encodeURIComponent(nct)}/compile`, {
      method: "POST",
      body: JSON.stringify({ force: false }),
    }),
};
