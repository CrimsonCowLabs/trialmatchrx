// Pure helpers for the match results page (RunWithTrace / MatchResults). Only a type import
// from ./api.ts and the pure ./browse.ts, so node:test can load this file directly.
import type { Schemas } from "./api.ts";
import { TIERS } from "./browse.ts";

type PatientFacts = Schemas["PatientFacts"];
type RunSummary = Schemas["RunSummary"];
type Fact = Schemas["Fact"];
type TrialMatch = Schemas["TrialMatch"];
type Tier = TrialMatch["tier"];
type TierCounts = Schemas["TierCounts"];

/** A finished run's wall time: "18.4 s" under a minute, else "1 min 12 s" / "2 min". */
export function formatRunDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const total = Math.round(seconds);
  const min = Math.floor(total / 60);
  const sec = total % 60;
  return sec ? `${min} min ${sec} s` : `${min} min`;
}

/** The rule that puts a trial in `tier` (SPEC.md "Ranking"), with the run's threshold. */
export function tierHint(tier: Tier, maxUnknownsForLikely: number): string {
  switch (tier) {
    case "likely":
      return `No criterion fails, at most ${maxUnknownsForLikely} unknown`;
    case "needs_info":
      return `No criterion fails, more than ${maxUnknownsForLikely} unknown`;
    case "ineligible":
      return "At least one criterion fails";
  }
}

/** How many trials each tier tab holds. */
export function tierCounts(matches: TrialMatch[]): TierCounts {
  const counts: TierCounts = { likely: 0, needs_info: 0, ineligible: 0 };
  for (const m of matches) counts[m.tier] += 1;
  return counts;
}

export interface ResultsView {
  /** The tier tab shown. */
  tier: Tier;
  /** NCT ID of the expanded trial card, if any. */
  expanded: string | null;
}

/** The view a run's results open on: the first tier that has trials (likely when it has any),
 *  with the first likely trial expanded. Matches arrive in rank order. */
export function initialView(matches: TrialMatch[]): ResultsView {
  const tier = TIERS.find(({ tier: t }) => matches.some((m) => m.tier === t))?.tier ?? "likely";
  const expanded = matches.find((m) => m.tier === "likely")?.nct_id ?? null;
  return { tier, expanded };
}

/** Where the verdict a trace event produced sits: its trial and that trial's tier. */
export function locateVerdict(
  matches: TrialMatch[],
  traceEventId: string | null,
): { tier: Tier; nctId: string } | null {
  if (!traceEventId) return null;
  const m = matches.find((x) => x.verdicts.some((v) => v.trace_event_id === traceEventId));
  return m ? { tier: m.tier, nctId: m.nct_id } : null;
}

/** "7 OK · 0 disqualifying · 1 unknown" from a trial's outcome counts. */
export function countLabel(counts: Record<string, number>): string {
  const { pass = 0, fail = 0, unknown = 0 } = counts;
  return `${pass} OK · ${fail} disqualifying · ${unknown} unknown`;
}

/** SPEC.md's trial-search radius, kept as the meaning of "near": the search itself reaches
 *  100 mi (the seeded radius), and a trial whose nearest site is farther than this is shown
 *  with a warning rather than dropped. */
export const NEAR_RADIUS_MI = 50;

/** "Outside 50 mi" when the trial's nearest site is past NEAR_RADIUS_MI, else null (exactly
 *  50.0 is inside; no site coordinates means no distance and no warning). */
export function distanceWarning(distanceMi: number | null): string | null {
  return distanceMi !== null && distanceMi > NEAR_RADIUS_MI
    ? `Outside ${NEAR_RADIUS_MI} mi`
    : null;
}

type Verdict = Schemas["Verdict"];

const OUTCOME_PRIORITY: Record<Verdict["outcome"], number> = { fail: 0, unknown: 1, pass: 2 };

