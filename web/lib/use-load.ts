"use client";

import { useEffect, useState } from "react";

import { errorMessage } from "./api";

/** Runs `load` whenever it changes (memoize it with useCallback; null = not yet) and keeps
 *  the latest result or error. A superseded or unmounted load is ignored. */
export function useLoad<T>(load: (() => Promise<T>) | null): {
  data: T | null;
  error: string | null;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!load) return;
    let cancelled = false;
    load().then(
      (d) => !cancelled && setData(d),
      (err: unknown) => !cancelled && setError(errorMessage(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [load]);
  return { data, error };
}
