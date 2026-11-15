"use client";

import { useParams } from "next/navigation";
import { useCallback } from "react";

import { RunWithTrace } from "@/components/RunWithTrace";
import type { BadgeVariant } from "@/components/TracePanel";
import { api } from "@/lib/api";
import { useRunEvents, type StreamState } from "@/lib/sse";
import { useLoad } from "@/lib/use-load";

const STREAM_VARIANT: Record<StreamState, BadgeVariant> = {
  connecting: "outline",
  open: "outline",
  done: "secondary",
  error: "destructive",
};

function MatchRun({ runId }: { runId: string }) {
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
      matches={summary?.status === "done" ? summary.matches : null}
      runStatus={runStatus ?? "running"}
      link={finished ? { href: `/runs/${encodeURIComponent(runId)}`, label: "Replay" } : undefined}
    >
      {error && <p className="text-sm text-destructive">{error}</p>}
      {finished && !summary && !error && (
        <p className="text-sm text-muted-foreground">Loading results…</p>
      )}
    </RunWithTrace>
  );
}

export function RunView() {
  const { runId } = useParams<{ runId: string }>();
  return <MatchRun key={runId} runId={runId} />;
}
