"use client";

// useRunEvents(runId): one EventSource per run page.
// The server sends stored events first, then live ones, then `done`, so a refresh or a late
// open catches up on its own. Emissions are folded with `upsertEvent` (lib/trace.ts).
import { useEffect, useState } from "react";

import { api, type RunDone, type TraceEvent } from "./api";
import { upsertEvent } from "./trace";

export type StreamState = "connecting" | "open" | "done" | "error";

export interface RunEvents {
  events: TraceEvent[];
  state: StreamState;
  runStatus: RunDone["status"] | null;
}

/** Mount with `key={runId}` so a new run starts from empty state. */
export function useRunEvents(runId: string | null): RunEvents {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [state, setState] = useState<StreamState>("connecting");
  const [runStatus, setRunStatus] = useState<RunDone["status"] | null>(null);

  useEffect(() => {
    if (!runId) return;
    const source = new EventSource(api.eventsUrl(runId), { withCredentials: true });

    source.onopen = () => setState("open");
    source.addEventListener("trace", (msg) => {
      const event = JSON.parse((msg as MessageEvent<string>).data) as TraceEvent;
      setEvents((prev) => upsertEvent(prev, event));
    });
    source.addEventListener("done", (msg) => {
      const done = JSON.parse((msg as MessageEvent<string>).data) as RunDone;
      setRunStatus(done.status);
      setState("done");
      source.close(); // otherwise EventSource reconnects forever
    });
    // EventSource retries on its own (sending Last-Event-ID); only a closed source is fatal.
    // A refused stream (e.g. a 401 when the session ended) closes it, and EventSource can't
    // see the status. Asking for the run through `api` can: a 401 there goes to /login
    // (lib/api.ts); otherwise the page shows the error.
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        setState("error");
        api.getRun(runId).catch(() => {});
      } else setState("connecting");
    };

    return () => source.close();
  }, [runId]);

  return { events, state, runStatus };
}
