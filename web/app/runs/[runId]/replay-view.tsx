"use client";

// Replays a finished run from GET /api/runs/{run_id}/trace: every emission in seq order
// (`replayEmissions`), with the original gaps capped at 0.2 s, through the same panel and
// results as the live page.
import { Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { RunWithTrace } from "@/components/RunWithTrace";
import { Button } from "@/components/ui/button";
import { api, type RunSummary, type TraceEvent } from "@/lib/api";
import { replayDelays, replayEmissions, upsertEvent } from "@/lib/trace";

const GAP_CAP_MS = 200;
const SPEEDS = [1, 4, 16] as const;

interface Loaded {
  trace: TraceEvent[];
  summary: RunSummary;
}

function useReplaySource(runId: string): { loaded: Loaded | null; error: string | null } {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getTrace(runId), api.getRun(runId)]).then(
      ([trace, summary]) => !cancelled && setLoaded({ trace, summary }),
      (err: unknown) => !cancelled && setError(err instanceof Error ? err.message : String(err)),
    );
    return () => {
      cancelled = true;
    };
  }, [runId]);
  return { loaded, error };
}

function Replay({ runId, trace, summary }: { runId: string } & Loaded) {
  const emissions = useMemo(() => replayEmissions(trace), [trace]);
  const delays = useMemo(() => replayDelays(emissions, GAP_CAP_MS), [emissions]);
  const [shown, setShown] = useState<{ index: number; events: TraceEvent[] }>({
    index: 0,
    events: [],
  });
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const finished = shown.index >= emissions.length;
  const running = playing && !finished;

  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(
      () =>
        setShown(({ index, events }) => ({
          index: index + 1,
          events: upsertEvent(events, emissions[index]),
        })),
      delays[shown.index] / speed,
    );
    return () => clearTimeout(timer);
  }, [running, shown.index, emissions, delays, speed]);

  const restart = () => {
    setShown({ index: 0, events: [] });
    setPlaying(true);
  };
  const skipToEnd = () => setShown({ index: emissions.length, events: trace });

  const live = summary.status === "running";
  return (
    <RunWithTrace
      runId={runId}
      events={shown.events}
      live={false}
      status={{
        label: finished ? "replayed" : `replay ${shown.index}/${emissions.length}`,
        variant: finished ? "secondary" : "outline",
      }}
      matches={finished && summary.status === "done" ? summary.matches : null}
    >
      <p className="text-sm text-muted-foreground">
        Run <span className="font-mono">{runId}</span> · {summary.status} ·{" "}
        <Link href={`/match/${encodeURIComponent(runId)}`} className="underline">
          Live view
        </Link>
      </p>
      {live && (
        <p className="text-sm text-amber-600">
          This run is still running; the replay stops at what has been recorded so far.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2" data-testid="replay-controls">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setPlaying((p) => !p)}
          disabled={finished}
        >
          {running ? <Pause /> : <Play />} {running ? "Pause" : "Play"}
        </Button>
        <Button variant="outline" size="sm" onClick={restart}>
          <RotateCcw /> Restart
        </Button>
        <Button variant="outline" size="sm" onClick={skipToEnd} disabled={finished}>
          <SkipForward /> Skip to end
        </Button>
        <span className="ml-2 text-xs text-muted-foreground">Speed</span>
        {SPEEDS.map((s) => (
          <Button
            key={s}
            variant={s === speed ? "secondary" : "ghost"}
            size="xs"
            onClick={() => setSpeed(s)}
          >
            {s}x
          </Button>
        ))}
        <span className="text-xs tabular-nums text-muted-foreground">
          seq {emissions[shown.index - 1]?.seq ?? 0} / {emissions.length}
        </span>
      </div>
      {finished && summary.status === "failed" && (
        <p className="text-sm text-destructive">Run failed; the error event is in the trace.</p>
      )}
    </RunWithTrace>
  );
}

function ReplayRun({ runId }: { runId: string }) {
  const { loaded, error } = useReplaySource(runId);
  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!loaded) return <p className="text-sm text-muted-foreground">Loading trace…</p>;
  return <Replay runId={runId} {...loaded} />;
}

export function ReplayView() {
  const { runId } = useParams<{ runId: string }>();
  return <ReplayRun key={runId} runId={runId} />;
}
