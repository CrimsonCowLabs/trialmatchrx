"use client";

// A run page: the header (breadcrumb with the run's status, duration and Replay / Live view
// link; the patient and their facts), then results on the left and the trace on the right,
// linked both ways. "Why?" on a verdict focuses its trace event; selecting a trace event
// highlights the verdict it produced. The trace column stays in view while the results scroll.
// Below `lg` the two columns become Results / "Trace · N" tabs: Why? switches to the trace and
// opens its event in a bottom sheet, whose View verdict switches back to the criterion.
// Used by the live match and closer pages and the replay page. A closer run's header is its
// own: "Next steps for a 61 M patient", the trial's title, its NCT ID on the breadcrumb line.
// With `collapsibleTrace` (the live closer page) a Show / Hide trace toggle folds the trace
// column away once the agent's answer is there (`traceShown`); while folded there are no tabs.
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useState,
  type Dispatch,
  type ReactNode,
} from "react";

import { CloserResult } from "@/components/CloserResult";
import { MatchResults } from "@/components/MatchResults";
import { PageHeader, type Crumb } from "@/components/PageHeader";
import { PatientFactsPanel } from "@/components/PatientFactsPanel";
import { StatusPill, type RunStatus } from "@/components/StatusPill";
import { TracePanel, type TracePanelProps } from "@/components/TracePanel";
import type { CloserOutput, RunSummary, Schemas, TraceEvent } from "@/lib/api";
import { closerTitle, traceShown } from "@/lib/closer";
import {
  formatRunDuration,
  INITIAL_RUN_TABS,
  patientFactChips,
  patientTitle,
  runTabsReducer,
  traceTabLabel,
  type RunTab,
  type RunTabsAction,
} from "@/lib/match-results";
import { parseProvenance } from "@/lib/patient-facts";
import { verdictEventFor } from "@/lib/trace";
import { useTraceSelection } from "@/lib/use-trace-selection";

function FactsStrip({ patient }: { patient: RunSummary["patient"] }) {
  const chips = patientFactChips(patient);
  if (chips.length === 0) return null;
  return (
    <ul
      aria-label="Patient facts"
      className="flex flex-wrap gap-2"
      data-testid="patient-facts"
    >
      {chips.map(({ label, value }) => (
        <li
          key={label}
          className="rounded-md border bg-surface-sunken px-2.5 py-1 text-sm text-foreground"
        >
          <span className="text-ink-4">{label}</span>{" "}
          <span className="font-medium">{value}</span>
        </li>
      ))}
    </ul>
  );
}

