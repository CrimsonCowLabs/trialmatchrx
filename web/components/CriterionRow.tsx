// One criterion's verdict: outcome icon, the criterion id and the trial's quote, the patient
// evidence and why, how it was decided (rule or LLM) and "Why?".
// Outcomes are relative to eligibility (an exclusion that applies is a `fail`), so the labels
// say "OK" / "Disqualifies", never "met" / "not met", which would read backwards for exclusions.
// Self-contained on purpose: badges (e.g. "unverified quote") and the "Why?" link go here.
"use client";

import { Check, type LucideIcon, QuestionMark, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { AccessBarrierTag } from "@/components/AccessBarrierTag";
import { UnverifiedQuoteBadge } from "@/components/UnverifiedQuoteBadge";
import type { Schemas } from "@/lib/api";

export type Verdict = Schemas["Verdict"];

// Literal class names so Tailwind sees them; colours are the verdict tokens in globals.css.
const OUTCOME: Record<Verdict["outcome"], { icon: LucideIcon; label: string; tone: string }> = {
  pass: { icon: Check, label: "OK", tone: "bg-verdict-pass-bg text-verdict-pass" },
  fail: { icon: X, label: "Disqualifies", tone: "bg-verdict-fail-bg text-verdict-fail" },
  unknown: { icon: QuestionMark, label: "Unknown", tone: "bg-verdict-unknown-bg text-verdict-unknown" },
};

const METHOD: Record<Verdict["method"], { label: string; title: string }> = {
  rule: { label: "rule", title: "Decided by a compiled rule over the patient facts" },
  llm: { label: "LLM", title: "Judged by the LLM from the note and facts" },
};

export function CriterionRow({
  verdict,
  highlighted = false,
  revealNonce,
  onWhy,
  collapsedOnMobile = false,
}: {
  verdict: Verdict;
  /** The selected trace event produced this verdict. */
  highlighted?: boolean;
  /** Bumped by "View verdict" on the mobile trace sheet: scroll this (highlighted) row to the
   *  middle of the screen, even when it was already highlighted. */
  revealNonce?: number;
  /** "Why?": jump to the trace event that produced this verdict. */
  onWhy?: (traceEventId: string) => void;
  /** Behind "Show all N criteria" on a phone (always shown from `lg`). */
  collapsedOnMobile?: boolean;
}) {
  const { icon: Icon, label, tone } = OUTCOME[verdict.outcome];
  const method = METHOD[verdict.method];
  const exclusion = verdict.criterion_id.startsWith("exc");
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    // Instant, so it can't cancel the trace panel's smooth scroll started in the same commit
    // after "Why?"; `nearest` is a no-op when the row is already on screen.
    if (highlighted) ref.current?.scrollIntoView({ block: "nearest" });
  }, [highlighted]);
  useEffect(() => {
    // The Results tab was hidden until this commit, so the row is likely off screen.
    if (highlighted && revealNonce) ref.current?.scrollIntoView({ block: "center" });
  }, [highlighted, revealNonce]);
  return (
    <li
      ref={ref}
      data-testid="criterion-row"
      data-outcome={verdict.outcome}
      data-trace-event-id={verdict.trace_event_id}
      data-highlighted={highlighted || undefined}
      className={`${collapsedOnMobile ? "hidden lg:grid" : "grid"} grid-cols-[1.25rem_minmax(0,1fr)] gap-x-3 gap-y-1 border-b border-line-soft px-4 py-3 last:border-b-0 sm:grid-cols-[1.25rem_minmax(0,1fr)_auto] sm:px-5 ${highlighted ? "bg-teal-selected shadow-[inset_3px_0_0_var(--teal)]" : ""}`}
    >
      <span
        role="img"
        aria-label={label}
        title={label}
        className={`mt-0.5 flex size-5 items-center justify-center rounded-full ${tone}`}
      >
        <Icon className="size-3" strokeWidth={3} aria-hidden />
      </span>
      <div className="flex min-w-0 flex-col gap-1">
        <p className="text-[0.9375rem] font-medium">
          <span className="mr-2 font-mono text-xs font-normal text-ink-5">
            {verdict.criterion_id}
            {exclusion ? " (excl.)" : ""}
          </span>
          {verdict.criterion_quote} <UnverifiedQuoteBadge verified={verdict.verified} />{" "}
          <AccessBarrierTag barrier={verdict.access_barrier} />
        </p>
        <p className="text-[0.8125rem] text-ink-4">
          {verdict.patient_evidence && (
            <>
              <span className="text-ink-2 italic">“{verdict.patient_evidence}”</span>{" "}
            </>
          )}
          {verdict.rationale}
        </p>
      </div>
      <div className="col-start-2 flex items-center gap-2.5 self-start sm:col-start-3">
        <span className="font-mono text-xs text-ink-5" title={method.title}>
          {method.label}
        </span>
        {onWhy && (
          <button
            type="button"
            onClick={() => onWhy(verdict.trace_event_id)}
            className="text-[0.8125rem] font-medium link"
            title="Show the trace event that produced this verdict"
          >
            Why?
          </button>
        )}
      </div>
    </li>
  );
}
