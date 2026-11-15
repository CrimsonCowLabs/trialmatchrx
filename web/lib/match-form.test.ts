// Unit tests for the /match form helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { RunStats } from "./api.ts";
import { DEMO_RADIUS_MI } from "./demo.ts";
import {
  AGENT_STEPS,
  DEFAULT_RADIUS_MI,
  formatCost,
  formatDurationRange,
  RADII_MI,
  runStatsHint,
} from "./match-form.ts";

function stats(over: Partial<RunStats> = {}): RunStats {
  return {
    runs: 3,
    wall_time_min_s: 12.2,
    wall_time_max_s: 30.6,
    cost_usd_median: 0.104,
    ...over,
  };
}

test("radius choices are 25, 50 and 100 miles", () => {
  assert.deepEqual([...RADII_MI], [25, 50, 100]);
});

test("the form and the demo request search 100 miles, the seeded reach", () => {
  assert.equal(DEFAULT_RADIUS_MI, 100);
  assert.equal(DEMO_RADIUS_MI, 100);
});

test("the agent panel lists the six pipeline steps in order", () => {
  assert.deepEqual(
    AGENT_STEPS.map((s) => s.title),
    ["Parse", "Search", "Compile", "Evaluate", "Verify quotes", "Rank"],
  );
});

test("a duration range under a minute shares one unit", () => {
  assert.equal(formatDurationRange(12.2, 30.6), "12–31 s");
});

test("a range that crosses a minute names both units", () => {
  assert.equal(formatDurationRange(45, 130), "45 s – 2 min 10 s");
  assert.equal(formatDurationRange(60, 120), "1–2 min");
});

test("a range whose ends round the same reads as one value", () => {
  assert.equal(formatDurationRange(12.2, 12.4), "about 12 s");
});

test("costs show cents, and a non-zero cost under a cent says so", () => {
  assert.equal(formatCost(0.104), "$0.10");
  assert.equal(formatCost(1.5), "$1.50");
  assert.equal(formatCost(0.004), "under $0.01");
  assert.equal(formatCost(0), "$0.00");
});

test("the hint states the range, the typical cost and how many runs it is from", () => {
  assert.equal(
    runStatsHint(stats()),
    "Recent runs took 12–31 s · typical cost $0.10 · from the last 3 finished runs",
  );
  assert.equal(
    runStatsHint(stats({ runs: 1, wall_time_min_s: 20, wall_time_max_s: 20 })),
    "Recent runs took about 20 s · typical cost $0.10 · from the last finished run",
  );
});

test("there is no hint without finished runs", () => {
  assert.equal(runStatsHint(null), null);
  assert.equal(
    runStatsHint(stats({ runs: 0, wall_time_min_s: null, wall_time_max_s: null, cost_usd_median: null })),
    null,
  );
});

test("a missing figure drops its part of the hint", () => {
  assert.equal(
    runStatsHint(stats({ cost_usd_median: null })),
    "Recent runs took 12–31 s · from the last 3 finished runs",
  );
  assert.equal(
    runStatsHint(stats({ wall_time_min_s: null, wall_time_max_s: null })),
    "Typical cost $0.10 · from the last 3 finished runs",
  );
});
