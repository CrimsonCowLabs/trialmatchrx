"use client";

import { useEffect, useState } from "react";

import { api, type RunSummary } from "./api";

/** `GET /api/runs/{run_id}` once `enabled` turns true (e.g. when the run is done). */
export function useRunSummary(
  runId: string,
  enabled: boolean,
): { summary: RunSummary | null; error: string | null } {
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    api.getRun(runId).then(
      (s) => !cancelled && setSummary(s),
      (err: unknown) => !cancelled && setError(err instanceof Error ? err.message : String(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [runId, enabled]);
  return { summary, error };
}
