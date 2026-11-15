// Unit tests for the home page helpers. Run with `pnpm test` (node:test, no extra deps).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { EvalLatest, TrialListItem } from "./api.ts";
import { defaultFeasibilityNct, evalBars } from "./home.ts";

function trial(nct_id: string, compiled: boolean, overall_status: string | null): TrialListItem {
  return {
    nct_id,
    title: `Trial ${nct_id}`,
    phase: null,
    overall_status,
    compiled,
    criteria_count: compiled ? 5 : 0,
  };
}

test("default feasibility trial: the first compiled, recruiting trial", () => {
  const trials = [
    trial("NCT00000001", false, "RECRUITING"),
    trial("NCT00000002", true, "COMPLETED"),
    trial("NCT00000003", true, "RECRUITING"),
    trial("NCT00000004", true, "RECRUITING"),
  ];
  assert.equal(defaultFeasibilityNct(trials), "NCT00000003");
});

test("default feasibility trial: any compiled trial when none is recruiting", () => {
  const trials = [trial("NCT00000001", false, "RECRUITING"), trial("NCT00000002", true, null)];
  assert.equal(defaultFeasibilityNct(trials), "NCT00000002");
});

test("no default feasibility trial until one is compiled", () => {
  assert.equal(defaultFeasibilityNct([trial("NCT00000001", false, "RECRUITING")]), null);
  assert.equal(defaultFeasibilityNct([]), null);
});

function latest(metrics: Record<string, number>, baseline: Record<string, number>): EvalLatest {
  return {
    metrics,
    baseline,
    compile_rate: null,
    compile_rate_target: 0.6,
    sample_size: 0,
    topics: 0,
    dropped: 0,
    history: [],
  };
}

test("eval bars: matcher and BM25 per metric, in display order", () => {
  const bars = evalBars(
    latest(
      { accuracy: 0.8, "ndcg@10": 0.62, "p@10": 0.5, compile_rate: 0.6 },
      { "p@10": 0.3667, "ndcg@10": 0.4351, accuracy: 0.7 },
    ),
  );
  assert.deepEqual(bars, [
    { key: "ndcg@10", label: "nDCG@10", matcher: 0.62, bm25: 0.4351 },
    { key: "p@10", label: "P@10", matcher: 0.5, bm25: 0.3667 },
    { key: "accuracy", label: "Accuracy", matcher: 0.8, bm25: 0.7 },
  ]);
});

test("eval bars: a system that hasn't been scored is null, not zero", () => {
  const bars = evalBars(latest({}, { "ndcg@10": 0.43, "p@10": 0.37 }));
  assert.deepEqual(bars, [
    { key: "ndcg@10", label: "nDCG@10", matcher: null, bm25: 0.43 },
    { key: "p@10", label: "P@10", matcher: null, bm25: 0.37 },
  ]);
});

test("no eval bars before the first eval run", () => {
  assert.deepEqual(evalBars(latest({}, {})), []);
});
