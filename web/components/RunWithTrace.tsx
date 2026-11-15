"use client";

// A run page: the header (breadcrumb with the run's status, duration and Replay / Live view
// link; the patient and their facts), then results on the left and the trace on the right,
// linked both ways. "Why?" on a verdict focuses its trace event; selecting a trace event
// highlights the verdict it produced. The trace column stays in view while the results scroll.
// Used by the live match and closer pages and the replay page.
import Link from "next/link";
import { useMemo, type ReactNode } from "react";

import { CloserResult } from "@/components/CloserResult";
import { MatchResults } from "@/components/MatchResults";
import { PageHeader, type Crumb } from "@/components/PageHeader";
import { StatusPill, type RunStatus } from "@/components/StatusPill";
import { TracePanel, type TracePanelProps } from "@/components/TracePanel";
import type { CloserOutput, RunSummary, Schemas, TraceEvent } from "@/lib/api";
import { formatRunDuration, patientFactChips, patientTitle } from "@/lib/match-results";
import { verdictEventFor } from "@/lib/trace";
import { useTraceSelection } from "@/lib/use-trace-selection";

function FactsStrip({ patient }: { patient: RunSummary["patient"] }) {
  const chips = patientFactChips(patient);
  if (chips.length === 0) return null;
  return (
    <ul aria-label="Patient facts" className="flex flex-wrap gap-2" data-testid="patient-facts">
      {chips.map(({ label, value }) => (
        <li
          key={label}
          className="rounded-md border bg-surface-sunken px-2.5 py-1 text-sm text-foreground"
        >
          <span className="text-ink-4">{label}</span> <span className="font-medium">{value}</span>
        </li>
      ))}
    </ul>
  );
}

export function RunWithTrace({
  runId,
  events,
  live,
  status,
  summary,
  matches,
  closer = null,
  totals,
  onNextSteps,
  runStatus,
  link,
  title,
  breadcrumb,
  children,
}: {
  runId: string;
  events: TraceEvent[];
  live: boolean;
  status: TracePanelProps["status"];
  /** The run's summary (null until loaded): the header's patient, condition and duration. */
  summary: RunSummary | null;
  /** null until the run's results should show. */
  matches: Schemas["TrialMatch"][] | null;
  /** A closer run's answer (null until loaded, or for a match run). */
  closer?: CloserOutput | null;
  /** The run summary's totals for the trace panel (null until loaded). */
  totals?: TracePanelProps["totals"];
  /** "Next steps" on a trial: start the closer agent for it (live match page only). */
  onNextSteps?: (nctId: string) => void;
  /** The run's own status. */
  runStatus: RunStatus;
  /** The other view of this run (live <-> replay). */
  link?: { href: string; label: string };
  /** The page title when the summary names no patient or condition. */
  title: string;
  breadcrumb: Crumb[];
  /** Shown above the results (controls, notices). */
  children?: ReactNode;
}) {
  const selection = useTraceSelection(events);
  const verdictEventIds = useMemo(
    () => new Set((matches ?? []).flatMap((m) => m.verdicts.map((v) => v.trace_event_id))),
    [matches],
  );
  const highlighted = verdictEventFor(events, selection.selectedId, verdictEventIds);
  const wallTime = runStatus === "running" ? null : (summary?.totals.wall_time_s ?? null);

  return (
    <>
      <PageHeader
        breadcrumb={breadcrumb}
        trail={
          <>
            <span className="font-mono break-all text-foreground">{runId}</span>
            <StatusPill
              status={runStatus}
              detail={wallTime === null ? null : formatRunDuration(wallTime)}
            />
            {link && (
              <Link href={link.href} className="font-medium link sm:ml-auto">
                {link.label}
              </Link>
            )}
          </>
        }
        title={patientTitle(summary?.patient ?? null, summary?.condition ?? null) ?? title}
        description={summary && <FactsStrip patient={summary.patient} />}
      />
      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]">
        <div className="flex min-w-0 flex-col gap-4">
          {children}
          {runStatus === "failed" && (
            <p className="text-sm text-destructive">Run failed; the error event is in the trace.</p>
          )}
          {closer && <CloserResult output={closer} />}
          {matches && summary && (
            <MatchResults
              matches={matches}
              maxUnknownsForLikely={summary.max_unknowns_for_likely}
              highlightedEventId={highlighted}
              onWhy={selection.focus}
              onNextSteps={onNextSteps}
            />
          )}
        </div>
        {/* Sticky wrapper: the trace stays in view while the results column scrolls. */}
        <div className="min-w-0 lg:sticky lg:top-4" data-testid="trace-column">
          <TracePanel
            runId={runId}
            events={events}
            selection={selection}
            verdictEventIds={verdictEventIds}
            live={live}
            status={status}
            totals={totals}
          />
        </div>
      </div>
    </>
  );
}
