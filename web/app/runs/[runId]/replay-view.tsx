"use client";

// Replays a finished run from GET /api/runs/{run_id}/trace: every emission in seq order
// (`replayEmissions`), with the original gaps capped at 0.2 s, through the same panel and
// results as the live page. The replay bar's state is `replayReducer` (lib/replay.ts).
import { Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useReducer, type Dispatch } from "react";

import { RunWithTrace } from "@/components/RunWithTrace";
import { api, type RunSummary, type TraceEvent } from "@/lib/api";
import {
  INITIAL_REPLAY,
  REPLAY_SPEEDS,
  replayPosition,
  replayReducer,
  type ReplayAction,
  type ReplayState,
} from "@/lib/replay";
import { replayDelays, replayEmissions } from "@/lib/trace";
import { useLoad } from "@/lib/use-load";

const GAP_CAP_MS = 200;

interface Loaded {
  trace: TraceEvent[];
  summary: RunSummary;
}

const OUTLINED =
  "inline-flex h-9 items-center gap-1.5 rounded-lg border border-replay-line px-3.5 text-sm font-medium hover:bg-replay-sunken disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4";

/** Design 07's dark replay bar: Pause / Play, Restart, Skip to end, a progress bar, the
 *  1x / 4x / 16x speeds and "seq N / M". */
function ReplayBar({
  state,
  emissions,
  dispatch,
}: {
  state: ReplayState;
  emissions: TraceEvent[];
  dispatch: Dispatch<ReplayAction>;
}) {
  const finished = state.index >= emissions.length;
  const running = state.playing && !finished;
  const { seq, lastSeq, fraction } = replayPosition(emissions, state.index);
  return (
    <div
      className="flex flex-wrap items-center gap-x-3.5 gap-y-3 rounded-card bg-replay px-4 py-3.5 text-white"
      data-testid="replay-controls"
    >
      <button
        type="button"
        onClick={() => dispatch({ type: "toggle" })}
        disabled={finished}
        className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-white px-3.5 text-sm font-medium text-ink hover:bg-white/90 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4"
      >
        {running ? <Pause /> : <Play />} {running ? "Pause" : "Play"}
      </button>
      <button type="button" onClick={() => dispatch({ type: "restart" })} className={OUTLINED}>
        <RotateCcw /> Restart
      </button>
      <button
        type="button"
        onClick={() => dispatch({ type: "skip", emissions })}
        disabled={finished}
        className={OUTLINED}
      >
        <SkipForward /> Skip to end
      </button>
      <div
        role="progressbar"
        aria-label="Replay position"
        aria-valuemin={0}
        aria-valuemax={lastSeq}
        aria-valuenow={seq}
        className="relative order-last h-1 w-full rounded-full bg-replay-line sm:order-none sm:mx-2 sm:w-auto sm:min-w-16 sm:flex-1"
      >
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-replay-progress"
          style={{ width: `${fraction * 100}%` }}
        />
      </div>
      <div
        role="group"
        aria-label="Replay speed"
        className="flex rounded-lg bg-replay-sunken p-0.5 font-mono text-[0.8125rem] font-medium"
      >
        {REPLAY_SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={s === state.speed}
            onClick={() => dispatch({ type: "speed", speed: s })}
            className={`rounded-md px-2.5 py-1 ${s === state.speed ? "bg-replay-line" : "text-replay-muted hover:text-white"}`}
          >
            {s}x
          </button>
        ))}
      </div>
      <span
        className="font-mono text-[0.8125rem] text-replay-muted tabular-nums"
        data-testid="replay-position"
      >
        seq {seq} / {lastSeq}
      </span>
    </div>
  );
}

function Replay({ runId, trace, summary }: { runId: string } & Loaded) {
  const emissions = useMemo(() => replayEmissions(trace), [trace]);
  const delays = useMemo(() => replayDelays(emissions, GAP_CAP_MS), [emissions]);
  const [state, dispatch] = useReducer(replayReducer, INITIAL_REPLAY);
  const finished = state.index >= emissions.length;
  const running = state.playing && !finished;

  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(
      () => dispatch({ type: "tick", emissions }),
      delays[state.index] / state.speed,
    );
    return () => clearTimeout(timer);
  }, [running, state.index, state.speed, emissions, delays]);

  const stillRecording = summary.status === "running";
  const isCloser = summary.kind === "closer";
  return (
    <RunWithTrace
      runId={runId}
      events={state.events}
      live={false}
      status={{
        label: finished ? "replayed" : `replay ${state.index}/${emissions.length}`,
        variant: finished ? "secondary" : "outline",
      }}
      summary={summary}
      matches={finished && summary.status === "done" && !isCloser ? summary.matches : null}
      closer={finished ? (summary.closer ?? null) : null}
      totals={finished ? summary.totals : null}
      runStatus={summary.status}
      link={{
        href: `/${isCloser ? "closer" : "match"}/${encodeURIComponent(runId)}`,
        label: "Live view",
      }}
      title={isCloser ? "Next steps replay" : "Run replay"}
      breadcrumb={[{ label: "Runs", href: "/runs" }, { label: "Replay" }]}
    >
      {stillRecording && (
        <p className="text-sm text-verdict-unknown">
          This run is still running; the replay stops at what has been recorded so far.
        </p>
      )}
      <ReplayBar state={state} emissions={emissions} dispatch={dispatch} />
    </RunWithTrace>
  );
}

function ReplayRun({ runId }: { runId: string }) {
  const load = useCallback(
    async (): Promise<Loaded> => {
      const [trace, summary] = await Promise.all([api.getTrace(runId), api.getRun(runId)]);
      return { trace, summary };
    },
    [runId],
  );
  const { data: loaded, error } = useLoad(load);
  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!loaded) return <p className="text-sm text-muted-foreground">Loading trace…</p>;
  return <Replay runId={runId} {...loaded} />;
}

export function ReplayView() {
  const { runId } = useParams<{ runId: string }>();
  return <ReplayRun key={runId} runId={runId} />;
}
