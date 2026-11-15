"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { ThresholdSlider } from "@/components/ThresholdSlider";
import { Waterfall } from "@/components/Waterfall";
import { Button } from "@/components/ui/button";
import { api, errorMessage } from "@/lib/api";
import {
  biggestBlocker,
  eligibleCount,
  type Overrides,
  reviewCriteria,
  waterfallSteps,
} from "@/lib/feasibility";
import { useFeasibility } from "@/lib/use-feasibility";

function CompileTrial({ nct, onCompiled }: { nct: string; onCompiled: () => void }) {
  const [state, setState] = useState<"idle" | "compiling" | string>("idle");
  const compile = () => {
    setState("compiling");
    api.compileTrial(nct).then(onCompiled, (err: unknown) => setState(errorMessage(err)));
  };
  return (
    <div className="flex flex-col items-start gap-2 text-sm">
      <p>{nct} hasn&apos;t been compiled into predicates yet.</p>
      <Button onClick={compile} disabled={state === "compiling"}>
        {state === "compiling" ? "Compiling…" : "Compile criteria"}
      </Button>
      {state !== "idle" && state !== "compiling" && <p className="text-destructive">{state}</p>}
    </div>
  );
}

function Feasibility({ nct }: { nct: string }) {
  // Slider positions, applied immediately on screen; the API call follows debounced.
  const [overrides, setOverrides] = useState<Overrides>({});
  const [reloadKey, setReloadKey] = useState(0);
  const { result, error, loading, latencyMs } = useFeasibility(nct, overrides, reloadKey);

  if (error?.status === 404 && !result) {
    return <CompileTrial nct={nct} onCompiled={() => setReloadKey((k) => k + 1)} />;
  }
  if (!result) {
    return error ? (
      <p className="text-sm text-destructive">{error.message}</p>
    ) : (
      <p className="text-sm text-muted-foreground">Running the cohort…</p>
    );
  }

  const steps = waterfallSteps(result);
  const eligible = eligibleCount(result);
  const blocker = biggestBlocker(steps);
  const setThreshold = (id: string, value: number | null) =>
    setOverrides((o) => {
      const next = { ...o };
      if (value === null) delete next[id];
      else next[id] = value;
      return next;
    });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end gap-x-10 gap-y-2">
        <div>
          <div className="font-mono text-xs text-muted-foreground">{result.nct_id}</div>
          <div className="text-4xl font-semibold tabular-nums">
            {eligible}
            <span className="text-lg font-normal text-muted-foreground">
              {" "}
              / {result.cohort_size} eligible
            </span>
          </div>
        </div>
        <div className="text-sm">
          <div className="tabular-nums">{result.needs_review} need review</div>
          {blocker && (
            <div className="text-muted-foreground">
              Dropping {blocker.criterionId} would add {blocker.addedIfRemoved}
            </div>
          )}
        </div>
        <div className="ml-auto text-xs text-muted-foreground tabular-nums" aria-live="polite">
          {loading ? "updating…" : latencyMs !== null && `${latencyMs} ms`}
          {Object.keys(overrides).length > 0 && (
            <Button variant="link" size="xs" onClick={() => setOverrides({})}>
              Reset all
            </Button>
          )}
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error.message}</p>}
      <Waterfall
        cohortSize={result.cohort_size}
        steps={steps}
        blockerId={blocker?.criterionId ?? null}
        needsReview={result.needs_review}
        reviewCriteria={reviewCriteria(result)}
        control={(s) => {
          const current = overrides[s.criterionId];
          return (
            <ThresholdSlider
              step={s}
              value={typeof current === "number" ? current : Number(s.defaultValue)}
              onChange={(v) => setThreshold(s.criterionId, v)}
              onReset={() => setThreshold(s.criterionId, null)}
            />
          );
        }}
      />
    </div>
  );
}

export function FeasibilityView() {
  const { nct } = useParams<{ nct: string }>();
  return <Feasibility key={nct} nct={nct} />;
}
