"use client";

// GET /api/runs: the most recent match runs, newest first.
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { api, type RunListItem } from "@/lib/api";
import { runLinks, tierSummary } from "@/lib/browse";
import { useLoad } from "@/lib/use-load";

const LIMIT = 50;

const STATUS_VARIANT = {
  running: "secondary",
  done: "default",
  failed: "destructive",
} as const satisfies Record<RunListItem["status"], string>;

const loadRuns = () => api.listRuns({ kind: "match", limit: LIMIT });

export function RunsView() {
  const { data, error } = useLoad(loadRuns);
  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Loading runs…</p>;
  if (data.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No match runs yet.{" "}
        <Link href="/match" className="underline">
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
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="py-1 pr-4 font-normal">Started</th>
                <th className="py-1 pr-4 font-normal">Status</th>
                <th className="py-1 pr-4 font-normal">Patient</th>
                <th className="py-1 pr-4 font-normal">Matches</th>
                <th className="py-1 font-normal" />
              </tr>
            </thead>
            <tbody>
              {data.map((run) => {
                const links = runLinks(run);
                return (
                  <tr key={run.run_id} className="border-t">
                    <td className="py-1 pr-4 whitespace-nowrap tabular-nums">
                      <Link href={links.view} className="underline">
                        {new Date(run.created_at).toLocaleString()}
                      </Link>
                    </td>
                    <td className="py-1 pr-4">
                      <Badge variant={STATUS_VARIANT[run.status]}>{run.status}</Badge>
                    </td>
                    <td className="py-1 pr-4 whitespace-nowrap">{run.patient_label ?? "–"}</td>
                    <td className="py-1 pr-4 tabular-nums">{tierSummary(run.tier_counts)}</td>
                    <td className="py-1 text-right whitespace-nowrap">
                      {links.replay && (
                        <Link href={links.replay} className="text-xs underline">
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
      </Card>
    </div>
  );
}
