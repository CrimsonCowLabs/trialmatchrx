// Pure helpers for the feasibility page: the waterfall joined with leave-one-out, and the
// slider ranges. Only a type import from ./api.ts, so node:test can load this file directly.
import type { FeasibilityResult, Schemas } from "./api.ts";

export type Overrides = NonNullable<Schemas["FeasibilityRequest"]["overrides"]>;
export type ReviewCriterion = Schemas["ReviewCriterion"];

/** One rule of the waterfall, with the patients entering it and its leave-one-out impact. */
export type WaterfallStep = Schemas["WaterfallStep"] & {
  before: number;
  added_if_removed: number;
};

export function waterfallSteps(result: FeasibilityResult): WaterfallStep[] {
  const added = new Map(result.leave_one_out.map((l) => [l.criterion_id, l.added_if_removed]));
  let before = result.cohort_size;
  return result.waterfall.map((w) => {
    const step = { ...w, before, added_if_removed: added.get(w.criterion_id) ?? 0 };
    before = w.remaining;
    return step;
  });
}

/** Patients left after every rule (the whole cohort when the trial has none). */
export function eligibleCount(result: FeasibilityResult): number {
  return result.waterfall.at(-1)?.remaining ?? result.cohort_size;
}

/** The step whose removal would add the most patients: the criterion that shrinks the pool. */
export function biggestBlocker(steps: WaterfallStep[]): WaterfallStep | null {
  return steps.reduce<WaterfallStep | null>(
    (best, s) => (s.added_if_removed > (best?.added_if_removed ?? 0) ? s : best),
    null,
  );
}

const share = (n: number, total: number) =>
  `${total > 0 ? Math.round((10000 * n) / total) / 100 : 0}%`;

/** CSS widths of a waterfall bar on the shared cohort scale: the patients a rule keeps, then
 *  the faint tail it drops. */
export function barWidths(
  counts: Pick<WaterfallStep, "remaining" | "dropped">,
  cohortSize: number,
): { kept: string; dropped: string } {
  return { kept: share(counts.remaining, cohortSize), dropped: share(counts.dropped, cohortSize) };
}

export interface SliderRange {
  min: number;
  max: number;
  step: number;
}

// Plausible clinical ranges per field, in the canonical units of
// api/app/pipeline/predicate_fields.py. A field missing here falls back to [0, 2 x value].
const RANGES: Record<string, SliderRange> = {
  age: { min: 0, max: 100, step: 1 },
  "labs.egfr": { min: 5, max: 120, step: 1 },
  "labs.hba1c": { min: 4, max: 14, step: 0.1 },
  "labs.uacr": { min: 0, max: 5000, step: 10 },
  "labs.upcr": { min: 0, max: 5000, step: 10 },
  "labs.potassium": { min: 2.5, max: 7, step: 0.1 },
  "labs.ldl": { min: 20, max: 300, step: 5 },
  "labs.creatinine": { min: 0.2, max: 10, step: 0.1 },
  "labs.albumin": { min: 1, max: 6, step: 0.1 },
  "labs.alt": { min: 0, max: 300, step: 1 },
  "labs.hscrp": { min: 0, max: 30, step: 0.5 },
  "vitals.bmi": { min: 12, max: 60, step: 0.5 },
  "vitals.sbp": { min: 70, max: 220, step: 1 },
  "vitals.dbp": { min: 40, max: 130, step: 1 },
  "vitals.weight": { min: 30, max: 250, step: 1 },
};

/** Slider bounds for a numeric step: the field's range, widened to include its values. */
export function sliderRange(step: WaterfallStep): SliderRange {
  const values = [step.value, step.default_value].filter((v): v is number => typeof v === "number");
  const base = RANGES[step.field] ?? { min: 0, max: Math.max(1, ...values) * 2, step: 1 };
  return {
    min: Math.min(base.min, ...values),
    max: Math.max(base.max, ...values),
    step: base.step,
  };
}

/** `egfr >= 45 mL/min/1.73m2`-style label for a rule's current predicate. */
export function ruleLabel(step: WaterfallStep): string {
  const field = step.field.split(".").at(-1) ?? step.field;
  const shown = Array.isArray(step.value) ? step.value.join(" / ") : String(step.value);
  const unit = step.unit && step.numeric ? ` ${step.unit}` : "";
  return `${field} ${step.op.replace("_", " ")} ${shown}${unit}`;
}

/** `overrides` with a numeric rule's threshold moved to `value`. Back at the compiled value, or
 *  null, drops the override, so Reset all is just `{}` and "adjusted" means a key is present. */
export function setThreshold(
  overrides: Overrides,
  step: WaterfallStep,
  value: number | null,
): Overrides {
  const next = { ...overrides };
  if (value === null || value === step.default_value) delete next[step.criterion_id];
  else next[step.criterion_id] = value;
  return next;
}

/** Where a numeric rule's slider sits: its override, else the compiled threshold. */
export function thresholdValue(overrides: Overrides, step: WaterfallStep): number {
  const current = overrides[step.criterion_id];
  return typeof current === "number" ? current : Number(step.default_value);
}

/** "8 compiled criteria, 2 need review" for the page header. */
export function criteriaSummary(result: FeasibilityResult): string {
  const compiled = result.waterfall.length;
  const review = result.review_criteria.length;
  const rules = `${compiled} compiled ${compiled === 1 ? "criterion" : "criteria"}`;
  if (review === 0) return `${rules}, none need review`;
  return `${rules}, ${review} ${review === 1 ? "needs" : "need"} review`;
}

export interface ReviewSummary {
  patients: number; // pass every rule but still face the criteria below by hand
  allEligible: boolean; // every patient who passes the rules still needs review
  criteria: ReviewCriterion[];
}

/** The criteria with no rule and the patients still facing them, or null when every criterion
 *  compiled. Review is never counted as passed: these patients are not "eligible". */
export function reviewSummary(result: FeasibilityResult): ReviewSummary | null {
  if (result.review_criteria.length === 0) return null;
  return {
    patients: result.needs_review,
    allEligible: result.needs_review > 0 && result.needs_review === eligibleCount(result),
    criteria: result.review_criteria,
  };
}
