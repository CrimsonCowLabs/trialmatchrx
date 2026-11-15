"use client";

// GET /api/trials: the cached trials, filtered by NCT ID or title as you type.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { trialStatusTone, type TrialStatusTone } from "@/lib/browse";
import { useLoad } from "@/lib/use-load";

const DEBOUNCE_MS = 250;

// Literal class names so Tailwind sees them; colours are the trial-status tokens in globals.css.
const STATUS_DOT = {
  recruiting: "bg-trial-recruiting",
  "not-yet": "bg-trial-not-yet",
  other: "bg-trial-other",
} as const satisfies Record<TrialStatusTone, string>;

export function TrialsView() {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query.trim()), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);
  const load = useCallback(() => api.listTrials(debouncedQuery || undefined), [debouncedQuery]);
  const { data, error } = useLoad(load);

  return (
    <div className="flex flex-col gap-4">
      <Input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter by NCT ID or title"
        aria-label="Filter trials"
        className="max-w-sm"
      />
      {error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : !data ? (
        <p className="text-sm text-muted-foreground">Loading trials…</p>
      ) : data.length === 0 && !debouncedQuery ? (
        <p className="text-sm text-muted-foreground">
          No trials cached yet. Run <code className="font-mono">make seed</code> to fetch the
          T2D/CKD trials.
        </p>
      ) : (
        <>
          <p className="text-sm" data-testid="trials-count">
            <span className="font-semibold tabular-nums">{data.length}</span>{" "}
            {data.length === 1 ? "trial" : "trials"}
            {debouncedQuery ? ` matching “${debouncedQuery}”` : " in the cache"}
          </p>
          {data.length > 0 && (
            <Card>
              <CardContent className="overflow-x-auto">
                <table className="w-full text-sm" data-testid="trials-table">
                  <thead className="text-left text-xs tracking-wide text-muted-foreground uppercase">
                    <tr>
                      <th className="py-2 pr-4 font-medium">NCT ID</th>
                      <th className="py-2 pr-4 font-medium">Title</th>
                      <th className="py-2 pr-4 font-medium">Phase</th>
                      <th className="py-2 pr-4 font-medium">Status</th>
                      <th className="py-2 font-medium">Criteria</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.map((trial) => (
                      <tr key={trial.nct_id} className="border-t border-line-soft align-top">
                        <td className="py-2.5 pr-4 font-mono text-xs whitespace-nowrap">
                          <Link
                            href={`/feasibility/${encodeURIComponent(trial.nct_id)}`}
                            className="font-medium text-teal hover:text-teal-strong hover:underline"
                          >
                            {trial.nct_id}
                          </Link>
                        </td>
                        <td className="min-w-64 py-2.5 pr-4 font-medium">{trial.title}</td>
                        <td className="py-2.5 pr-4 whitespace-nowrap">{trial.phase ?? "–"}</td>
                        <td className="py-2.5 pr-4 text-xs whitespace-nowrap">
                          <span className="inline-flex items-center gap-1.5">
                            <span
                              aria-hidden
                              className={`size-2 rounded-full ${STATUS_DOT[trialStatusTone(trial.overall_status)]}`}
                            />
                            {trial.overall_status ?? "–"}
                          </span>
                        </td>
                        <td className="py-2.5 whitespace-nowrap">
                          {trial.compiled ? (
                            <Badge className="bg-teal-tint text-teal-strong">{trial.criteria_count} compiled</Badge>
                          ) : (
                            <Badge variant="outline" className="border-line-strong text-ink-2">
                              Not compiled
                            </Badge>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
