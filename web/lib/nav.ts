// App shell navigation: the five items, which one a route highlights, and the sidebar's
// count hints and API health line. Pure helpers, tested in nav.test.ts.
import type { Health } from "./api.ts";

export type NavId = "home" | "match" | "runs" | "trials" | "eval";

export const NAV_ITEMS: readonly { id: NavId; label: string; href: string }[] = [
  { id: "home", label: "Home", href: "/" },
  { id: "match", label: "Match", href: "/match" },
  { id: "runs", label: "Runs", href: "/runs" },
  { id: "trials", label: "Trials", href: "/trials" },
  { id: "eval", label: "Eval", href: "/eval" },
];

// First path segment -> the item it highlights. Feasibility is opened from a trial, so it sits
// under Trials; a closer run continues a match (opened from the match results), so it sits under
// Match.
const SECTION: Record<string, NavId> = {
  match: "match",
  closer: "match",
  runs: "runs",
  trials: "trials",
  feasibility: "trials",
  eval: "eval",
};

/** The nav item a pathname highlights, or null when none fits. */
export function activeNav(pathname: string | null): NavId | null {
  if (pathname === null) return null;
  const segment = pathname.split("/").filter(Boolean)[0];
  if (segment === undefined) return "home";
  return SECTION[segment] ?? null;
}

/** The hint beside a nav item: the list's length, or `cap+` when the API cut the list off at
 *  `cap` (so the true count may be higher). Null (no hint) until the list has loaded. */
export function countHint(count: number | null, cap: number): string | null {
  if (count === null) return null;
  return count >= cap ? `${cap}+` : String(count);
}

export type HealthTone = "ok" | "warn" | "down";

/** The sidebar's API status line from `/api/health`: healthy, reachable but not ready (replay
 *  mode without recorded fixtures), or unreachable. Null while the first check is in flight. */
export function healthLine(
  health: Health | null,
  error: string | null,
): { tone: HealthTone; text: string } | null {
  if (health) {
    const mode = health.demo_mode === "off" ? "live" : health.demo_mode;
    return health.ok
      ? { tone: "ok", text: `API healthy · ${mode} mode` }
      : { tone: "warn", text: `API not ready · ${mode} mode` };
  }
  return error === null ? null : { tone: "down", text: "API unreachable" };
}