/** Results / "Trace · N" below `lg` (design 03, mobile frames); hidden from `lg`. */
function RunTabBar({
  tab,
  eventCount,
  onShow,
}: {
  tab: RunTab;
  eventCount: number;
  onShow: Dispatch<RunTabsAction>;
}) {
  const tabs: { id: RunTab; label: string }[] = [
    { id: "results", label: "Results" },
    { id: "trace", label: traceTabLabel(eventCount) },
  ];
  return (
    <div
      role="tablist"
      aria-label="Run view"
      className="mb-4 flex rounded-[0.625rem] bg-surface-sunken p-0.5 text-[0.9375rem] font-medium lg:hidden"
    >
      {tabs.map(({ id, label }) => {
        const selected = tab === id;
        return (
          <button
            key={id}
            id={`run-tab-${id}`}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={`run-${id}`}
            data-testid={`run-tab-${id}`}
            onClick={() => onShow({ type: "show", tab: id })}
            className={`flex-1 rounded-lg py-2 text-center ${selected ? "bg-surface shadow-xs" : "text-ink-3"}`}
          >
            {label}
          </button>
        );
      })}
    </div>
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
  collapsibleTrace = false,
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
  /** A Show / Hide trace toggle; the trace starts open and folds away once `closer` shows. */
  collapsibleTrace?: boolean;
  /** Shown above the results (controls, notices). */
  children?: ReactNode;
}) {
  const selection = useTraceSelection(events);
  const [tabs, dispatchTabs] = useReducer(runTabsReducer, INITIAL_RUN_TABS);
  const verdictEventIds = useMemo(
    () =>
      new Set(
        (matches ?? []).flatMap((m) => m.verdicts.map((v) => v.trace_event_id)),
      ),
    [matches],
  );
  const provenance = useMemo(() => parseProvenance(events), [events]);
  const highlighted = verdictEventFor(
    events,
    selection.selectedId,
    verdictEventIds,
  );
  const wallTime =
    runStatus === "running" ? null : (summary?.totals.wall_time_s ?? null);
  const [traceChoice, setTraceChoice] = useState<boolean | null>(null);
  const showTrace =
    !collapsibleTrace || traceShown(traceChoice, closer !== null);
  const header =
    summary?.kind === "closer"
      ? { title: closerTitle(summary), description: summary.trial_title }
      : {
          title: patientTitle(summary) ?? title,
          description: summary && <FactsStrip patient={summary.patient} />,
        };
  const { focus } = selection;
  const onWhy = useCallback(
    (eventId: string) => {
      focus(eventId);
      dispatchTabs({ type: "why" });
    },
    [focus],
  );
  const onViewVerdict = useCallback(
    (eventId: string) => dispatchTabs({ type: "view-verdict", eventId }),
    [],
  );
  // Child effects run first, so the criterion row has scrolled by the time this clears the
  // request; a later remount of that row won't scroll again.
  useEffect(() => {
    if (tabs.reveal) dispatchTabs({ type: "revealed" });
  }, [tabs.reveal]);
  // Below `lg` only the chosen tab's column shows; from `lg` both sit side by side. With the
  // trace folded away there are no tabs and the results always show.
  const shownBelowLg = (tab: RunTab) =>
    !showTrace || tabs.tab === tab ? "" : "max-lg:hidden";

  return (
    <>
      <PageHeader
        breadcrumb={breadcrumb}
        trail={
          <>
            <span className="font-mono break-all text-foreground">
              {closer?.nct_id ?? runId}
            </span>
            <StatusPill
              status={runStatus}
              detail={wallTime === null ? null : formatRunDuration(wallTime)}
            />
            <span className="flex gap-4 sm:ml-auto">
              {link && (
                <Link href={link.href} className="font-medium link">
                  {link.label}
                </Link>
              )}
              {collapsibleTrace && (
                <button
                  type="button"
                  className="font-medium link"
                  aria-expanded={showTrace}
                  aria-controls="run-trace"
                  onClick={() => setTraceChoice(!showTrace)}
                  data-testid="trace-toggle"
                >
                  {showTrace ? "Hide trace" : "Show trace"}
                </button>
              )}
            </span>
          </>
        }
        title={header.title}
        description={header.description}
      />
      {showTrace && (
        <RunTabBar
          tab={tabs.tab}
          eventCount={events.length}
          onShow={dispatchTabs}
        />
      )}
      <div
        className={`grid grid-cols-[minmax(0,1fr)] items-start gap-6 ${showTrace ? "lg:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]" : ""}`}
      >
        <div
          id="run-results"
          role="tabpanel"
          aria-labelledby="run-tab-results"
          className={`flex min-w-0 flex-col gap-4 ${shownBelowLg("results")}`}
        >
          {children}
          {runStatus === "failed" && (
            <p className="text-sm text-destructive">
              Run failed; the error event is in the trace.
            </p>
          )}
          {closer && <CloserResult key={closer.nct_id} output={closer} />}
          {matches && summary?.patient && (
            <PatientFactsPanel
              patient={summary.patient}
              provenance={provenance}
            />
          )}
          {matches && summary && (
            <MatchResults
              matches={matches}
              maxUnknownsForLikely={summary.max_unknowns_for_likely}
              highlightedEventId={highlighted}
              reveal={tabs.reveal}
              onWhy={onWhy}
              onNextSteps={onNextSteps}
            />
          )}
        </div>
        {/* Sticky wrapper: the trace stays in view while the results column scrolls. */}
        <div
          id="run-trace"
          role="tabpanel"
          aria-labelledby="run-tab-trace"
          className={`min-w-0 lg:sticky lg:top-4 ${showTrace ? shownBelowLg("trace") : "hidden"}`}
          data-testid="trace-column"
        >
          <TracePanel
            onViewVerdict={onViewVerdict}
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
