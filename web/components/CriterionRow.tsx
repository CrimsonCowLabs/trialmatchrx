// One criterion's verdict: outcome icon, the trial's quote, the patient evidence and why.
// Self-contained on purpose: badges (e.g. "unverified quote") and the "Why?" link go here.
import { CircleCheck, CircleQuestionMark, CircleX, type LucideIcon } from "lucide-react";

import type { Schemas } from "@/lib/api";

export type Verdict = Schemas["Verdict"];

const OUTCOME: Record<Verdict["outcome"], { icon: LucideIcon; label: string; color: string }> = {
  pass: { icon: CircleCheck, label: "Met", color: "text-emerald-600" },
  fail: { icon: CircleX, label: "Not met", color: "text-red-600" },
  unknown: { icon: CircleQuestionMark, label: "Unknown", color: "text-amber-500" },
};

export function CriterionRow({ verdict }: { verdict: Verdict }) {
  const { icon: Icon, label, color } = OUTCOME[verdict.outcome];
  const exclusion = verdict.criterion_id.startsWith("exc");
  return (
    <li
      data-testid="criterion-row"
      data-outcome={verdict.outcome}
      data-trace-event-id={verdict.trace_event_id}
      className="flex gap-2 border-b py-1.5 last:border-b-0"
    >
      <Icon className={`mt-0.5 size-4 shrink-0 ${color}`} aria-label={label} role="img" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="text-sm">
          <span className="mr-1.5 font-mono text-xs text-muted-foreground">
            {verdict.criterion_id}
            {exclusion ? " (excl.)" : ""}
          </span>
          {verdict.criterion_quote}
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
    </li>
  );
}
