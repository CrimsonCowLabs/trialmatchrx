"use client";

// useRunEvents(runId): one EventSource per run page.
// The server sends stored events first, then live ones, then `done`, so a refresh or a late
// open catches up on its own. A step arrives twice (started, then final) under one id, so
// events are upserted by id and kept in order of first appearance.
import { useEffect, useState } from "react";

import { api, type RunDone, type TraceEvent } from "./api";

export type StreamState = "connecting" | "open" | "done" | "error";

export interface RunEvents {
  events: TraceEvent[];
  state: StreamState;
  runStatus: RunDone["status"] | null;
}

function upsert(events: TraceEvent[], next: TraceEvent): TraceEvent[] {
  const i = events.findIndex((e) => e.id === next.id);
  if (i === -1) return [...events, next];
  if (events[i].seq >= next.seq) return events; // duplicate or stale
  const copy = events.slice();
  copy[i] = next;
  return copy;
}

/** Mount with `key={runId}` so a new run starts from empty state. */
export function useRunEvents(runId: string | null): RunEvents {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [state, setState] = useState<StreamState>("connecting");
  const [runStatus, setRunStatus] = useState<RunDone["status"] | null>(null);

  useEffect(() => {
    if (!runId) return;
    const source = new EventSource(api.eventsUrl(runId));

    source.onopen = () => setState("open");
    source.addEventListener("trace", (msg) => {
      const event = JSON.parse((msg as MessageEvent<string>).data) as TraceEvent;
      setEvents((prev) => upsert(prev, event));
    });
    source.addEventListener("done", (msg) => {
      const done = JSON.parse((msg as MessageEvent<string>).data) as RunDone;
      setRunStatus(done.status);
      setState("done");
      source.close(); // otherwise EventSource reconnects forever
    });
    // EventSource retries on its own (sending Last-Event-ID); only a closed source is fatal.
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) setState("error");
      else setState("connecting");
    };

    return () => source.close();
  }, [runId]);

  return { events, state, runStatus };
}