/** The criteria an expanded trial card shows on mobile before "Show all N criteria": up to
 *  `limit`, the highlighted verdict first, then failures, then unknowns (what decides the
 *  tier), then passes; shown in the trial's own order. */
export function shortCriteria(
  verdicts: Verdict[],
  highlightedEventId: string | null,
  limit: number,
): Verdict[] {
  const rank = (v: Verdict) =>
    v.trace_event_id === highlightedEventId ? -1 : OUTCOME_PRIORITY[v.outcome];
  const keep = new Set(
    verdicts
      .map((v, i) => ({ v, i }))
      .sort((a, b) => rank(a.v) - rank(b.v) || a.i - b.i)
      .slice(0, limit)
      .map(({ v }) => v),
  );
  return verdicts.filter((v) => keep.has(v));
}

export type RunTab = "results" | "trace";

/** A request to bring a verdict into view on the Results tab; a new nonce re-asks for the
 *  same verdict (View verdict twice on one event still reveals it). */
export interface RevealRequest {
  eventId: string;
  nonce: number;
}

/** Which tab a run page shows below `lg` (side by side from `lg`, where the tab is moot). */
export interface RunTabs {
  tab: RunTab;
  reveal: RevealRequest | null;
}

export type RunTabsAction =
  | { type: "show"; tab: RunTab }
  /** "Why?" on a verdict: its trace event is focused on the Trace tab. */
  | { type: "why" }
  /** "View verdict" in the trace sheet: back to Results, revealing the verdict `eventId`. */
  | { type: "view-verdict"; eventId: string }
  /** The revealed row has scrolled into view: drop the request, so a later remount of that
   *  row (tier switch, card reopened) doesn't scroll again. */
  | { type: "revealed" };

export const INITIAL_RUN_TABS: RunTabs = { tab: "results", reveal: null };

export function runTabsReducer(state: RunTabs, action: RunTabsAction): RunTabs {
  switch (action.type) {
    case "show":
      return { ...state, tab: action.tab };
    case "why":
      return { ...state, tab: "trace" };
    case "view-verdict":
      return {
        tab: "results",
        reveal: { eventId: action.eventId, nonce: (state.reveal?.nonce ?? 0) + 1 },
      };
    case "revealed":
      return state.reveal ? { ...state, reveal: null } : state;
  }
}

/** The mobile Trace tab: "Trace · 41", the number of trace events the run has so far. */
export const traceTabLabel = (eventCount: number) => `Trace · ${eventCount}`;

export type FactChip = { label: string; value: string };

/** "61 M · type 2 diabetes": the run's patient label, then its condition; whichever parts are
 *  known, null when none is (or there is no summary yet). */
export function patientTitle(
  summary: Partial<Pick<RunSummary, "patient_label" | "condition">> | null,
): string | null {
  return [summary?.patient_label, summary?.condition].filter(Boolean).join(" · ") || null;
}

/** "8.4%", "48 mL/min/1.73m2": a fact's value with its unit. */
export function factValue({ value, unit }: Pick<Fact, "value" | "unit">): string {
  if (!unit) return String(value);
  return unit === "%" ? `${value}%` : `${value} ${unit}`;
}

/** The facts strip: age, HbA1c, eGFR, meds and place, each only when the patient has it. */
export function patientFactChips(patient: PatientFacts | null): FactChip[] {
  if (!patient) return [];
  const { hba1c, egfr } = patient.labs;
  const chips: (FactChip | null)[] = [
    patient.age != null ? { label: "Age", value: String(patient.age) } : null,
    hba1c ? { label: "HbA1c", value: factValue(hba1c) } : null,
    egfr ? { label: "eGFR", value: factValue(egfr) } : null,
    patient.meds.length
      ? { label: "Meds", value: patient.meds.map((m) => String(m.value)).join(", ") }
      : null,
    patient.place ? { label: "Near", value: patient.place } : null,
  ];
  return chips.filter((c): c is FactChip => c !== null);
}
