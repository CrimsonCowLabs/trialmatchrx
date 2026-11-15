"use client";

// Design 07. GET /api/runs: the most recent match runs, newest first. Each row links to its
// match view; a done run also offers Replay, a failed one its Trace (`runAction`). A table from
// md up, a list of cards below.
import { Plus } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/PageHeader";
import { StatusPill } from "@/components/StatusPill";
import { TierChips, TierLegend } from "@/components/TierChips";
import { Button } from "@/components/ui/button";
import { Card, CardFooter } from "@/components/ui/card";
import { api, type RunListItem } from "@/lib/api";
import { runAction, runLinks } from "@/lib/browse";
import { countNoun } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

const LIMIT = 50;

const loadRuns = () => api.listRuns({ kind: "match", limit: LIMIT });

const started = (run: RunListItem) =>
  new Date(run.created_at).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

/** The patient is labelled once the run has finished. */
const patient = (run: RunListItem) =>
  run.patient_label ?? (run.status === "running" ? "–" : "Patient not parsed");

/** Counts mean nothing until the run is done; the status pill says why. */
function Matches({ run }: { run: RunListItem }) {
  return run.status === "done" ? (
    <TierChips counts={run.tier_counts} />
  ) : (
    <span className="text-ink-4">–</span>
  );
}

function ActionLink({ run }: { run: RunListItem }) {
  const action = runAction(run);
  if (!action) return null;
  return (
    <Link href={action.href} className="link text-sm font-medium" data-testid="run-action">
      {action.label}
    </Link>
  );
}

function RunsTable({ runs }: { runs: RunListItem[] }) {
  return (
    <Card className="hidden py-0 md:flex">
      <table className="w-full text-sm" data-testid="runs-table">
        <thead className="border-b border-line-soft text-left text-xs tracking-wide text-ink-4 uppercase">
          <tr>
            <th className="py-3 pr-5 pl-5 font-medium">Started</th>
            <th className="py-3 pr-5 font-medium">Status</th>
            <th className="py-3 pr-5 font-medium">Patient</th>
            <th className="py-3 pr-5 font-medium">Matches</th>
            <th className="py-3 pr-5 font-medium">
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.run_id} className="border-t border-line-soft first:border-t-0">
              <td className="py-3.5 pr-5 pl-5 font-mono whitespace-nowrap tabular-nums">
                <Link href={runLinks(run).view} className="hover:text-teal hover:underline">
                  {started(run)}
                </Link>
              </td>
              <td className="py-3.5 pr-5">
                <StatusPill status={run.status} />
              </td>
              <td className="py-3.5 pr-5 text-[0.9375rem] font-medium">{patient(run)}</td>
              <td className="py-3.5 pr-5">
                <Matches run={run} />
              </td>
              <td className="py-3.5 pr-5 text-right whitespace-nowrap">
                <ActionLink run={run} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <CardFooter className="bg-card px-5">
        <TierLegend />
      </CardFooter>
    </Card>
  );
}

function RunCards({ runs }: { runs: RunListItem[] }) {
  return (
    <ul className="flex flex-col gap-3 md:hidden" data-testid="runs-list">
      {runs.map((run) => (
        <li key={run.run_id}>
          <Card size="sm" className="gap-2 px-4">
            <div className="flex items-center justify-between gap-3">
              <Link
                href={runLinks(run).view}
                className="min-w-0 truncate text-[0.9375rem] font-medium hover:underline"
              >
                {patient(run)}
              </Link>
              <StatusPill status={run.status} />
            </div>
            <div className="flex items-center justify-between gap-3">
              <Matches run={run} />
              <span className="font-mono text-xs text-ink-4 tabular-nums">{started(run)}</span>
            </div>
            {runAction(run) && (
              <div>
                <ActionLink run={run} />
              </div>
            )}
          </Card>
        </li>
      ))}
    </ul>
  );
}

function Body({ data, error }: { data: RunListItem[] | null; error: string | null }) {
  if (error) return <p className="text-sm break-words text-destructive">{error}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Loading runs…</p>;
  if (data.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No match runs yet.{" "}
        <Link href="/match" className="link underline">
          Match a patient
        </Link>{" "}
        to start one.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <RunsTable runs={data} />
      <RunCards runs={data} />
    </div>
  );
}

/** "The 50 most recent runs, newest first" when the list is full, else "3 runs, newest first". */
function countLine(runs: RunListItem[]): string {
  if (runs.length === LIMIT) return `The ${LIMIT} most recent runs, newest first`;
  return `${runs.length} ${countNoun(runs.length, "run", "runs")}, newest first`;
}

export function RunsView() {
  const { data, error } = useLoad(loadRuns);
  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Home", href: "/" }]}
        title="Match runs"
        description={
          data && data.length > 0 ? (
            <span data-testid="runs-count">{countLine(data)}</span>
          ) : (
            "Past match runs, newest first. Open one to see its tiers, verdicts and trace again."
          )
        }
        actions={
          <Button
            render={<Link href="/match" />}
            nativeButton={false}
            size="lg"
            aria-label="Match a patient"
          >
            <Plus className="md:hidden" />
            <span className="hidden md:inline">Match a patient</span>
          </Button>
        }
      />
      <Body data={data} error={error} />
    </>
  );
}
