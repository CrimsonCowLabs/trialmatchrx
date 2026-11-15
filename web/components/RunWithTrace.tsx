"use client";

// A run page body: results on the left, the trace drawer on the right, linked both ways.
// "Why?" on a verdict focuses its trace event; selecting a trace event highlights the verdict
// it produced. Used by the live match page and the replay page.
import { useMemo, type ReactNode } from "react";

import { MatchResults } from "@/components/MatchResults";
import { TracePanel, type TracePanelProps } from "@/components/TracePanel";
import type { Schemas, TraceEvent } from "@/lib/api";
import { verdictEventFor } from "@/lib/trace";
import { useTraceSelection } from "@/lib/use-trace-selection";

export function RunWithTrace({
  runId,
  events,
  live,
  status,
  matches,
  children,
}: {
  runId: string;
  events: TraceEvent[];
  live: boolean;
  status: TracePanelProps["status"];
  /** null until the run's results are loaded. */
  matches: Schemas["TrialMatch"][] | null;
  /** Shown above the results (run id, status, controls, errors). */
  children?: ReactNode;
}) {
  const selection = useTraceSelection(events);
  const verdictEventIds = useMemo(
    () => new Set((matches ?? []).flatMap((m) => m.verdicts.map((v) => v.trace_event_id))),
    [matches],
  );
  const highlighted = verdictEventFor(events, selection.selectedId, verdictEventIds);

  return (
    <div className="grid items-start gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,32rem)]">
      <div className="flex min-w-0 flex-col gap-2">
        {children}
        {matches && (
          <MatchResults
            matches={matches}
            highlightedEventId={highlighted}
            onWhy={selection.focus}
          />
        )}
      </div>
      <TracePanel
        runId={runId}
        events={events}
        selection={selection}
        verdictEventIds={verdictEventIds}
        live={live}
        status={status}
      />
    </div>
  );
}
