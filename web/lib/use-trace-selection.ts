"use client";

// Shared state behind the two-way link between verdicts and the trace panel: which event is
// selected, which tree nodes are expanded, which rows show their details, and a scroll request.
// Owned by the page so both MatchResults ("Why?", highlight) and TracePanel can use it.
import { useCallback, useState } from "react";

import type { TraceEvent } from "./api";
import { ancestorIds } from "./trace";

export interface ScrollRequest {
  id: string;
  nonce: number; // a new request for the same id still scrolls
}

export interface TraceSelection {
  selectedId: string | null;
  expanded: ReadonlySet<string>;
  details: ReadonlySet<string>;
  scrollRequest: ScrollRequest | null;
  /** Click on a trace row: select it and toggle its details. */
  select: (id: string) => void;
  toggleExpanded: (id: string) => void;
  /** "Why?" on a verdict: select the event, open its ancestors and details, scroll to it. */
  focus: (id: string) => void;
}

function toggled(set: ReadonlySet<string>, id: string): Set<string> {
  const next = new Set(set);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

export function useTraceSelection(events: TraceEvent[]): TraceSelection {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [details, setDetails] = useState<ReadonlySet<string>>(new Set());
  const [scrollRequest, setScrollRequest] = useState<ScrollRequest | null>(null);

  const select = useCallback((id: string) => {
    setSelectedId(id);
    setDetails((d) => toggled(d, id));
  }, []);

  const toggleExpanded = useCallback((id: string) => setExpanded((x) => toggled(x, id)), []);

  const focus = useCallback(
    (id: string) => {
      setSelectedId(id);
      setExpanded((x) => new Set([...x, ...ancestorIds(events, id)]));
      setDetails((d) => new Set([...d, id]));
      setScrollRequest((r) => ({ id, nonce: (r?.nonce ?? 0) + 1 }));
    },
    [events],
  );

  return { selectedId, expanded, details, scrollRequest, select, toggleExpanded, focus };
}
