// Pure helpers for the match results page (RunWithTrace / MatchResults). Only a type import
// from ./api.ts and the pure ./browse.ts, so node:test can load this file directly.
import type { Schemas } from "./api.ts";
import { TIERS } from "./browse.ts";

type PatientFacts = Schemas["PatientFacts"];
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

/** "7 OK · 0 disqualify · 1 unknown" from a trial's outcome counts. */
export function countLabel(counts: Record<string, number>): string {
  const { pass = 0, fail = 0, unknown = 0 } = counts;
  return `${pass} OK · ${fail} disqualify · ${unknown} unknown`;
}

export type FactChip = { label: string; value: string };

const SEX_LABEL = { female: "F", male: "M" } as const;

/** "61 M · type 2 diabetes": the parsed age and sex, then the run's condition; whichever parts
 *  are known, null when none is. */
export function patientTitle(patient: PatientFacts | null, condition: string | null): string | null {
  const who = [
    patient?.age != null ? String(patient.age) : null,
    patient?.sex ? SEX_LABEL[patient.sex] : null,
  ]
    .filter(Boolean)
    .join(" ");
  return [who, condition].filter(Boolean).join(" · ") || null;
}

function factValue({ value, unit }: Fact): string {
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
