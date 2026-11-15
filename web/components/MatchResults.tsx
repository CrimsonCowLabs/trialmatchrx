"use client";

// Ranked trials behind a tier switch (likely / needs info / ineligible) with the rule that puts
// a trial in the shown tier. Each trial is a card that expands to its criterion verdicts and a
// "Next steps" block; the first likely trial starts expanded. The API returns matches in rank
// order, so filtering by tier keeps that order.
import { MapPin, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { CriterionRow } from "@/components/CriterionRow";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { Schemas, Tier } from "@/lib/api";
import {
  countLabel,
  distanceWarning,
  initialView,
  NEAR_RADIUS_MI,
  locateVerdict,
  shortCriteria,
  tierCounts,
  tierHint,
  type RevealRequest,
} from "@/lib/match-results";

/** How many criteria an open card lists on a phone before "Show all" (as in the design). */
const SHORT_CRITERIA_LIMIT = 3;

type TrialMatch = Schemas["TrialMatch"];

const TIER_TABS: { tier: Tier; label: string; shortLabel: string; count: string }[] = [
  { tier: "likely", label: "Likely eligible", shortLabel: "Likely", count: "text-tier-likely" },
  { tier: "needs_info", label: "Needs info", shortLabel: "Needs info", count: "text-tier-needs-info" },
  { tier: "ineligible", label: "Ineligible", shortLabel: "Ineligible", count: "text-tier-ineligible" },
];

interface Linking {
  /** `trace_event_id` of the verdict to highlight (the selected trace event produced it). */
  highlightedEventId?: string | null;
  onWhy?: (traceEventId: string) => void;
  /** "View verdict" from the mobile trace sheet: show this verdict's tier and card again and
   *  scroll it into view, even if it was already highlighted. */
  reveal?: RevealRequest | null;
  /** "Next steps": run the closer agent on a trial. No button when absent, or on an
   *  ineligible trial (a disqualifying criterion has no follow-up that helps). */
  onNextSteps?: (nctId: string) => void;
}

/** Pass / fail / unknown as proportional segments; the label beside it carries the numbers. */
function CountBar({ counts }: { counts: Record<string, number> }) {
  const segments = [
    { n: counts.pass ?? 0, tone: "bg-verdict-pass" },
    { n: counts.fail ?? 0, tone: "bg-verdict-fail" },
    { n: counts.unknown ?? 0, tone: "bg-verdict-unknown" },
  ].filter((s) => s.n > 0);
  return (
    <div aria-hidden className="flex min-w-0 flex-1 gap-1">
      {segments.map((s) => (
        <div key={s.tone} className={`h-1.5 rounded-full ${s.tone}`} style={{ flex: s.n }} />
      ))}
    </div>
  );
}

function TrialMeta({ match }: { match: TrialMatch }) {
  const parts = [
    match.nct_id,
    match.phase,
    match.distance_mi === null ? null : `${match.distance_mi} mi`,
  ].filter(Boolean);
  const warning = distanceWarning(match.distance_mi);
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span className="font-mono text-[0.8125rem] text-ink-4">{parts.join(" · ")}</span>
      {warning && (
        <Badge
          variant="outline"
          className="border-verdict-unknown/40 bg-verdict-unknown-bg text-verdict-unknown"
          title={`The nearest site is ${match.distance_mi} mi from the patient, more than ${NEAR_RADIUS_MI} mi of travel.`}
        >
          <MapPin data-icon="inline-start" />
          {warning}
        </Badge>
      )}
    </span>
  );
}

function TrialCard({
  match,
  open,
  onToggle,
  highlightedEventId,
  reveal,
  onWhy,
  onNextSteps,
}: { match: TrialMatch; open: boolean; onToggle: () => void } & Linking) {
  const nextSteps = match.tier !== "ineligible" ? onNextSteps : undefined;
  // Below `lg` an open card lists a few criteria, then "Show all N criteria".
  const [showAll, setShowAll] = useState(false);
  const shortList = new Set(
    shortCriteria(match.verdicts, highlightedEventId ?? null, SHORT_CRITERIA_LIMIT),
  );
  return (
    <li data-testid="trial-match" data-nct={match.nct_id}>
      <Card className="gap-0 py-0">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className={`grid w-full gap-x-5 gap-y-2 px-4 py-4 text-left hover:bg-muted/50 sm:px-5 ${open ? "" : "sm:grid-cols-[minmax(0,1fr)_14rem] sm:items-center"}`}
        >
          <span className="flex min-w-0 flex-col gap-1.5">
            <span className="flex items-center gap-3">
              <TrialMeta match={match} />
              <span className="ml-auto text-[0.8125rem] font-medium text-ink-5">
                {open ? "Collapse" : "Expand"}
              </span>
            </span>
            <span
              className={`text-pretty ${open ? "text-lg leading-snug font-semibold" : "text-base leading-snug font-medium"}`}
            >
              {match.title}
            </span>
          </span>
          <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
            <CountBar counts={match.counts} />
            <span className="text-[0.8125rem] font-medium whitespace-nowrap text-ink-2">
              {countLabel(match.counts)}
            </span>
          </span>
        </button>
        {open && (
          <>
            <ul className="border-t border-line-soft">
              {match.verdicts.map((v) => (
                <CriterionRow
                  key={v.criterion_id}
                  verdict={v}
                  highlighted={!!highlightedEventId && v.trace_event_id === highlightedEventId}
                  revealNonce={reveal?.eventId === v.trace_event_id ? reveal.nonce : undefined}
                  onWhy={onWhy}
                  collapsedOnMobile={!showAll && !shortList.has(v)}
                />
              ))}
            </ul>
            {shortList.size < match.verdicts.length && (
              // -mt-px: sits on the last shown row's bottom border instead of doubling it.
              <button
                type="button"
                onClick={() => setShowAll((s) => !s)}
                aria-expanded={showAll}
                data-testid="show-all-criteria"
                className="-mt-px border-t border-line-soft px-4 py-3 text-left text-sm font-medium link lg:hidden"
              >
                {showAll ? "Show fewer criteria" : `Show all ${match.verdicts.length} criteria`}
              </button>
            )}
            <div
              data-testid="trial-next-steps"
              className="grid grid-cols-[repeat(auto-fit,minmax(0,1fr))] items-center gap-2 border-t border-line-soft px-4 py-3.5 sm:flex sm:flex-wrap sm:gap-3 sm:px-5"
            >
              {nextSteps && (
                <Button
                  size="lg"
                  className="px-4"
                  onClick={() => nextSteps(match.nct_id)}
                  data-testid="next-steps"
                >
                  <Sparkles /> Next steps
                </Button>
              )}
              <Link
                href={`/feasibility/${encodeURIComponent(match.nct_id)}`}
                className={buttonVariants({ variant: "outline", size: "lg", className: "px-4" })}
              >
                Cohort feasibility
              </Link>
              {nextSteps && (
                <span className="hidden text-[0.8125rem] text-ink-4 sm:ml-auto sm:inline">
                  Follow-ups, coordinator email, Spanish summary
                </span>
              )}
            </div>
          </>
        )}
      </Card>
    </li>
  );
}

