// Pure helpers for the /trials and /runs browse pages. Only a type import from ./api.ts, so
// node:test can load this file directly.
import type { RunListItem, Tier, TierCounts } from "./api.ts";

// Every tier, in rank order; `satisfies` makes tsc flag a tier added to the API but not here.
const TIER_LABELS = {
  likely: "likely",
  needs_info: "needs info",
  ineligible: "ineligible",
} as const satisfies Record<Tier, string>;

export type TierChip = { tier: Tier; label: string; count: number };

/** Every tier with its label, in rank order. */
export const TIERS = (Object.keys(TIER_LABELS) as Tier[]).map((tier) => ({
  tier,
  label: TIER_LABELS[tier],
}));

/** One chip per tier, in rank order, zero counts included. */
export function tierChips(counts: TierCounts): TierChip[] {
  return TIERS.map(({ tier, label }) => ({ tier, label, count: counts[tier] }));
}

/** "1 likely · 2 needs info · 4 ineligible", or "No matches" when every count is zero. */
export function tierSummary(counts: TierCounts): string {
  const chips = tierChips(counts);
  if (chips.every(({ count }) => count === 0)) return "No matches";
  return chips.map(({ count, label }) => `${count} ${label}`).join(" · ");
}

export type RunLinks = { view: string; replay: string | null };

/** Where a match run's row links: its match view (live while running), plus the replay view
 *  once it is done. */
export function runLinks(run: RunListItem): RunLinks {
  const id = encodeURIComponent(run.run_id);
  return { view: `/match/${id}`, replay: run.status === "done" ? `/runs/${id}` : null };
}

export type TrialStatusTone = "recruiting" | "not-yet" | "other";

/** Colour of a trial's status dot, from its ClinicalTrials.gov overall status
 *  (RECRUITING, NOT_YET_RECRUITING, ACTIVE_NOT_RECRUITING, ...). */
export function trialStatusTone(status: string | null): TrialStatusTone {
  if (status === "RECRUITING") return "recruiting";
  if (status === "NOT_YET_RECRUITING") return "not-yet";
  return "other";
}
