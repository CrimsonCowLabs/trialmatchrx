"use client";

import { useState, type ReactNode } from "react";

import { AccessBarrierTag } from "@/components/AccessBarrierTag";
import { formatCount } from "@/lib/format";
import {
  barWidths,
  cohortShare,
  ruleLabel,
  type ReviewSummary,
  type WaterfallStep,
} from "@/lib/feasibility";

// Bars are plain divs on one shared scale (the cohort size): one series, so one ink. Remaining
// is solid, the patients a rule drops are the faint tail, and "needs review" is hatched so it
// never reads as part of the eligible count.
const HATCH =
  "repeating-linear-gradient(135deg, var(--color-muted-foreground) 0 2px, transparent 2px 6px)";

// Criterion · bar (+ slider) · numbers, from sm up; stacked below sm.
const COLUMNS = "sm:grid sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)_12rem] sm:gap-6";

function Bar({ step, cohortSize }: { step: WaterfallStep; cohortSize: number }) {
  const { kept, dropped } = barWidths(step, cohortSize);
  return (
    <div className="flex h-2.5 w-full gap-0.5 sm:h-3.5" aria-hidden>
      <div className="rounded-r-sm bg-primary transition-[width] duration-200" style={{ width: kept }} />
      {step.dropped > 0 && (
        <div
          className="rounded-r-sm bg-primary/20 transition-[width] duration-200"
          style={{ width: dropped }}
        />
      )}
    </div>
  );
}

function Row({
  step,
  cohortSize,
  eligible,
  blocker,
  control,
}: {
  step: WaterfallStep;
  cohortSize: number;
  eligible: number;
  blocker: boolean;
  control: ReactNode;
}) {
  // Below sm a numeric rule's slider is behind "Adjust"; from sm up it is always inline.
  const [adjusting, setAdjusting] = useState(false);
  const added = step.added_if_removed;
  return (
    <li
      data-testid="waterfall-row"
      data-criterion={step.criterion_id}
      className={`flex flex-col gap-2 border-b border-line-soft px-4 py-3 sm:items-center sm:px-5 sm:py-3.5 ${COLUMNS} ${blocker ? "bg-teal-selected" : ""}`}
      title={
        `${step.before} in, ${step.dropped} dropped, ${step.remaining} remain. ` +
        `Without this rule: ${eligible + added} pass every rule (+${added}).`
      }
    >
      <div className="flex min-w-0 items-baseline justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium sm:text-[0.9375rem]">
            <span className="mr-2 font-mono text-xs font-normal text-ink-5">{step.criterion_id}</span>
            {step.text} <AccessBarrierTag barrier={step.access_barrier} />
          </div>
          <div className="mt-0.5 hidden flex-wrap items-center gap-2 text-[0.8125rem] text-ink-4 sm:flex">
            {step.type}
            {step.missing > 0 &&
              ` · ${step.missing} with no data ${step.type === "inclusion" ? "(dropped)" : "(kept)"}`}
            {blocker && <BlockerTag />}
          </div>
        </div>
        <span className="font-mono text-sm font-semibold tabular-nums sm:hidden">
          {formatCount(step.remaining)}
        </span>
      </div>
      <div className="flex flex-col gap-2">
        <Bar step={step} cohortSize={cohortSize} />
        {step.numeric && (
          <>
            <div className="flex items-center justify-between font-mono text-xs text-ink-2 sm:hidden">
              <span>{ruleLabel(step)}</span>
              <button
                type="button"
                className="font-sans font-medium link"
                aria-expanded={adjusting}
                onClick={() => setAdjusting((a) => !a)}
              >
                {adjusting ? "Done" : "Adjust"}
              </button>
            </div>
            <div className={`${adjusting ? "block" : "hidden"} sm:block`}>{control}</div>
          </>
        )}
      </div>
      <div className="hidden text-right font-mono text-[0.8125rem] tabular-nums sm:block">
        <span className="text-base font-semibold">{formatCount(step.remaining)}</span>{" "}
        <span className="text-ink-5">−{formatCount(step.dropped)}</span>{" "}
        <span className={added > 0 ? "font-medium text-teal-strong" : "text-ink-5"}>
          +{formatCount(added)}
        </span>
      </div>
    </li>
  );
}

function BlockerTag() {
  return (
    <span className="rounded-full bg-teal-tint px-2 py-0.5 text-[0.6875rem] font-medium text-teal-strong">
      biggest blocker
    </span>
  );
}

export function Waterfall({
  cohortSize,
  steps,
  eligible,
  blockerId,
  review,
  control,
}: {
  cohortSize: number;
  steps: WaterfallStep[];
  eligible: number; // patients left after every rule
  blockerId: string | null;
  review: ReviewSummary | null;
  control: (step: WaterfallStep) => ReactNode; // the threshold slider for a numeric rule
}) {
  return (
    <section
      aria-label="Waterfall"
      className="overflow-hidden rounded-card border bg-card"
      data-testid="waterfall"
    >
      <div
        className={`hidden border-b border-line-soft px-5 py-3 text-xs font-medium tracking-wider text-ink-4 uppercase ${COLUMNS}`}
      >
        <span>Criterion</span>
        <span>Remaining of {formatCount(cohortSize)}</span>
        <span className="text-right whitespace-nowrap">Remain · drop · if removed</span>
      </div>
      <ol>
        {steps.map((s) => (
          <Row
            key={s.criterion_id}
            step={s}
            cohortSize={cohortSize}
            eligible={eligible}
            blocker={s.criterion_id === blockerId}
            control={s.numeric ? control(s) : null}
          />
        ))}
      </ol>
      {review && (
        <div
          className={`m-3 flex flex-col gap-2 rounded-lg border border-dashed border-line-strong px-4 py-3.5 sm:items-start ${COLUMNS}`}
          data-testid="needs-review"
          title={`${review.patients} pass every rule but still have to be checked by hand`}
        >
          <div className="flex items-baseline justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-medium sm:text-[0.9375rem]">Needs review</div>
              <div className="mt-0.5 text-[0.8125rem] text-ink-4">Never counted as passed:</div>
              <ul className="mt-1 flex flex-col gap-1 text-[0.8125rem] text-ink-3">
                {review.criteria.map((r) => (
                  <li key={r.criterion_id}>
                    <span className="mr-1.5 font-mono text-ink-5">{r.criterion_id}</span>
                    {r.text} <AccessBarrierTag barrier={r.access_barrier} />
                  </li>
                ))}
              </ul>
            </div>
            <span className="font-mono text-sm font-semibold tabular-nums sm:hidden">
              {formatCount(review.patients)}
            </span>
          </div>
          <div className="h-2.5 sm:mt-1 sm:h-3.5" aria-hidden>
            <div
              className="h-full rounded-r-sm border border-muted-foreground/60 transition-[width] duration-200"
              style={{
                width: cohortShare(review.patients, cohortSize),
                backgroundImage: HATCH,
              }}
            />
          </div>
          <div className="hidden text-right font-mono text-base font-semibold tabular-nums sm:block">
            {formatCount(review.patients)}
          </div>
        </div>
      )}
    </section>
  );
}
