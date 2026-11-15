// Pure helpers for the /trials and /runs browse pages. Only a type import from ./api.ts, so
// node:test can load this file directly.
import type { RunListItem, Tier, TierCounts } from "./api.ts";

// Every tier, in rank order; `satisfies` makes tsc flag a tier added to the API but not here.
const TIER_LABELS = {
  likely: "likely",
  needs_info: "needs info",
  ineligible: "ineligible",
} as const satisfies Record<Tier, string>;

/** "1 likely · 2 needs info · 4 ineligible", or "No matches" when every count is zero. */
export function tierSummary(counts: TierCounts): string {
  const parts = (Object.keys(TIER_LABELS) as Tier[]).map((tier) => ({
    n: counts[tier],
    label: TIER_LABELS[tier],
  }));
  if (parts.every(({ n }) => n === 0)) return "No matches";
  return parts.map(({ n, label }) => `${n} ${label}`).join(" · ");
}

export type RunLinks = { view: string; replay: string | null };

/** Where a match run's row links: its match view (live while running), plus the replay view
 *  once it is done. */
export function runLinks(run: RunListItem): RunLinks {
  const id = encodeURIComponent(run.run_id);
  return { view: `/match/${id}`, replay: run.status === "done" ? `/runs/${id}` : null };
}
