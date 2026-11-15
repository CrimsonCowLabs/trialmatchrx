"use client";

// GET /api/runs: the most recent match runs, newest first.
import Link from "next/link";

import { StatusPill } from "@/components/StatusPill";
import { TierChips, TierLegend } from "@/components/TierChips";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { api } from "@/lib/api";
import { runLinks } from "@/lib/browse";
import { useLoad } from "@/lib/use-load";

const LIMIT = 50;

const loadRuns = () => api.listRuns({ kind: "match", limit: LIMIT });

export function RunsView() {
  const { data, error } = useLoad(loadRuns);
  if (error) return <p className="text-sm text-destructive">{error}</p>;
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
      <p className="text-sm text-muted-foreground">
        {data.length === LIMIT ? `The ${LIMIT} most recent runs.` : `${data.length} runs.`}
      </p>
      <Card>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="runs-table">
            <thead className="text-left text-xs tracking-wide text-muted-foreground uppercase">
              <tr>
                <th className="py-2 pr-4 font-medium">Started</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 pr-4 font-medium">Patient</th>
                <th className="py-2 pr-4 font-medium">Matches</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {data.map((run) => {
                const links = runLinks(run);
                return (
                  <tr key={run.run_id} className="border-t border-line-soft">
                    <td className="py-2.5 pr-4 font-mono whitespace-nowrap tabular-nums">
                      <Link href={links.view} className="hover:text-teal hover:underline">
                        {new Date(run.created_at).toLocaleString()}
                      </Link>
                    </td>
                    <td className="py-2.5 pr-4">
                      <StatusPill status={run.status} />
                    </td>
                    <td className="py-2.5 pr-4 font-medium whitespace-nowrap">
                      {run.patient_label ?? "–"}
                    </td>
                    <td className="py-2.5 pr-4">
                      {/* Counts mean nothing until the run is done; the status pill says why. */}
                      {run.status === "done" ? (
                        <TierChips counts={run.tier_counts} />
                      ) : (
                        <span className="text-ink-4">–</span>
                      )}
                    </td>
                    <td className="py-2.5 text-right whitespace-nowrap">
                      {links.replay && (
                        <Link
                          href={links.replay}
                          className="font-medium link"
                        >
                          Replay
                        </Link>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </CardContent>
        <CardFooter className="bg-card">
          <TierLegend />
        </CardFooter>
      </Card>
    </div>
  );
}
