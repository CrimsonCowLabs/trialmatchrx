// Pure helpers for the /match form. Only a type import from ./api.ts, so node:test can load
// this file directly.
import type { RunStats } from "./api.ts";

/** The search radius choices, in miles; the form submits the chosen one as `radius_mi`. */
export const RADII_MI = [25, 50, 100] as const;
export type RadiusMi = (typeof RADII_MI)[number];
// HACK(demo): 50 mi default around Sacramento, as SPEC.md's trial search.
export const DEFAULT_RADIUS_MI: RadiusMi = 50;

/** What a match run does, in pipeline order (SPEC.md "Pipelines"). Descriptions only: no
 *  figures, since every number on the page must come from the API. */
export const AGENT_STEPS = [
  {
    title: "Parse",
    detail: "Reads the note into structured patient facts, quoting the source for each one.",
  },
  {
    title: "Search",
    detail: "Finds recruiting trials for the condition with a site inside the radius.",
  },
  {
    title: "Compile",
    detail: "Splits each trial's eligibility text into atomic criteria, as code rules where it can.",
  },
  {
    title: "Evaluate",
    detail: "Runs each rule against the facts; criteria that need judgment go to the model.",
  },
  {
    title: "Verify quotes",
    detail: "Checks every quote against its source; an unverified verdict drops to unknown.",
  },
  {
    title: "Rank",
    detail: "Orders trials by tier, then fewer unknowns, then distance.",
  },
] as const;

function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  if (total < 60) return `${total} s`;
  const min = Math.floor(total / 60);
  const sec = total % 60;
  return sec ? `${min} min ${sec} s` : `${min} min`;
}

/** "12–31 s", "1–2 min", "45 s – 2 min 10 s", or "about 12 s" when both ends round alike. */
export function formatDurationRange(minS: number, maxS: number): string {
  const [lo, hi] = [formatDuration(minS), formatDuration(maxS)];
  if (lo === hi) return `about ${lo}`;
  const [a, b] = [Math.round(minS), Math.round(maxS)];
  if (b < 60) return `${a}–${b} s`;
  if (a >= 60 && a % 60 === 0 && b % 60 === 0) return `${a / 60}–${b / 60} min`;
  return `${lo} – ${hi}`;
}

/** Dollars to the cent; a non-zero cost that would round to $0.00 reads "under $0.01". */
export function formatCost(usd: number): string {
  if (usd > 0 && usd < 0.005) return "under $0.01";
  return `$${usd.toFixed(2)}`;
}

/** The form's duration / cost hint from `GET /api/runs/stats`, or null (hide it) when there
 *  are no finished runs or no figures to show. */
export function runStatsHint(stats: RunStats | null): string | null {
  if (!stats || stats.runs === 0) return null;
  const parts: string[] = [];
  if (stats.wall_time_min_s != null && stats.wall_time_max_s != null) {
    parts.push(`Recent runs took ${formatDurationRange(stats.wall_time_min_s, stats.wall_time_max_s)}`);
  }
  if (stats.cost_usd_median != null) {
    const cost = formatCost(stats.cost_usd_median);
    parts.push(parts.length ? `typical cost ${cost}` : `Typical cost ${cost}`);
  }
  if (parts.length === 0) return null;
  const from = stats.runs === 1 ? "the last finished run" : `the last ${stats.runs} finished runs`;
  return [...parts, `from ${from}`].join(" · ");
}
