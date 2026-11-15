// Pure helpers for the /trials and /runs browse pages. Only a type import from ./api.ts, so
// node:test can load this file directly.
import type { RunListItem, Tier, TierCounts, TrialListItem } from "./api.ts";

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

/** The link at the end of a /runs row: a done run's replay, or a failed run's trace (its match
 *  view, where the error event is in the trace panel). A running run has none yet. */
export function runAction(run: RunListItem): { label: string; href: string } | null {
  const links = runLinks(run);
  if (links.replay) return { label: "Replay", href: links.replay };
  if (run.status === "failed") return { label: "Trace", href: links.view };
  return null;
}

export type TrialFilter ="all" | "compiled" | "not_compiled";

const TRIAL_FILTERS = {
  all: { label: "All", keep: () => true },
  compiled: { label: "Compiled", keep: (t: TrialListItem) => t.compiled },
  not_compiled: { label: "Not compiled", keep: (t: TrialListItem) => !t.compiled },
} as const satisfies Record<TrialFilter, { label: string; keep: (t: TrialListItem) => boolean }>;

export type TrialFilterChip = { filter: TrialFilter; label: string; count: number };

/** The All / Compiled / Not compiled chips over `trials`, each with its count. */
export function trialFilterChips(trials: TrialListItem[]): TrialFilterChip[] {
  return (Object.keys(TRIAL_FILTERS) as TrialFilter[]).map((filter) => ({
    filter,
    label: TRIAL_FILTERS[filter].label,
    count: trials.filter(TRIAL_FILTERS[filter].keep).length,
  }));
}

/** The trials whose NCT ID or title contains `query`, ignoring case and surrounding space;
 *  the same match as GET /api/trials?q, run here so one load gives the whole cache count too. */
export function matchingTrials(trials: TrialListItem[], query: string): TrialListItem[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return trials;
  return trials.filter(
    (t) => t.nct_id.toLowerCase().includes(needle) || t.title.toLowerCase().includes(needle),
  );
}

/** `trials` with one row updated after POST /api/trials/{nct}/compile returned
 *  `criteriaCount` criteria; a trial counts as compiled once it has any, as on the API. */
export function withCompiled(
  trials: TrialListItem[],
  nct: string,
  criteriaCount: number,
): TrialListItem[] {
  return trials.map((t) =>
    t.nct_id === nct ? { ...t, compiled: criteriaCount > 0, criteria_count: criteriaCount } : t,
  );
}

/** The trials one chip keeps. */
export function filterTrials(trials: TrialListItem[], filter: TrialFilter): TrialListItem[] {
  return trials.filter(TRIAL_FILTERS[filter].keep);
}

export type TrialStatusTone = "recruiting" | "not-yet" | "other";

/** Colour of a trial's status dot, from its ClinicalTrials.gov overall status
 *  (RECRUITING, NOT_YET_RECRUITING, ACTIVE_NOT_RECRUITING, ...). */
export function trialStatusTone(status: string | null): TrialStatusTone {
  if (status === "RECRUITING") return "recruiting";
  if (status === "NOT_YET_RECRUITING") return "not-yet";
  return "other";
}
