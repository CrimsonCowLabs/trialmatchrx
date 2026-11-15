// Pure helpers for the feasibility page: typed views of FeasibilityResult's dict rows and the
// slider ranges. Only a type import from ./api.ts, so node:test can load this file directly.
import type { Schemas } from "./api.ts";

export type FeasibilityResult = Schemas["FeasibilityResult"];
export type Overrides = NonNullable<Schemas["FeasibilityRequest"]["overrides"]>;

/** One rule of the waterfall, merged with its leave-one-out impact. */
export interface WaterfallStep {
  criterionId: string;
  text: string;
  type: "inclusion" | "exclusion";
  field: string;
  op: string;
  value: number | string | string[];
  defaultValue: number | string | string[] | null;
  unit: string | null;
  numeric: boolean;
  before: number; // patients entering this step
  remaining: number;
  dropped: number;
  missing: number; // patients with no data for it (dropped on an inclusion, kept on an exclusion)
  addedIfRemoved: number;
}

export interface ReviewCriterion {
  criterionId: string;
  text: string;
  type: "inclusion" | "exclusion";
}

const str = (v: unknown): string => (typeof v === "string" ? v : String(v ?? ""));
const num = (v: unknown): number => (typeof v === "number" ? v : 0);
const value = (v: unknown): number | string | string[] =>
  typeof v === "number" || Array.isArray(v) ? (v as number | string[]) : str(v);
const kind = (v: unknown): "inclusion" | "exclusion" =>
  v === "exclusion" ? "exclusion" : "inclusion";

export function waterfallSteps(result: FeasibilityResult): WaterfallStep[] {
  const added = new Map(
    result.leave_one_out.map((l) => [str(l.criterion_id), num(l.added_if_removed)]),
  );
  let before = result.cohort_size;
  return result.waterfall.map((w) => {
    const step: WaterfallStep = {
      criterionId: str(w.criterion_id),
      text: str(w.text),
      type: kind(w.type),
      field: str(w.field),
      op: str(w.op),
      value: value(w.value),
      defaultValue: w.default_value == null ? null : value(w.default_value),
      unit: typeof w.unit === "string" ? w.unit : null,
      numeric: w.numeric === true,
      before,
      remaining: num(w.remaining),
      dropped: num(w.dropped),
      missing: num(w.missing),
      addedIfRemoved: added.get(str(w.criterion_id)) ?? 0,
    };
    before = step.remaining;
    return step;
  });
}

export function reviewCriteria(result: FeasibilityResult): ReviewCriterion[] {
  return result.review_criteria.map((r) => ({
    criterionId: str(r.criterion_id),
    text: str(r.text),
    type: kind(r.type),
  }));
}

/** Patients left after every rule (the whole cohort when the trial has none). */
export function eligibleCount(result: FeasibilityResult): number {
  const last = result.waterfall.at(-1);
  return last ? num(last.remaining) : result.cohort_size;
}

/** The step whose removal would add the most patients: the criterion that shrinks the pool. */
export function biggestBlocker(steps: WaterfallStep[]): WaterfallStep | null {
  return steps.reduce<WaterfallStep | null>(
    (best, s) => (s.addedIfRemoved > (best?.addedIfRemoved ?? 0) ? s : best),
    null,
  );
}

export interface SliderRange {
  min: number;
  max: number;
  step: number;
}

// Plausible clinical ranges per field, in the canonical units of api/app/pipeline/predicate_fields.py.
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
  const values = [step.value, step.defaultValue].filter((v): v is number => typeof v === "number");
  const base = RANGES[step.field] ?? {
    min: 0,
    max: Math.max(1, ...values) * 2,
    step: 1,
  };
  return {
    min: Math.min(base.min, ...values),
    max: Math.max(base.max, ...values),
    step: base.step,
  };
}

/** `eGFR >= 45 mL/min/1.73m2`-style label for a rule's current predicate. */
export function ruleLabel(step: WaterfallStep): string {
  const field = step.field.split(".").at(-1) ?? step.field;
  const shown = Array.isArray(step.value) ? step.value.join(" / ") : String(step.value);
  return `${field} ${step.op.replace("_", " ")} ${shown}${step.unit && step.numeric ? ` ${step.unit}` : ""}`;
}
