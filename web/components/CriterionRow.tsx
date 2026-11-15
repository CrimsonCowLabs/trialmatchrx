// One criterion's verdict: outcome icon, the trial's quote, the patient evidence and why.
// Outcomes are relative to eligibility (an exclusion that applies is a `fail`), so the labels
// say "OK" / "Disqualifies", never "met" / "not met", which would read backwards for exclusions.
// Self-contained on purpose: badges (e.g. "unverified quote") and the "Why?" link go here.
"use client";

import { CircleCheck, CircleQuestionMark, CircleX, type LucideIcon } from "lucide-react";
import { useEffect, useRef } from "react";

import { UnverifiedQuoteBadge } from "@/components/UnverifiedQuoteBadge";
import type { Schemas } from "@/lib/api";

export type Verdict = Schemas["Verdict"];

const OUTCOME: Record<Verdict["outcome"], { icon: LucideIcon; label: string; color: string }> = {
  pass: { icon: CircleCheck, label: "OK", color: "text-emerald-600" },
  fail: { icon: CircleX, label: "Disqualifies", color: "text-red-600" },
  unknown: { icon: CircleQuestionMark, label: "Unknown", color: "text-amber-500" },
};

export function CriterionRow({
  verdict,
  highlighted = false,
  onWhy,
}: {
  verdict: Verdict;
  /** The selected trace event produced this verdict. */
  highlighted?: boolean;
  /** "Why?": jump to the trace event that produced this verdict. */
  onWhy?: (traceEventId: string) => void;
}) {
  const { icon: Icon, label, color } = OUTCOME[verdict.outcome];
  const exclusion = verdict.criterion_id.startsWith("exc");
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    // Instant, so it can't cancel the trace panel's smooth scroll started in the same commit
    // after "Why?"; `nearest` is a no-op when the row is already on screen.
    if (highlighted) ref.current?.scrollIntoView({ block: "nearest" });
  }, [highlighted]);
  return (
    <li
      ref={ref}
      data-testid="criterion-row"
      data-outcome={verdict.outcome}
      data-trace-event-id={verdict.trace_event_id}
      data-highlighted={highlighted || undefined}
      className={`flex gap-2 border-b py-1.5 last:border-b-0 ${highlighted ? "-mx-3 bg-sky-50 px-3 ring-1 ring-sky-400 ring-inset dark:bg-sky-950" : ""}`}
    >
      <Icon className={`mt-0.5 size-4 shrink-0 ${color}`} aria-label={label} role="img" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="text-sm">
          <span className="mr-1.5 font-mono text-xs text-muted-foreground">
            {verdict.criterion_id}
            {exclusion ? " (excl.)" : ""}
          </span>
          {verdict.criterion_quote}{" "}
          <UnverifiedQuoteBadge verified={verdict.verified} />
        </p>
        <p className="text-xs text-muted-foreground">
          {verdict.patient_evidence && (
            <>
              <span className="italic">“{verdict.patient_evidence}”</span> ·{" "}
            </>
          )}
          {verdict.rationale}
        </p>
      </div>
      {onWhy && (
        <button
          type="button"
          onClick={() => onWhy(verdict.trace_event_id)}
          className="self-start text-xs text-sky-700 underline-offset-2 hover:underline dark:text-sky-400"
          title="Show the trace event that produced this verdict"
        >
          Why?
        </button>
      )}
    </li>
  );
}
