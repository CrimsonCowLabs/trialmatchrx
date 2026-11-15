"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import { RunWithTrace } from "@/components/RunWithTrace";
import { STREAM_VARIANT } from "@/components/TracePanel";
import { api, errorMessage } from "@/lib/api";
import { useRunEvents } from "@/lib/sse";
import { useLoad } from "@/lib/use-load";

function MatchRun({ runId }: { runId: string }) {
  const router = useRouter();
  const { events, state, runStatus } = useRunEvents(runId);
  const finished = runStatus !== null;
  const loadSummary = useCallback(() => api.getRun(runId), [runId]);
  const { data: summary, error } = useLoad(finished ? loadSummary : null);
  const [closer, setCloser] = useState<{ nct: string; error: string | null } | null>(null);

  // "Next steps" on a trial: start the closer agent and watch it on its own run page.
  const startCloser = (nct: string) => {
    if (closer && !closer.error) return; // one at a time
    setCloser({ nct, error: null });
    api.startCloser({ run_id: runId, nct_id: nct }).then(
      // The closer page links back to this match run through `?match=`.
      ({ run_id }) =>
        router.push(
          `/closer/${encodeURIComponent(run_id)}?match=${encodeURIComponent(runId)}`,
        ),
      (err: unknown) => setCloser({ nct, error: errorMessage(err) }),
    );
  };

  return (
    <RunWithTrace
      runId={runId}
      events={events}
      live={state !== "done" && state !== "error"}
      status={{ label: state, variant: STREAM_VARIANT[state] }}
      matches={summary?.status === "done" ? summary.matches : null}
      totals={summary?.totals}
      onNextSteps={summary?.status === "done" ? startCloser : undefined}
      runStatus={runStatus ?? "running"}
      link={finished ? { href: `/runs/${encodeURIComponent(runId)}`, label: "Replay" } : undefined}
    >
      {error && <p className="text-sm text-destructive">{error}</p>}
      {finished && !summary && !error && (
        <p className="text-sm text-muted-foreground">Loading results…</p>
      )}
      {closer &&
        (closer.error ? (
          <p className="text-sm text-destructive">
            Next steps for {closer.nct} failed: {closer.error}
          </p>
        ) : (
          <p className="text-sm text-muted-foreground">Starting the closer agent on {closer.nct}…</p>
        ))}
    </RunWithTrace>
  );
}

export function RunView() {
  const { runId } = useParams<{ runId: string }>();
  return <MatchRun key={runId} runId={runId} />;
}
