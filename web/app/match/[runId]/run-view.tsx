"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { MatchResults } from "@/components/MatchResults";
import { TracePanel } from "@/components/TracePanel";
import { api, type RunSummary } from "@/lib/api";
import { useRunEvents } from "@/lib/sse";

function Results({ runId }: { runId: string }) {
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.getRun(runId).then(setSummary, (err: unknown) =>
      setError(err instanceof Error ? err.message : String(err)),
    );
  }, [runId]);
  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!summary) return <p className="text-sm text-muted-foreground">Loading results…</p>;
  return <MatchResults matches={summary.matches} />;
}

function MatchRun({ runId }: { runId: string }) {
  const { events, state, runStatus } = useRunEvents(runId);
  return (
    <div className="grid gap-4 md:grid-cols-[1fr_minmax(0,28rem)]">
      <div className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          Run <span className="font-mono">{runId}</span> · {runStatus ?? "running"}
        </p>
        {runStatus === "done" && <Results runId={runId} />}
      </div>
      <TracePanel events={events} state={state} />
    </div>
  );
}

export function RunView() {
  const { runId } = useParams<{ runId: string }>();
  return <MatchRun key={runId} runId={runId} />;
}
