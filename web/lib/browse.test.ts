// Unit tests for the /trials and /runs page helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { RunListItem } from "./api.ts";
import { runLinks, tierSummary } from "./browse.ts";

function run(status: RunListItem["status"]): RunListItem {
  return {
    run_id: "r-1",
    kind: "match",
    status,
    created_at: "2026-11-12T10:00:00Z",
    ended_at: status === "running" ? null : "2026-11-12T10:01:00Z",
    patient_label: null,
    tier_counts: { likely: 0, needs_info: 0, ineligible: 0 },
  };
}

test("tier summary lists each tier with its count, in tier order", () => {
  assert.equal(
    tierSummary({ ineligible: 4, likely: 1, needs_info: 2 }),
    "1 likely · 2 needs info · 4 ineligible",
  );
});

test("tier summary keeps zero tiers when a run has matches", () => {
  assert.equal(tierSummary({ likely: 0, needs_info: 3, ineligible: 0 }), "0 likely · 3 needs info · 0 ineligible");
});

test("tier summary says so when a run has no matches", () => {
  assert.equal(tierSummary({ likely: 0, needs_info: 0, ineligible: 0 }), "No matches");
});

test("a finished match run opens its match view and offers its replay", () => {
  assert.deepEqual(runLinks(run("done")), { view: "/match/r-1", replay: "/runs/r-1" });
});

test("a running match run opens its live view, with no replay yet", () => {
  assert.deepEqual(runLinks(run("running")), { view: "/match/r-1", replay: null });
});

test("a failed run opens its view but offers no replay", () => {
  assert.deepEqual(runLinks(run("failed")), { view: "/match/r-1", replay: null });
});

test("run ids are URL-encoded", () => {
  assert.deepEqual(runLinks({ ...run("done"), run_id: "a/b" }), {
    view: "/match/a%2Fb",
    replay: "/runs/a%2Fb",
  });
});
