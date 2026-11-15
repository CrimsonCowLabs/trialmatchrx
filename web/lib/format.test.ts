// Unit tests for the shared number / copy formatters. Run with `pnpm test`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { countNoun, formatCount } from "./format.ts";

test("counts get thousands separators", () => {
  assert.equal(formatCount(1000), "1,000");
  assert.equal(formatCount(38), "38");
});

test("a count with its noun picks singular or plural", () => {
  assert.equal(countNoun(1, "criterion", "criteria"), "1 criterion");
  assert.equal(countNoun(21, "criterion", "criteria"), "21 criteria");
  assert.equal(countNoun(0, "criterion", "criteria"), "0 criteria");
  assert.equal(countNoun(1200, "patient", "patients"), "1,200 patients");
});
