"use client";

// The shell's route-aware parts: the nav items (sidebar or tab bar) with the active one
// highlighted, the sidebar's Runs / Trials count hints and its API health line. Everything
// shown comes from the API (`/api/runs`, `/api/trials`, `/api/health`), re-read on navigation
// so a new run shows up in the count.
import { ChartColumn, FlaskConical, History, House, Stethoscope } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { api, errorMessage, type Health } from "@/lib/api";
import { activeNav, countHint, healthLine, NAV_ITEMS, type NavId } from "@/lib/nav";

const ICONS: Record<NavId, typeof House> = {
  home: House,
  match: Stethoscope,
  runs: History,
  trials: FlaskConical,
  eval: ChartColumn,
};

/** `/api/runs` caps its list; at the cap the hint reads "200+". */
const RUNS_CAP = 200;

type ShellStatus = {
  runs: string | null;
  trials: string | null;
  health: Health | null;
  healthError: string | null;
};

const UNKNOWN: ShellStatus = { runs: null, trials: null, health: null, healthError: null };

/** Reads the counts and health on mount and on every navigation. A failed count hides its hint;
 *  a failed health check reads as "API unreachable". */
function useShellStatus(pathname: string): ShellStatus {
  const [status, setStatus] = useState(UNKNOWN);
  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([api.listRuns({ limit: RUNS_CAP }), api.listTrials(), api.getHealth()]).then(
      ([runs, trials, health]) => {
        if (cancelled) return;
        setStatus({
          runs: runs.status === "fulfilled" ? countHint(runs.value.length, RUNS_CAP) : null,
          // `/api/trials` is uncapped: its length is the count.
          trials: trials.status === "fulfilled" ? String(trials.value.length) : null,
          health: health.status === "fulfilled" ? health.value : null,
          healthError: health.status === "rejected" ? errorMessage(health.reason) : null,
        });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [pathname]);
  return status;
}

function hintFor(id: NavId, status: ShellStatus | null): string | null {
  if (!status) return null;
  return id === "runs" ? status.runs : id === "trials" ? status.trials : null;
}

function SidebarItems({ active, status }: { active: NavId | null; status: ShellStatus | null }) {
  return (
    <ul className="flex flex-col gap-0.5">
      {NAV_ITEMS.map(({ id, label, href }) => {
        const Icon = ICONS[id];
        const isActive = id === active;
        const hint = hintFor(id, status);
        return (
          <li key={id}>
            <Link
              href={href}
              aria-current={isActive ? "page" : undefined}
              className={`flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium ${
                isActive ? "bg-teal-tint text-teal-strong" : "text-ink-2 hover:bg-surface-sunken"
              }`}
            >
              <Icon aria-hidden className="size-4 shrink-0" />
              <span className="flex-1">{label}</span>
              {hint !== null && (
                <span className="font-mono text-xs text-ink-4 tabular-nums">{hint}</span>
              )}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

const TONE_DOT = {
  ok: "bg-status-done",
  warn: "bg-verdict-unknown",
  down: "bg-status-failed",
} as const;

function HealthStatus({ status }: { status: ShellStatus }) {
  const line = healthLine(status.health, status.healthError);
  if (!line) return null;
  return (
    <p className="flex items-center gap-2 text-xs text-ink-3" role="status">
      <span aria-hidden className={`size-2 shrink-0 rounded-full ${TONE_DOT[line.tone]}`} />
      {line.text}
    </p>
  );
}

/** Desktop sidebar nav plus the health line; fetches the counts. */
export function SidebarNav() {
  const pathname = usePathname();
  const status = useShellStatus(pathname);
  return (
    <>
      <nav aria-label="Main" className="flex-1">
        <SidebarItems active={activeNav(pathname)} status={status} />
      </nav>
      <HealthStatus status={status} />
    </>
  );
}

/** Pre-render / suspended stand-in: the same items, nothing highlighted, no hints. */
export function SidebarNavFallback() {
  return (
    <nav aria-label="Main" className="flex-1">
      <SidebarItems active={null} status={null} />
    </nav>
  );
}

function TabItems({ active }: { active: NavId | null }) {
  return (
    <ul className="grid grid-cols-5">
      {NAV_ITEMS.map(({ id, label, href }) => {
        const Icon = ICONS[id];
        const isActive = id === active;
        return (
          <li key={id}>
            <Link
              href={href}
              aria-current={isActive ? "page" : undefined}
              className={`relative flex h-16 flex-col items-center justify-center gap-1 text-[11px] font-medium ${
                isActive ? "text-teal-strong" : "text-ink-4"
              }`}
            >
              {isActive && (
                <span aria-hidden className="absolute inset-x-4 top-0 h-0.5 rounded-b bg-teal" />
              )}
              <Icon aria-hidden className="size-5" />
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** Mobile bottom tab bar items, active one marked with a bar on top. */
export function TabBarNav() {
  return <TabItems active={activeNav(usePathname())} />;
}

export function TabBarNavFallback() {
  return <TabItems active={null} />;
}
