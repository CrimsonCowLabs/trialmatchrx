"use client";

import { useEffect, useState } from "react";

import { ApiError, api, errorMessage } from "./api";
import type { FeasibilityResult, Overrides } from "./feasibility";

/** SPEC.md: the slider calls the API on every change, debounced 150 ms. */
export const FEASIBILITY_DEBOUNCE_MS = 150;

export interface FeasibilityState {
  result: FeasibilityResult | null; // the latest answer; kept on screen while the next loads
  error: { message: string; status: number | null } | null;
  loading: boolean;
  latencyMs: number | null; // round trip of the latest answer, shown next to the count
}

/** POST /api/feasibility/{nct} whenever `overrides` settles for `delayMs`. A superseded request
 *  is aborted, so a late answer for an old slider position never overwrites a newer one.
 *  Bump `reloadKey` to refetch with the same overrides (e.g. after compiling the trial). */
export function useFeasibility(
  nct: string,
  overrides: Overrides,
  reloadKey = 0,
  delayMs = FEASIBILITY_DEBOUNCE_MS,
): FeasibilityState {
  const [state, setState] = useState<FeasibilityState>({
    result: null,
    error: null,
    loading: true,
    latencyMs: null,
  });
  // Stable dependency for an object the caller rebuilds on every render.
  const body = JSON.stringify({ overrides });
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setState((s) => ({ ...s, loading: true }));
      const started = performance.now();
      try {
        const result = await api.feasibility(nct, JSON.parse(body), controller.signal);
        if (controller.signal.aborted) return;
        const latencyMs = Math.round(performance.now() - started);
        setState({ result, error: null, loading: false, latencyMs });
      } catch (err) {
        if (controller.signal.aborted) return;
        const status = err instanceof ApiError ? err.status : null;
        setState((s) => ({ ...s, error: { message: errorMessage(err), status }, loading: false }));
      }
    }, delayMs);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [nct, body, reloadKey, delayMs]);
  return state;
}
