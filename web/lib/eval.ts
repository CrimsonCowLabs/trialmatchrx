// Pure helpers for the /eval page: matcher-vs-BM25 metric cards with the gain, and the history
// grouped by prompt version. Only a type import from ./api.ts, so node:test can load this file directly.
import type { EvalLatest } from "./api.ts";

type Run = EvalLatest["history"][number];

/** The scores both systems report, in display order (label 2 = relevant). */
export const EVAL_METRICS = [
  { key: "ndcg@10", label: "nDCG@10" },
  { key: "p@10", label: "P@10" },
  { key: "accuracy", label: "Accuracy" },
] as const;

/** One metric card: each system's score (null = not scored) and the matcher's gain over
 * BM25 (null unless both are scored). */
export type MetricCard = {
  key: string;
  label: string;
  matcher: number | null;
  bm25: number | null;
  gain: number | null;
};

/** A card for each metric either system reports, in display order; empty before the first
 * `make eval`. */
export function metricCards(
  matcher: Record<string, number>,
  baseline: Record<string, number>,
): MetricCard[] {
  return EVAL_METRICS.filter(({ key }) => key in matcher || key in baseline).map(
    ({ key, label }) => {
      const m = matcher[key] ?? null;
      const b = baseline[key] ?? null;
      return { key, label, matcher: m, bm25: b, gain: m !== null && b !== null ? m - b : null };
    },
  );
}

export type PromptVersionGroup = { prompt_version: string | null; runs: Run[] };

/** Every run grouped by prompt version, a group per version in order of its newest run.
 * `history` is newest first (as GET /api/eval/latest returns it), and so is each group. */
export function groupByPromptVersion(history: Run[]): PromptVersionGroup[] {
  const groups = new Map<string | null, PromptVersionGroup>();
  for (const run of history) {
    const group = groups.get(run.prompt_version) ?? { prompt_version: run.prompt_version, runs: [] };
    group.runs.push(run);
    groups.set(run.prompt_version, group);
  }
  return [...groups.values()];
}

/** A gain (matcher minus BM25), signed, to three decimals. */
export function formatGain(delta: number): string {
  return `${delta >= 0 ? "+" : "−"}${Math.abs(delta).toFixed(3)}`;
}

/** The compile-rate target as a whole percentage, e.g. 0.6 -> "60%". */
export function formatTarget(target: number): string {
  return `${Math.round(target * 100)}%`;
}

/** A metric score (nDCG@10, P@10, accuracy) to three decimals; "–" when there is none. */
export function formatScore(score: number | null | undefined): string {
  return score == null ? "–" : score.toFixed(3);
}

export function formatRate(rate: number | null | undefined): string {
  return rate == null ? "–" : `${(rate * 100).toFixed(1)}%`;
}
