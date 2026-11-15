// Pure helpers for the /trials and /runs browse pages. Only a type import from ./api.ts, so
// node:test can load this file directly.
import type { RunListItem } from "./api.ts";

const TIERS = [
  ["likely", "likely"],
  ["needs_info", "needs info"],
  ["ineligible", "ineligible"],
] as const;

/** "1 likely · 2 needs info · 4 ineligible", or "No matches" when every count is zero. */
export function tierSummary(counts: Record<string, number>): string {
  const parts = TIERS.map(([tier, label]) => ({ n: counts[tier] ?? 0, label }));
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
