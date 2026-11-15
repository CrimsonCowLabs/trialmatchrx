// Pure helpers for the /eval page: matcher-vs-BM25 lifts and the history grouped by prompt
// version. Only a type import from ./api.ts, so node:test can load this file directly.
import type { EvalLatest } from "./api.ts";

type Run = EvalLatest["history"][number];

/** The scores both systems report, in display order (label 2 = relevant). */
export const EVAL_METRICS = [
  { key: "ndcg@10", label: "nDCG@10" },
  { key: "p@10", label: "P@10" },
  { key: "accuracy", label: "Accuracy" },
] as const;

export type Lift = { key: string; label: string; delta: number };

/** Matcher minus BM25, for each metric both have. */
export function lifts(matcher: Record<string, number>, baseline: Record<string, number>): Lift[] {
  return EVAL_METRICS.filter(({ key }) => key in matcher && key in baseline).map(
    ({ key, label }) => ({ key, label, delta: matcher[key] - baseline[key] }),
  );
}

export type PromptVersionRow = { prompt_version: string | null; matcher?: Run; bm25?: Run };

/** One row per prompt version, newest first, holding that version's newest run of each
 * system. `history` is newest first (as GET /api/eval/latest returns it). */
export function byPromptVersion(history: Run[]): PromptVersionRow[] {
  const rows = new Map<string | null, PromptVersionRow>();
  for (const run of history) {
    const row = rows.get(run.prompt_version) ?? { prompt_version: run.prompt_version };
    row[run.system] ??= run;
    rows.set(run.prompt_version, row);
  }
  return [...rows.values()];
}

export function formatRate(rate: number | null | undefined): string {
  return rate == null ? "–" : `${(rate * 100).toFixed(1)}%`;
}
