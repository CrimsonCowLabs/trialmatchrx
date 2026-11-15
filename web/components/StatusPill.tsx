// A run's status as a coloured pill: done (green), running (teal), failed (red).
import type { RunListItem } from "@/lib/api";

export type RunStatus = RunListItem["status"];

// Literal class names so Tailwind sees them; colours are the status tokens in globals.css.
const TONE = {
  done: "bg-status-done-bg text-status-done",
  running: "bg-status-running-bg text-status-running",
  failed: "bg-status-failed-bg text-status-failed",
} as const satisfies Record<RunStatus, string>;

export function StatusPill({ status }: { status: RunStatus }) {
  return (
    <span
      data-slot="status-pill"
      data-status={status}
      className={`inline-flex h-6 w-fit shrink-0 items-center rounded-full px-2.5 text-xs font-medium whitespace-nowrap ${TONE[status]}`}
    >
      {status}
    </span>
  );
}
