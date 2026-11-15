"use client";

import { useParams } from "next/navigation";
import { useCallback, useState, type ReactNode } from "react";

import { PageHeader } from "@/components/PageHeader";
import { ThresholdSlider } from "@/components/ThresholdSlider";
import { TrialStatus } from "@/components/TrialStatus";
import { formatCount, Waterfall } from "@/components/Waterfall";
import { Button } from "@/components/ui/button";
import { api, errorMessage, type FeasibilityResult, type TrialDetail } from "@/lib/api";
import {
  biggestBlocker,
  criteriaSummary,
  eligibleCount,
  type Overrides,
  reviewSummary,
  ruleLabel,
  setThreshold,
  thresholdValue,
  waterfallSteps,
} from "@/lib/feasibility";
import { useFeasibility } from "@/lib/use-feasibility";
import { useLoad } from "@/lib/use-load";

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

/** "PHASE3 · ● RECRUITING · 8 compiled criteria, 2 need review"; each part only once known. */
function TrialMeta({ trial, result }: { trial: TrialDetail | null; result: FeasibilityResult | null }) {
  const parts: ReactNode[] = [];
  if (trial?.phase) parts.push(trial.phase);
  if (trial?.overall_status) parts.push(<TrialStatus status={trial.overall_status} />);
  if (result) parts.push(criteriaSummary(result));
  if (parts.length === 0) return null;
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1" data-testid="trial-meta">
      {parts.map((p, i) => (
        <span key={i} className="inline-flex items-center gap-2">
          {i > 0 && <span aria-hidden>·</span>}
          {p}
        </span>
      ))}
    </span>
  );
}

function Figure({
  label,
  children,
  dashed = false,
  testId,
}: {
  label: string;
  children: ReactNode;
  dashed?: boolean;
  testId: string;
}) {
  return (
    <div
      className={`rounded-card border bg-card px-5 py-4 sm:py-5 ${dashed ? "border-dashed border-line-strong" : ""}`}
      data-testid={testId}
    >
      <div className="text-[0.8125rem] font-medium text-ink-4">{label}</div>
      {children}
    </div>
  );
}

