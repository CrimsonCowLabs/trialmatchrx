"use client";

import { useParams } from "next/navigation";
import { useState } from "react";

import { ThresholdSlider } from "@/components/ThresholdSlider";
import { Waterfall } from "@/components/Waterfall";
import { Button } from "@/components/ui/button";
import { api, errorMessage } from "@/lib/api";
import { biggestBlocker, eligibleCount, type Overrides, waterfallSteps } from "@/lib/feasibility";
import { useFeasibility } from "@/lib/use-feasibility";

function CompileTrial({ nct, onCompiled }: { nct: string; onCompiled: () => void }) {
  const [compiling, setCompiling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const compile = () => {
    setCompiling(true);
    setError(null);
    api.compileTrial(nct).then(onCompiled, (err: unknown) => {
      setCompiling(false);
      setError(errorMessage(err));
    });
  };
  return (
    <div className="flex flex-col items-start gap-2 text-sm">
      <p>{nct} hasn&apos;t been compiled into predicates yet.</p>
      <Button onClick={compile} disabled={compiling}>
        {compiling ? "Compiling…" : "Compile criteria"}
      </Button>
      {error && <p className="text-destructive">{error}</p>}
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
              / {result.cohort_size} pass every rule
            </span>
          </div>
        </div>
        <div className="text-sm">
          <div className="tabular-nums">
            {result.review_criteria.length > 0
              ? `all ${result.needs_review} still need review on ${result.review_criteria.length} criteria without a rule`
              : "every criterion has a rule: nothing left to review"}
          </div>
          {blocker && (
            <div className="text-muted-foreground">
              Dropping {blocker.criterion_id} would add {blocker.added_if_removed}
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
        eligible={eligible}
        blockerId={blocker?.criterion_id ?? null}
        needsReview={result.needs_review}
        reviewCriteria={result.review_criteria}
        control={(s) => {
          const current = overrides[s.criterion_id];
          return (
            <ThresholdSlider
              step={s}
              value={typeof current === "number" ? current : Number(s.default_value)}
              onChange={(v) => setThreshold(s.criterion_id, v)}
              onReset={() => setThreshold(s.criterion_id, null)}
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
