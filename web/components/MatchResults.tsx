"use client";

// Ranked trials grouped by tier; each trial lists its criterion verdicts.
// The API already returns matches in rank order, so grouping keeps that order within a tier.
import { useState } from "react";

import { CriterionRow } from "@/components/CriterionRow";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Schemas } from "@/lib/api";

type TrialMatch = Schemas["TrialMatch"];
type Tier = TrialMatch["tier"];

const TIERS: { tier: Tier; title: string; hint: string }[] = [
  { tier: "likely", title: "Likely eligible", hint: "No criterion fails, at most 2 unknown" },
  { tier: "needs_info", title: "Needs info", hint: "No criterion fails, more data needed" },
  { tier: "ineligible", title: "Ineligible", hint: "At least one criterion fails" },
];

function TrialCard({ match }: { match: TrialMatch }) {
  const [open, setOpen] = useState(match.tier !== "ineligible");
  const { pass = 0, fail = 0, unknown = 0 } = match.counts;
  return (
    <li data-testid="trial-match" data-nct={match.nct_id} className="rounded-md border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-baseline gap-x-2 gap-y-1 px-3 py-2 text-left hover:bg-muted"
      >
        <span className="font-mono text-xs">{match.nct_id}</span>
        <span className="flex-1 text-sm font-medium">{match.title}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {match.phase ?? "phase n/a"} ·{" "}
          {match.distance_mi === null ? "distance n/a" : `${match.distance_mi} mi`}
        </span>
        <span className="text-xs tabular-nums">
          <span className="text-emerald-600">{pass} ok</span> ·{" "}
          <span className="text-red-600">{fail} disqualifying</span> ·{" "}
          <span className="text-amber-500">{unknown} unknown</span>
        </span>
      </button>
      {open && (
        <ul className="border-t px-3">
          {match.verdicts.map((v) => (
            <CriterionRow key={v.criterion_id} verdict={v} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function MatchResults({ matches }: { matches: TrialMatch[] }) {
  if (matches.length === 0) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          No trials matched. Seed the cache (`make seed`) or widen the radius.
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      {TIERS.map(({ tier, title, hint }) => {
        const inTier = matches.filter((m) => m.tier === tier);
        return (
          <Card key={tier} data-testid={`tier-${tier}`}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                {title} <Badge variant="outline">{inTier.length}</Badge>
              </CardTitle>
              <p className="text-xs text-muted-foreground">{hint}</p>
            </CardHeader>
            <CardContent>
              {inTier.length === 0 ? (
                <p className="text-sm text-muted-foreground">None.</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {inTier.map((m) => (
                    <TrialCard key={m.nct_id} match={m} />
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
