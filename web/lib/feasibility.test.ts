// Unit tests for the feasibility page helpers. Run with `pnpm test` (node:test, no extra deps).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { FeasibilityResult } from "./api.ts";
import {
  barWidths,
  biggestBlocker,
  cohortShare,
  criteriaSummary,
  eligibleCount,
  reviewSummary,
  ruleLabel,
  setThreshold,
  sliderRange,
  thresholdValue,
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
    steps.map((s) => [s.criterion_id, s.before, s.remaining, s.dropped, s.added_if_removed]),
    [
      ["inc-1", 6, 5, 1, 1],
      ["inc-2", 5, 3, 2, 2],
    ],
  );
  assert.equal(steps[1].value, 45);
  assert.equal(steps[1].default_value, 60);
  assert.equal(steps[1].numeric, true);
});

test("eligible is the last step's remaining, or the whole cohort with no rules", () => {
  assert.equal(eligibleCount(RESULT), 3);
  assert.equal(eligibleCount({ ...RESULT, waterfall: [], leave_one_out: [] }), 6);
});

test("the biggest blocker is the rule whose removal adds the most", () => {
  assert.equal(biggestBlocker(waterfallSteps(RESULT))?.criterion_id, "inc-2");
  assert.equal(biggestBlocker([]), null);
});

test("the biggest blocker comes from leave-one-out, not from how many a rule dropped", () => {
  // inc-1 drops the most in waterfall order, but removing inc-2 alone would add more.
  const result: FeasibilityResult = {
    ...RESULT,
    waterfall: [
      { ...RESULT.waterfall[0], remaining: 2, dropped: 4 },
      { ...RESULT.waterfall[1], remaining: 1, dropped: 1 },
    ],
    leave_one_out: [
      { criterion_id: "inc-1", added_if_removed: 1 },
      { criterion_id: "inc-2", added_if_removed: 3 },
    ],
  };
  assert.equal(biggestBlocker(waterfallSteps(result))?.criterion_id, "inc-2");
});

test("no biggest blocker when dropping any one rule adds nobody; ties go to the earlier rule", () => {
  const none = { ...RESULT, leave_one_out: RESULT.leave_one_out.map((l) => ({ ...l, added_if_removed: 0 })) };
  assert.equal(biggestBlocker(waterfallSteps(none)), null);
  const tie = { ...RESULT, leave_one_out: RESULT.leave_one_out.map((l) => ({ ...l, added_if_removed: 2 })) };
  assert.equal(biggestBlocker(waterfallSteps(tie))?.criterion_id, "inc-1");
});

test("slider range is the field's clinical range, widened to fit the values", () => {
  const [, egfr] = waterfallSteps(RESULT);
  assert.deepEqual(sliderRange(egfr), { min: 5, max: 120, step: 1 });
  assert.deepEqual(sliderRange({ ...egfr, value: 150 }), { min: 5, max: 150, step: 1 });
  assert.deepEqual(sliderRange({ ...egfr, field: "labs.unknown", value: 7, default_value: 8 }), {
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

test("review summary names the criteria without a rule and never counts them as passed", () => {
  // 3 pass every rule; all 3 still face inc-3 by hand.
  assert.deepEqual(reviewSummary(RESULT), {
    patients: 3,
    allEligible: true,
    criteria: [{ criterion_id: "inc-3", text: "Stable kidney function", type: "inclusion" }],
  });
  assert.equal(reviewSummary({ ...RESULT, review_criteria: [], needs_review: 0 }), null);
});

test("bar widths are shares of the whole cohort: what a rule keeps, then what it drops", () => {
  const [t2d, egfr] = waterfallSteps(RESULT);
  assert.deepEqual(barWidths(t2d, 6), { kept: "83.33%", dropped: "16.67%" });
  assert.deepEqual(barWidths(egfr, 6), { kept: "50%", dropped: "33.33%" });
  assert.deepEqual(barWidths(egfr, 0), { kept: "0%", dropped: "0%" });
});

test("a threshold override is kept only while it differs from the compiled value", () => {
  const [, egfr] = waterfallSteps(RESULT); // compiled at 60
  const moved = setThreshold({}, egfr, 45);
  assert.deepEqual(moved, { "inc-2": 45 });
  assert.deepEqual(setThreshold(moved, egfr, 60), {}, "back at the trial's value is no override");
  assert.deepEqual(setThreshold({ "inc-2": 45, "inc-9": 3 }, egfr, null), { "inc-9": 3 });
});

test("a slider shows its override, else the compiled value", () => {
  const [, egfr] = waterfallSteps(RESULT);
  assert.equal(thresholdValue({}, egfr), 60);
  assert.equal(thresholdValue({ "inc-2": 45 }, egfr), 45);
});

test("criteria summary counts compiled rules and the criteria that need review", () => {
  assert.equal(criteriaSummary(RESULT), "2 compiled criteria, 1 needs review");
  const more = { ...RESULT, review_criteria: [...RESULT.review_criteria, RESULT.review_criteria[0]] };
  assert.equal(criteriaSummary(more), "2 compiled criteria, 2 need review");
  assert.equal(
    criteriaSummary({ ...RESULT, waterfall: RESULT.waterfall.slice(0, 1), review_criteria: [] }),
    "1 compiled criterion, none need review",
  );
});

test("a cohort share is a CSS width, 0% with no cohort", () => {
  assert.equal(cohortShare(70, 1000), "7%");
  assert.equal(cohortShare(1, 3), "33.33%");
  assert.equal(cohortShare(5, 0), "0%");
});
