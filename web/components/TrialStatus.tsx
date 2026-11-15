// A trial's ClinicalTrials.gov overall status with its coloured dot (trials browser, feasibility).
import { trialStatusTone, type TrialStatusTone } from "@/lib/browse";

// Literal class names so Tailwind sees them; colours are the trial-status tokens in globals.css.
const STATUS_DOT = {
  recruiting: "bg-trial-recruiting",
  "not-yet": "bg-trial-not-yet",
  other: "bg-trial-other",
} as const satisfies Record<TrialStatusTone, string>;

export function TrialStatus({ status }: { status: string | null }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden className={`size-2 rounded-full ${STATUS_DOT[trialStatusTone(status)]}`} />
      {status ?? "–"}
    </span>
  );
}
