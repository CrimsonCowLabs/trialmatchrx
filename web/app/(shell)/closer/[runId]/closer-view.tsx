"use client";

// A closer agent run, live: the trace streams every thought, tool call and tool result while
// the agent works; once it's done, the follow-ups, coordinator email and EN/ES summary take
// the page and the trace folds behind "Show trace". The breadcrumb leads back to the match
// results the run started from.
import { useParams, useSearchParams } from "next/navigation";
import { useCallback } from "react";

import { RunWithTrace } from "@/components/RunWithTrace";
import { STREAM_VARIANT } from "@/components/TracePanel";
import { api } from "@/lib/api";
import { useRunEvents } from "@/lib/sse";
import { useLoad } from "@/lib/use-load";

function CloserRun({ runId, matchRunId }: { runId: string; matchRunId: string | null }) {
  const { events, state, runStatus } = useRunEvents(runId);
  const finished = runStatus !== null;
  const loadSummary = useCallback(() => api.getRun(runId), [runId]);
  const { data: summary, error } = useLoad(finished ? loadSummary : null);
  // The summary names the match run once loaded; until then the `?match=` the match page set.
  const sourceRunId = summary?.source_run_id ?? matchRunId;
  return (
    <RunWithTrace
      runId={runId}
      events={events}
      live={state !== "done" && state !== "error"}
      status={{ label: state, variant: STREAM_VARIANT[state] }}
      summary={summary}
      matches={null}
      closer={summary?.closer ?? null}
      totals={summary?.totals}
      runStatus={runStatus ?? "running"}
      link={finished ? { href: `/runs/${encodeURIComponent(runId)}`, label: "Replay" } : undefined}
      title="Next steps"
      breadcrumb={
        sourceRunId
          ? [{ label: "Match results", href: `/match/${encodeURIComponent(sourceRunId)}` }]
          : [{ label: "Runs", href: "/runs" }]
      }
      collapsibleTrace
    >
      {!finished && (
        <p className="text-sm text-muted-foreground">
          The agent is working; watch its thoughts and tool calls in the trace.
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </RunWithTrace>
  );
}

export function CloserView() {
  const { runId } = useParams<{ runId: string }>();
  const matchRunId = useSearchParams().get("match");
  return <CloserRun key={runId} runId={runId} matchRunId={matchRunId} />;
}
