"use client";

// GET /api/trials: the cached trials, filtered by NCT ID or title as you type.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/use-load";

const DEBOUNCE_MS = 250;

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
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="py-1 pr-4 font-normal">NCT ID</th>
                      <th className="py-1 pr-4 font-normal">Title</th>
                      <th className="py-1 pr-4 font-normal">Phase</th>
                      <th className="py-1 pr-4 font-normal">Status</th>
                      <th className="py-1 font-normal">Criteria</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.map((trial) => (
                      <tr key={trial.nct_id} className="border-t align-top">
                        <td className="py-1 pr-4 font-mono text-xs whitespace-nowrap">
                          <Link
                            href={`/feasibility/${encodeURIComponent(trial.nct_id)}`}
                            className="underline"
                          >
                            {trial.nct_id}
                          </Link>
                        </td>
                        <td className="py-1 pr-4">{trial.title}</td>
                        <td className="py-1 pr-4 whitespace-nowrap">{trial.phase ?? "–"}</td>
                        <td className="py-1 pr-4 text-xs whitespace-nowrap">
                          {trial.overall_status ?? "–"}
                        </td>
                        <td className="py-1 whitespace-nowrap">
                          {trial.compiled ? (
                            <Badge>{trial.criteria_count} compiled</Badge>
                          ) : (
                            <Badge variant="outline">Not compiled</Badge>
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
