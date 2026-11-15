// Unit tests for the feasibility page helpers. Run with `pnpm test` (node:test, no extra deps).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  biggestBlocker,
  eligibleCount,
  type FeasibilityResult,
  reviewCriteria,
  ruleLabel,
  sliderRange,
  waterfallSteps,
} from "./feasibility.ts";

// The shape POST /api/feasibility/{nct} returns (api/tests/test_feasibility.py's fixture cohort).
const RESULT: FeasibilityResult = {
  nct_id: "NCT1",
  cohort_size: 6,
  waterfall: [
    {
      criterion_id: "inc-1",
      text: "T2D",
      type: "inclusion",
      category: "diagnosis",
      field: "conditions",
      op: "has",
      value: "type 2 diabetes",
      default_value: "type 2 diabetes",
      unit: null,
      numeric: false,
      remaining: 5,
      dropped: 1,
      missing: 0,
    },
    {
      criterion_id: "inc-2",
      text: "eGFR >= 60",
      type: "inclusion",
      category: "lab",
      field: "labs.egfr",
      op: ">=",
      value: 45,
      default_value: 60,
      unit: "mL/min/1.73m2",
      numeric: true,
      remaining: 3,
      dropped: 2,
      missing: 1,
    },
  ],
  leave_one_out: [
    { criterion_id: "inc-1", added_if_removed: 1 },
    { criterion_id: "inc-2", added_if_removed: 2 },
  ],
  needs_review: 3,
  review_criteria: [{ criterion_id: "inc-3", text: "Stable kidney function", type: "inclusion" }],
};

test("steps chain each rule's input to the previous rule's output and carry leave-one-out", () => {
  const steps = waterfallSteps(RESULT);
  assert.deepEqual(
    steps.map((s) => [s.criterionId, s.before, s.remaining, s.dropped, s.addedIfRemoved]),
    [
      ["inc-1", 6, 5, 1, 1],
      ["inc-2", 5, 3, 2, 2],
    ],
  );
  assert.equal(steps[1].value, 45);
  assert.equal(steps[1].defaultValue, 60);
  assert.equal(steps[1].numeric, true);
});

test("eligible is the last step's remaining, or the whole cohort with no rules", () => {
  assert.equal(eligibleCount(RESULT), 3);
  assert.equal(eligibleCount({ ...RESULT, waterfall: [], leave_one_out: [] }), 6);
});

test("the biggest blocker is the rule whose removal adds the most", () => {
  assert.equal(biggestBlocker(waterfallSteps(RESULT))?.criterionId, "inc-2");
  assert.equal(biggestBlocker([]), null);
});

test("review criteria are listed apart from the rules", () => {
  assert.deepEqual(reviewCriteria(RESULT), [
    { criterionId: "inc-3", text: "Stable kidney function", type: "inclusion" },
  ]);
});

test("slider range is the field's clinical range, widened to fit the values", () => {
  const [, egfr] = waterfallSteps(RESULT);
  assert.deepEqual(sliderRange(egfr), { min: 5, max: 120, step: 1 });
  assert.deepEqual(sliderRange({ ...egfr, value: 150 }), { min: 5, max: 150, step: 1 });
  assert.deepEqual(sliderRange({ ...egfr, field: "labs.unknown", value: 7, defaultValue: 8 }), {
    min: 0,
    max: 16,
    step: 1,
  });
});

test("rule labels read like the predicate", () => {
  const [t2d, egfr] = waterfallSteps(RESULT);
  assert.equal(ruleLabel(egfr), "egfr >= 45 mL/min/1.73m2");
  assert.equal(ruleLabel(t2d), "conditions has type 2 diabetes");
});
