"use client";

// A closer agent run, live: the trace streams every thought, tool call and tool result on the
// right; the follow-ups, coordinator email and EN/ES summary appear on the left when it's done.
import Link from "next/link";
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
  return (
    <RunWithTrace
      runId={runId}
      events={events}
      live={state !== "done" && state !== "error"}
      status={{ label: state, variant: STREAM_VARIANT[state] }}
      matches={null}
      closer={summary?.closer ?? null}
      runStatus={runStatus ?? "running"}
      link={finished ? { href: `/runs/${encodeURIComponent(runId)}`, label: "Replay" } : undefined}
    >
      {matchRunId && (
        <Link href={`/match/${encodeURIComponent(matchRunId)}`} className="text-sm underline">
          Back to the match results
        </Link>
      )}
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