export function MatchResults({
  matches,
  maxUnknownsForLikely,
  highlightedEventId,
  reveal,
  onWhy,
  onNextSteps,
}: {
  matches: TrialMatch[];
  /** The run's tier rule threshold (`RunSummary.max_unknowns_for_likely`). */
  maxUnknownsForLikely: number;
} & Linking) {
  const [view, setView] = useState(() => {
    const { tier, expanded } = initialView(matches);
    return { tier, expanded: new Set(expanded ? [expanded] : []) };
  });
  // When a selected trace event points at a verdict, show its tier and open its card (once per
  // selection, and again on each View verdict; the user can still switch away or collapse).
  // State adjusted during render, React's pattern for reacting to a prop change.
  const located = locateVerdict(matches, highlightedEventId ?? null);
  const locatedKey = located
    ? `${located.tier}/${located.nctId}/${highlightedEventId}/${reveal?.nonce ?? 0}`
    : null;
  const [shownKey, setShownKey] = useState<string | null>(null);
  if (locatedKey !== shownKey) {
    setShownKey(locatedKey);
    if (located) {
      setView((v) => ({ tier: located.tier, expanded: new Set([...v.expanded, located.nctId]) }));
    }
  }

  if (matches.length === 0) {
    return (
      <Card>
        <CardContent className="py-2 text-sm text-muted-foreground">
          No trials matched. Seed the cache (`make seed`) or widen the radius.
        </CardContent>
      </Card>
    );
  }

  const counts = tierCounts(matches);
  const inTier = matches.filter((m) => m.tier === view.tier);
  const toggle = (nct: string) =>
    setView((v) => {
      const expanded = new Set(v.expanded);
      if (!expanded.delete(nct)) expanded.add(nct);
      return { ...v, expanded };
    });

  return (
    <section aria-label="Match results" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div
          role="tablist"
          aria-label="Match tier"
          className="flex flex-wrap gap-0.5 rounded-lg bg-surface-sunken p-0.5 text-sm font-medium"
        >
          {TIER_TABS.map(({ tier, label, shortLabel, count }) => {
            const selected = tier === view.tier;
            return (
              <button
                key={tier}
                type="button"
                role="tab"
                aria-selected={selected}
                data-testid={`tier-${tier}`}
                onClick={() => setView((v) => ({ ...v, tier }))}
                className={`rounded-md px-3.5 py-1.5 ${selected ? "bg-surface shadow-xs" : "text-ink-3 hover:text-foreground"}`}
              >
                {/* The short label keeps all three tabs on one line at 390px. */}
                <span className="sm:hidden">{shortLabel}</span>
                <span className="hidden sm:inline">{label}</span>{" "}
                <span className={`font-mono tabular-nums ${selected ? count : ""}`}>
                  {counts[tier]}
                </span>
              </button>
            );
          })}
        </div>
        <p className="text-[0.8125rem] text-ink-4">{tierHint(view.tier, maxUnknownsForLikely)}</p>
      </div>
      {inTier.length === 0 ? (
        <Card>
          <CardContent className="py-2 text-sm text-muted-foreground">
            No trials in this tier.
          </CardContent>
        </Card>
      ) : (
        <ul role="tabpanel" className="flex flex-col gap-4">
          {inTier.map((m) => (
            <TrialCard
              key={m.nct_id}
              match={m}
              open={view.expanded.has(m.nct_id)}
              onToggle={() => toggle(m.nct_id)}
              highlightedEventId={highlightedEventId}
              reveal={reveal}
              onWhy={onWhy}
              onNextSteps={onNextSteps}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
