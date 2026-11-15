// Unit tests for the eval page helpers. Run with `pnpm test` (node:test, no extra deps).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { EvalLatest } from "./api.ts";
import {
  formatGain,
  formatRate,
  formatScore,
  formatTarget,
  groupByPromptVersion,
  metricCards,
} from "./eval.ts";

type Run = EvalLatest["history"][number];

function run(
  id: string,
  system: Run["system"],
  prompt_version: string | null,
  metrics: Record<string, number>,
): Run {
  return {
    id,
    system,
    prompt_version,
    metrics,
    created_at: "2026-11-12T10:00:00Z",
    git_sha: "abc1234",
    sample_size: 299,
  };
}

test("metric cards: matcher, BM25 and the gain (matcher minus BM25) per metric", () => {
  const matcher = { "ndcg@10": 0.62, "p@10": 0.5, accuracy: 0.8, compile_rate: 0.6 };
  const baseline = { "ndcg@10": 0.4351, "p@10": 0.3667 };

  const got = metricCards(matcher, baseline).map(({ key, matcher, bm25, gain }) => [
    key,
    matcher,
    bm25,
    gain === null ? null : Number(gain.toFixed(4)),
  ]);

  assert.deepEqual(got, [
    ["ndcg@10", 0.62, 0.4351, 0.1849],
    ["p@10", 0.5, 0.3667, 0.1333],
    ["accuracy", 0.8, null, null],
  ]);
});

test("metric cards before the matcher is scored: BM25 only, no gain", () => {
  const got = metricCards({}, { "ndcg@10": 0.4, "p@10": 0.3, accuracy: 0.5 });

  assert.deepEqual(
    got.map(({ label, matcher, bm25, gain }) => [label, matcher, bm25, gain]),
    [
      ["nDCG@10", null, 0.4, null],
      ["P@10", null, 0.3, null],
      ["Accuracy", null, 0.5, null],
    ],
  );
});

test("no metric cards before the first make eval", () => {
  assert.deepEqual(metricCards({}, {}), []);
});

test("history by prompt version: every run, grouped, newest version first", () => {
  // Newest first, as GET /api/eval/latest returns it. A version that comes back keeps its
  // first (newest) position and collects all its runs.
  const history = [
    run("m3", "matcher", "judge-v2", { "ndcg@10": 0.7 }),
    run("b2", "bm25", "judge-v2", { "ndcg@10": 0.43 }),
    run("m2", "matcher", "judge-v1", { "ndcg@10": 0.6 }),
    run("b0", "bm25", null, { "ndcg@10": 0.43 }),
    run("m1", "matcher", "judge-v1", { "ndcg@10": 0.5 }),
    run("b1", "bm25", "judge-v1", { "ndcg@10": 0.43 }),
  ];

  const groups = groupByPromptVersion(history).map((g) => [
    g.prompt_version,
    g.runs.map((r) => r.id),
  ]);

  assert.deepEqual(groups, [
    ["judge-v2", ["m3", "b2"]],
    ["judge-v1", ["m2", "m1", "b1"]],
    [null, ["b0"]],
  ]);
});

test("gains are signed to three decimals", () => {
  assert.equal(formatGain(0.1849), "+0.185");
  assert.equal(formatGain(-0.02), "−0.020");
  assert.equal(formatGain(0), "+0.000");
});

test("the compile target formats as a whole percentage", () => {
  assert.equal(formatTarget(0.6), "60%");
  assert.equal(formatTarget(0.625), "63%");
});

test("rates format as whole-ish percentages, a missing rate as a dash", () => {
  assert.equal(formatRate(0.434), "43.4%");
  assert.equal(formatRate(null), "–");
  assert.equal(formatRate(undefined), "–");
});

test("scores format to three decimals, a missing score as a dash", () => {
  assert.equal(formatScore(0.4351), "0.435");
  assert.equal(formatScore(0), "0.000");
  assert.equal(formatScore(null), "–");
  assert.equal(formatScore(undefined), "–");
});
