"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { RunWithTrace } from "@/components/RunWithTrace";
import { useRunSummary } from "@/lib/use-run-summary";
import { useRunEvents, type StreamState } from "@/lib/sse";

const STREAM_VARIANT: Record<StreamState, "outline" | "destructive" | "secondary"> = {
  connecting: "outline",
  open: "outline",
  done: "secondary",
  error: "destructive",
};

function MatchRun({ runId }: { runId: string }) {
  const { events, state, runStatus } = useRunEvents(runId);
  const { summary, error } = useRunSummary(runId, runStatus !== null);
  return (
    <RunWithTrace
      runId={runId}
      events={events}
      live={state !== "done" && state !== "error"}
      status={{ label: state, variant: STREAM_VARIANT[state] }}
      matches={summary?.status === "done" ? summary.matches : null}
    >
      <p className="text-sm text-muted-foreground">
        Run <span className="font-mono">{runId}</span> · {runStatus ?? "running"}
        {runStatus && (
          <>
            {" · "}
            <Link href={`/runs/${encodeURIComponent(runId)}`} className="underline">
              Replay
            </Link>
          </>
        )}
      </p>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {runStatus === "failed" && (
        <p className="text-sm text-destructive">Run failed; the error event is in the trace.</p>
      )}
      {runStatus && !summary && !error && (
        <p className="text-sm text-muted-foreground">Loading results…</p>
      )}
    </RunWithTrace>
  );
}

export function RunView() {
  const { runId } = useParams<{ runId: string }>();
  return <MatchRun key={runId} runId={runId} />;
}
