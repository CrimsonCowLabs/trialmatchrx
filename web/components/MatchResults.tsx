"use client";

// Ranked trials grouped by tier; each trial lists its criterion verdicts.
// The API already returns matches in rank order, so grouping keeps that order within a tier.
import { Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { CriterionRow } from "@/components/CriterionRow";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Schemas } from "@/lib/api";

type TrialMatch = Schemas["TrialMatch"];
type Tier = TrialMatch["tier"];

const TIERS: { tier: Tier; title: string; hint: string }[] = [
  { tier: "likely", title: "Likely eligible", hint: "No criterion fails, at most 2 unknown" },
  { tier: "needs_info", title: "Needs info", hint: "No criterion fails, more data needed" },
  { tier: "ineligible", title: "Ineligible", hint: "At least one criterion fails" },
];

interface Linking {
  /** `trace_event_id` of the verdict to highlight (the selected trace event produced it). */
  highlightedEventId?: string | null;
  onWhy?: (traceEventId: string) => void;
  /** "Next steps": run the closer agent on a trial. No button when absent, or on an
   *  ineligible trial (a disqualifying criterion has no follow-up that helps). */
  onNextSteps?: (nctId: string) => void;
}

function TrialCard({
  match,
  highlightedEventId,
  onWhy,
  onNextSteps,
}: { match: TrialMatch } & Linking) {
  const [open, setOpen] = useState(match.tier !== "ineligible");
  // When this card starts holding the highlighted verdict, open it (once; the user can still
  // collapse it). State adjusted during render, React's pattern for reacting to a prop change.
  const holdsHighlight = match.verdicts.some((v) => v.trace_event_id === highlightedEventId);
  const [heldHighlight, setHeldHighlight] = useState(false);
  if (holdsHighlight !== heldHighlight) {
    setHeldHighlight(holdsHighlight);
    if (holdsHighlight) setOpen(true);
  }
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
            <CriterionRow
              key={v.criterion_id}
              verdict={v}
              highlighted={!!highlightedEventId && v.trace_event_id === highlightedEventId}
              onWhy={onWhy}
            />
          ))}
          <li className="flex flex-wrap items-center gap-3 py-2 text-xs">
            {onNextSteps && match.tier !== "ineligible" && (
              <Button
                size="sm"
                onClick={() => onNextSteps(match.nct_id)}
                data-testid="next-steps"
                title="Agent: follow-ups for the unknowns, a coordinator email, a Spanish summary"
              >
                <Sparkles /> Next steps
              </Button>
            )}
            <Link href={`/feasibility/${encodeURIComponent(match.nct_id)}`} className="underline">
              Feasibility over the 1,000-patient cohort
            </Link>
          </li>
        </ul>
      )}
    </li>
  );
}

export function MatchResults({
  matches,
  highlightedEventId,
  onWhy,
  onNextSteps,
}: { matches: TrialMatch[] } & Linking) {
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
                    <TrialCard
                      key={m.nct_id}
                      match={m}
                      highlightedEventId={highlightedEventId}
                      onWhy={onWhy}
                      onNextSteps={onNextSteps}
                    />
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
