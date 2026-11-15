"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { TracePanel } from "@/components/TracePanel";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type RunSummary } from "@/lib/api";
import { useRunEvents } from "@/lib/sse";

function Results({ runId }: { runId: string }) {
  const [summary, setSummary] = useState<RunSummary | null>(null);
  useEffect(() => {
    api.getRun(runId).then(setSummary, () => setSummary(null));
  }, [runId]);
  if (!summary) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{summary.matches.length} trial(s)</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-1 text-sm">
          {summary.matches.map((m) => (
            <li key={m.nct_id}>
              <span className="font-mono">{m.nct_id}</span> · {m.title} · <b>{m.tier}</b> (
              {m.counts.pass ?? 0} pass / {m.counts.fail ?? 0} fail / {m.counts.unknown ?? 0}{" "}
              unknown)
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function Run({ runId }: { runId: string }) {
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
  return <Run key={runId} runId={runId} />;
}