function Feasibility({ nct }: { nct: string }) {
  // Slider positions, applied immediately on screen; the API call follows debounced.
  const [overrides, setOverrides] = useState<Overrides>({});
  const [reloadKey, setReloadKey] = useState(0);
  const { result, error, loading, latencyMs } = useFeasibility(nct, overrides, reloadKey);
  // Title, phase and status; the page still works (titled by NCT ID) if this fails.
  const { data: trial } = useLoad(useCallback(() => api.getTrial(nct), [nct]));
  const adjusted = Object.keys(overrides).length > 0;

  const header = (
    <PageHeader
      breadcrumb={[{ label: "Trials", href: "/trials" }]}
      trail={<span className="font-mono break-all text-foreground">{nct}</span>}
      title={trial?.title ?? "Trial feasibility"}
      description={<TrialMeta trial={trial} result={result} />}
      actions={
        result && (
          <>
            {/* The measured round trip of the answer on screen (useFeasibility). */}
            <span
              className="font-mono text-[0.8125rem] text-ink-4 tabular-nums"
              aria-live="polite"
              title="Round trip of the last feasibility request"
              data-testid="latency"
            >
              {loading ? "updating…" : latencyMs !== null && `${latencyMs} ms`}
            </span>
            <Button
              variant="link"
              size="xs"
              className="px-0 text-sm"
              onClick={() => setOverrides({})}
              disabled={!adjusted}
            >
              Reset all
            </Button>
          </>
        )
      }
    />
  );

  if (error?.status === 404 && !result) {
    return (
      <>
        {header}
        <CompileTrial nct={nct} onCompiled={() => setReloadKey((k) => k + 1)} />
      </>
    );
  }
  if (!result) {
    return (
      <>
        {header}
        {error ? (
          <p className="text-sm text-destructive">{error.message}</p>
        ) : (
          <p className="text-sm text-muted-foreground">Running the cohort…</p>
        )}
      </>
    );
  }

  const steps = waterfallSteps(result);
  const eligible = eligibleCount(result);
  const blocker = biggestBlocker(steps);
  const review = reviewSummary(result);
  const cohort = formatCount(result.cohort_size);

  return (
    <>
      {header}
      {error && <p className="text-sm text-destructive">{error.message}</p>}

      {/* Desktop: three figures. */}
      <div className="hidden gap-4 sm:grid sm:grid-cols-3">
        <Figure label="Pass every rule" testId="figure-eligible">
          <div className="mt-1 font-mono text-4xl font-semibold tracking-tight tabular-nums">
            {formatCount(eligible)}
            <span className="font-sans text-lg font-normal text-ink-5"> / {cohort}</span>
          </div>
        </Figure>
        <Figure label="Biggest blocker" testId="figure-blocker">
          {blocker ? (
            <>
              <div className="mt-2 text-xl font-semibold">
                {blocker.criterion_id} · {ruleLabel(blocker)}
              </div>
              <div className="mt-1 text-sm text-ink-2">
                Dropping it would add{" "}
                <span className="font-semibold text-teal-strong">
                  +{formatCount(blocker.added_if_removed)}
                </span>
              </div>
            </>
          ) : (
            <>
              <div className="mt-2 text-xl font-semibold">None</div>
              <div className="mt-1 text-sm text-ink-2">Dropping any one rule adds nobody</div>
            </>
          )}
        </Figure>
        <Figure label="Still need review" dashed testId="figure-review">
          {review ? (
            <>
              <div className="mt-2 text-xl font-semibold">
                {review.allEligible ? `All ${formatCount(review.patients)}` : formatCount(review.patients)}
              </div>
              <div className="mt-1 text-sm text-ink-2">
                on {review.criteria.length} {review.criteria.length === 1 ? "criterion" : "criteria"}{" "}
                without a rule:{" "}
                {review.criteria.map((r, i) => (
                  <span key={r.criterion_id} className="font-mono whitespace-nowrap">
                    {r.criterion_id}
                    {i < review.criteria.length - 1 && ", "}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="mt-2 text-xl font-semibold">None</div>
              <div className="mt-1 text-sm text-ink-2">Every criterion has a rule</div>
            </>
          )}
        </Figure>
      </div>

      {/* Mobile: the count and the one rule worth dropping, side by side. */}
      <div className="grid grid-cols-2 gap-3 rounded-card border bg-card p-4 sm:hidden" data-testid="figures-compact">
        <div>
          <div className="text-xs font-medium text-ink-4">Pass every rule</div>
          <div className="font-mono text-3xl font-semibold tabular-nums">
            {formatCount(eligible)}
            <span className="font-sans text-[0.9375rem] font-normal text-ink-5"> / {cohort}</span>
          </div>
        </div>
        {blocker && (
          <div>
            <div className="text-xs font-medium text-ink-4">Drop {blocker.criterion_id}</div>
            <div className="font-mono text-3xl font-semibold text-teal-strong tabular-nums">
              +{formatCount(blocker.added_if_removed)}
            </div>
          </div>
        )}
      </div>

      <Waterfall
        cohortSize={result.cohort_size}
        steps={steps}
        eligible={eligible}
        blockerId={blocker?.criterion_id ?? null}
        review={review}
        control={(s) => (
          <ThresholdSlider
            step={s}
            value={thresholdValue(overrides, s)}
            onChange={(v) => setOverrides((o) => setThreshold(o, s, v))}
            onReset={() => setOverrides((o) => setThreshold(o, s, null))}
          />
        )}
      />
    </>
  );
}

export function FeasibilityView() {
  const { nct } = useParams<{ nct: string }>();
  return <Feasibility key={nct} nct={nct} />;
}
