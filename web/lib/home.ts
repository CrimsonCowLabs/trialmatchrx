// Pure helpers for the home page. Only type imports from ./api.ts (and pure ./eval.ts), so
// node:test can load this file directly.
import type { EvalLatest, TrialListItem } from "./api.ts";
import { EVAL_METRICS } from "./eval.ts";

/** The NCT ID the feasibility card opens by default: the first compiled trial (the list is
 *  sorted by NCT ID), preferring one that is recruiting. */
export function defaultFeasibilityNct(trials: TrialListItem[]): string | null {
  const compiled = trials.filter((t) => t.compiled);
  const recruiting = compiled.find((t) => t.overall_status === "RECRUITING");
  return (recruiting ?? compiled[0])?.nct_id ?? null;
}

/** One pair of bars on the Latest eval card; null = that system has no score for the metric. */
export type EvalBar = { key: string; label: string; matcher: number | null; bm25: number | null };

/** Matcher vs BM25 for each metric either system reports, in display order; empty before the
 *  first `make eval`. */
export function evalBars({ metrics, baseline }: EvalLatest): EvalBar[] {
  return EVAL_METRICS.filter(({ key }) => key in metrics || key in baseline).map(
    ({ key, label }) => ({ key, label, matcher: metrics[key] ?? null, bm25: baseline[key] ?? null }),
  );
}
