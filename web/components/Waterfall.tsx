"use client";

import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import type { ReviewCriterion, WaterfallStep } from "@/lib/feasibility";

// Bars are plain divs on one shared scale (the cohort size): one series, so one ink. Remaining
// is solid, the patients a rule drops are the faint tail, and "needs review" is hatched so it
// never reads as part of the eligible count.
const HATCH =
  "repeating-linear-gradient(135deg, var(--color-muted-foreground) 0 2px, transparent 2px 6px)";

const pct = (n: number, total: number) => `${total ? (100 * n) / total : 0}%`;

function Bar({ kept, dropped, total }: { kept: number; dropped: number; total: number }) {
  return (
    <div className="flex h-4 w-full gap-0.5" aria-hidden>
      <div
        className="rounded-r-sm bg-primary transition-[width] duration-200"
        style={{ width: pct(kept, total) }}
      />
      {dropped > 0 && (
        <div
          className="rounded-r-sm bg-primary/15 transition-[width] duration-200"
          style={{ width: pct(dropped, total) }}
        />
      )}
    </div>
  );
}

function Row({
  label,
  detail,
  bar,
  numbers,
  control,
  tooltip,
}: {
  label: ReactNode;
  detail?: ReactNode;
  bar: ReactNode;
  numbers: ReactNode;
  control?: ReactNode;
  tooltip: string;
}) {
  return (
    <li
      className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_9rem] items-center gap-x-4 gap-y-1 rounded-sm px-2 py-2 hover:bg-muted/60"
      title={tooltip}
    >
      <div className="min-w-0 text-sm">
        <div className="truncate">{label}</div>
        {detail && <div className="text-xs text-muted-foreground">{detail}</div>}
      </div>
      <div className="flex flex-col gap-1.5">
        {bar}
        {control}
      </div>
      <div className="text-right text-xs tabular-nums">{numbers}</div>
    </li>
  );
}

export function Waterfall({
  cohortSize,
  steps,
  eligible,
  blockerId,
  needsReview,
  reviewCriteria,
  control,
}: {
  cohortSize: number;
  steps: WaterfallStep[];
  eligible: number; // patients left after every rule
  blockerId: string | null;
  needsReview: number;
  reviewCriteria: ReviewCriterion[];
  control: (step: WaterfallStep) => ReactNode; // the threshold slider for a numeric rule
}) {
  return (
    <div className="flex flex-col gap-4">
      <ol className="flex flex-col">
        <Row
          label={<span className="font-medium">Synthetic cohort</span>}
          bar={<Bar kept={cohortSize} dropped={0} total={cohortSize} />}
          numbers={<span className="text-sm font-medium">{cohortSize}</span>}
          tooltip={`${cohortSize} Synthea patients`}
        />
        {steps.map((s) => (
          <Row
            key={s.criterion_id}
            label={
              <>
                <span className="mr-1.5 font-mono text-xs text-muted-foreground">
                  {s.criterion_id}
                </span>
                {s.text}
              </>
            }
            detail={
              <span className="flex flex-wrap items-center gap-1.5">
                {s.type}
                {s.missing > 0 && (
                  <span>
                    · {s.missing} with no data {s.type === "inclusion" ? "(dropped)" : "(kept)"}
                  </span>
                )}
                {s.criterion_id === blockerId && <Badge variant="outline">biggest blocker</Badge>}
              </span>
            }
            bar={<Bar kept={s.remaining} dropped={s.dropped} total={cohortSize} />}
            control={s.numeric ? control(s) : undefined}
            numbers={
              <>
                <div className="text-sm font-medium">{s.remaining}</div>
                <div className="text-muted-foreground">−{s.dropped}</div>
                <div className={s.added_if_removed > 0 ? "" : "text-muted-foreground"}>
                  +{s.added_if_removed} if dropped
                </div>
              </>
            }
            tooltip={
              `${s.before} in, ${s.dropped} dropped, ${s.remaining} remain. ` +
              `Without this rule: ${eligible + s.added_if_removed} eligible (+${s.added_if_removed}).`
            }
          />
        ))}
        <Row
          label={<span className="font-medium">Eligible on every rule</span>}
          bar={<Bar kept={eligible} dropped={0} total={cohortSize} />}
          numbers={<span className="text-sm font-semibold">{eligible}</span>}
          tooltip={`${eligible} of ${cohortSize} pass every criterion that has a rule`}
        />
      </ol>

      <section className="flex flex-col gap-2 rounded-md border border-dashed p-2">
        <Row
          label={<span className="font-medium">Needs review</span>}
          detail={`${reviewCriteria.length} criteria have no rule; never counted as passed`}
          bar={
            <div className="h-4 w-full" aria-hidden>
              <div
                className="h-full rounded-r-sm border border-muted-foreground/60"
                style={{ width: pct(needsReview, cohortSize), backgroundImage: HATCH }}
              />
            </div>
          }
          numbers={<span className="text-sm font-medium">{needsReview}</span>}
          tooltip={`${needsReview} patients pass every rule but still have to be checked by hand`}
        />
        {reviewCriteria.length > 0 && (
          <ul className="flex flex-col gap-1 px-2 pb-1 text-xs text-muted-foreground">
            {reviewCriteria.map((r) => (
              <li key={r.criterion_id}>
                <span className="mr-1.5 font-mono">{r.criterion_id}</span>
                {r.text}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
