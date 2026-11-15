// Unit tests for the /trials and /runs page helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { RunListItem, TrialListItem } from "./api.ts";
import {
  filterTrials,
  matchingTrials,
  runAction,
  runLinks,
  tierChips,
  tierSummary,
  trialFilterChips,
  trialStatusTone,
  withCompiled,
} from "./browse.ts";

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

test("a run row's action: Replay when done, Trace when failed, none while running", () => {
  assert.deepEqual(runAction(run("done")), { label: "Replay", href: "/runs/r-1" });
  assert.deepEqual(runAction(run("failed")), { label: "Trace", href: "/match/r-1" });
  assert.equal(runAction(run("running")), null);
});

test("run ids are URL-encoded", () => {
  assert.deepEqual(runLinks({ ...run("done"), run_id: "a/b" }), {
    view: "/match/a%2Fb",
    replay: "/runs/a%2Fb",
  });
});

test("tier chips list every tier in rank order with its label and count", () => {
  assert.deepEqual(tierChips({ ineligible: 4, likely: 1, needs_info: 0 }), [
    { tier: "likely", label: "likely", count: 1 },
    { tier: "needs_info", label: "needs info", count: 0 },
    { tier: "ineligible", label: "ineligible", count: 4 },
  ]);
});

test("trial status tone: recruiting, not yet recruiting, and everything else", () => {
  assert.equal(trialStatusTone("RECRUITING"), "recruiting");
  assert.equal(trialStatusTone("NOT_YET_RECRUITING"), "not-yet");
  assert.equal(trialStatusTone("ACTIVE_NOT_RECRUITING"), "other");
  assert.equal(trialStatusTone("COMPLETED"), "other");
  assert.equal(trialStatusTone(null), "other");
});

function trial(nct_id: string, title: string, criteria_count: number): TrialListItem {
  return {
    nct_id,
    title,
    phase: "PHASE3",
    overall_status: "RECRUITING",
    compiled: criteria_count > 0,
    criteria_count,
  };
}

const TRIALS = [
  trial("NCT001", "Finerenone in diabetic kidney disease", 11),
  trial("NCT002", "Semaglutide vs insulin in T2D", 0),
  trial("NCT003", "Tirzepatide in early CKD", 12),
];

test("trial filter chips count all, compiled and not compiled trials", () => {
  assert.deepEqual(trialFilterChips(TRIALS), [
    { filter: "all", label: "All", count: 3 },
    { filter: "compiled", label: "Compiled", count: 2 },
    { filter: "not_compiled", label: "Not compiled", count: 1 },
  ]);
});

const ncts = (trials: TrialListItem[]) => trials.map((t) => t.nct_id);

test("matching trials: a case-insensitive substring of NCT ID or title, like GET /api/trials?q", () => {
  assert.deepEqual(ncts(matchingTrials(TRIALS, "  ckd ")), ["NCT003"]);
  assert.deepEqual(ncts(matchingTrials(TRIALS, "nct00")), ["NCT001", "NCT002", "NCT003"]);
  assert.deepEqual(ncts(matchingTrials(TRIALS, "")), ["NCT001", "NCT002", "NCT003"]);
  assert.deepEqual(ncts(matchingTrials(TRIALS, "zzz")), []);
});

test("filtering trials by chip keeps compiled or not compiled ones", () => {
  assert.deepEqual(ncts(filterTrials(TRIALS, "all")), ["NCT001", "NCT002", "NCT003"]);
  assert.deepEqual(ncts(filterTrials(TRIALS, "compiled")), ["NCT001", "NCT003"]);
  assert.deepEqual(ncts(filterTrials(TRIALS, "not_compiled")), ["NCT002"]);
});

test("a compiled trial's row takes the compile endpoint's criteria count", () => {
  const after = withCompiled(TRIALS, "NCT002", 9);
  assert.deepEqual(after[1], { ...TRIALS[1], compiled: true, criteria_count: 9 });
  assert.deepEqual([after[0], after[2]], [TRIALS[0], TRIALS[2]]);
});

test("a compile that yields no criteria leaves the trial not compiled, as GET /api/trials does", () => {
  assert.deepEqual(withCompiled(TRIALS, "NCT002", 0)[1], TRIALS[1]);
});
