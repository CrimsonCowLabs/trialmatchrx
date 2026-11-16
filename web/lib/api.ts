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
export type CloserRequest = Schemas["CloserRequest"];
export type CloserOutput = Schemas["CloserOutput"];
export type TrialListItem = Schemas["TrialListItem"];
export type TrialDetail = Schemas["TrialDetail"];
export type RunListItem = Schemas["RunListItem"];
export type RunStats = Schemas["RunStats"];
export type RunKind = RunListItem["kind"];
export type Tier = Schemas["TrialMatch"]["tier"];
export type TierCounts = Schemas["TierCounts"];
export type Health = Schemas["Health"];
export type GuidePin = Schemas["GuidePin"];
export type Me = Schemas["Me"];
export type LoginRequest = Schemas["LoginRequest"];

// Called directly (not through a Next rewrite) so the SSE stream is never buffered. Inlined at
// build time: the Docker image is built with "" so every call is a same-origin `/api/...` path.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8045";

type JsonBody<P extends keyof paths, M extends "post"> = paths[P][M] extends {
  requestBody?: { content: { "application/json": infer B } };
}
  ? B
  : never;

/** How a failed call reads on the page. */
export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** A non-2xx answer; `status` lets a page react to e.g. 404 (not compiled) vs 503, and
 *  `detail` is FastAPI's `detail` message when it sent a string one. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: string | null = null,
  ) {
    super(message);
  }
}

function detailOf(body: string): string | null {
  try {
    const detail: unknown = JSON.parse(body)?.detail;
    return typeof detail === "string" ? detail : null;
  } catch {
    return null;
  }
}

/** Every request carries the session cookie (`credentials: "include"`, since in dev the API is
 *  on another port) and `X-Requested-With`, without which the API refuses any POST (its CSRF
 *  guard). */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "content-type": "application/json",
      "x-requested-with": "fetch",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text();
    const message = `${init?.method ?? "GET"} ${path} -> ${res.status}: ${body}`;
    throw new ApiError(message, res.status, detailOf(body));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  login: (body: LoginRequest) =>
    request<Me>("/api/auth/login", { method: "POST", body: JSON.stringify(body) }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  /** The signed-in account; rejects with an ApiError of status 401 when signed out. */
  me: () => request<Me>("/api/auth/me"),
  startMatch: (body: JsonBody<"/api/match", "post">) =>
    request<RunStarted>("/api/match", { method: "POST", body: JSON.stringify(body) }),
  startCloser: (body: CloserRequest) =>
    request<RunStarted>("/api/closer", { method: "POST", body: JSON.stringify(body) }),
  getRun: (runId: string) => request<RunSummary>(`/api/runs/${encodeURIComponent(runId)}`),
  getTrace: (runId: string) =>
    request<TraceEvent[]>(`/api/runs/${encodeURIComponent(runId)}/trace`),
  listTrials: (q?: string) =>
    request<TrialListItem[]>(`/api/trials${q ? `?${new URLSearchParams({ q })}` : ""}`),
  listRuns: ({ kind = "match", limit }: { kind?: RunKind; limit?: number } = {}) =>
    request<RunListItem[]>(
      `/api/runs?${new URLSearchParams({ kind, ...(limit && { limit: String(limit) }) })}`,
    ),
  getTrial: (nct: string) => request<TrialDetail>(`/api/trials/${encodeURIComponent(nct)}`),
  getHealth: () => request<Health>("/api/health"),
  getRunStats: () => request<RunStats>("/api/runs/stats"),
  getEvalLatest: () => request<EvalLatest>("/api/eval/latest"),
  listGuidePins: () => request<GuidePin[]>("/api/guide"),
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
