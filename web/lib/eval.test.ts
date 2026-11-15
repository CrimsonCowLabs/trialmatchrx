// Unit tests for the eval page helpers. Run with `pnpm test` (node:test, no extra deps).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { EvalLatest } from "./api.ts";
import { byPromptVersion, formatRate, lifts } from "./eval.ts";

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

test("lifts are matcher minus BM25, only for metrics both systems report", () => {
  const matcher = { "ndcg@10": 0.62, "p@10": 0.5, accuracy: 0.8, compile_rate: 0.6 };
  const baseline = { "ndcg@10": 0.4351, "p@10": 0.3667 };

  const got = lifts(matcher, baseline).map(({ key, delta }) => [key, Number(delta.toFixed(4))]);

  assert.deepEqual(got, [
    ["ndcg@10", 0.1849],
    ["p@10", 0.1333],
  ]);
});

test("no lifts until the matcher has been scored", () => {
  assert.deepEqual(lifts({}, { "ndcg@10": 0.4 }), []);
});

test("history by prompt version: newest version first, its newest run per system", () => {
  // Newest first, as GET /api/eval/latest returns it.
  const history = [
    run("m3", "matcher", "judge-v2", { "ndcg@10": 0.7 }),
    run("b2", "bm25", "judge-v2", { "ndcg@10": 0.43 }),
    run("m2", "matcher", "judge-v1", { "ndcg@10": 0.6 }),
    run("m1", "matcher", "judge-v1", { "ndcg@10": 0.5 }),
    run("b1", "bm25", "judge-v1", { "ndcg@10": 0.43 }),
    run("b0", "bm25", null, { "ndcg@10": 0.43 }),
  ];

  const rows = byPromptVersion(history).map((r) => [
    r.prompt_version,
    r.matcher?.id ?? null,
    r.bm25?.id ?? null,
  ]);

  assert.deepEqual(rows, [
    ["judge-v2", "m3", "b2"],
    ["judge-v1", "m2", "b1"],
    [null, null, "b0"],
  ]);
});

test("rates format as whole-ish percentages, a missing rate as a dash", () => {
  assert.equal(formatRate(0.434), "43.4%");
  assert.equal(formatRate(null), "–");
  assert.equal(formatRate(undefined), "–");
});
