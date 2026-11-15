// Pure helpers for the Patient facts panel: every fact the run's patient parse kept, with the
// quote it came from, plus the facts it dropped because their quote failed verification.
// Provenance is read off the run's `parse_patient` trace step (pinned by
// api/tests/test_parse_patient.py). No React, so node:test can load this file directly.
import type { Schemas, TraceEvent } from "./api.ts";
import { countNoun, formatCount } from "./format.ts";
import { factValue } from "./match-results.ts";
import { measureLabel } from "./measures.ts";

type PatientFacts = Schemas["PatientFacts"];

/** A fact the parse dropped because its quote was not found in the input: `path` as the parse
 *  names it ("age", "location", "conditions[2]", "labs.egfr"), `fact` the model's draft. */
export interface UnverifiedFact {
  path: string;
  fact: Record<string, unknown>;
}

export interface ParseProvenance {
  source: "quoted" | "record";
  scalarQuotes: Record<string, string>;
  unverified: UnverifiedFact[];
}

export type FactQuote =
  | { kind: "verified"; text: string }
  | { kind: "unverified"; text: string }
  | { kind: "record" }
  | { kind: "none" };

export type FactGroup = "Patient" | "Conditions" | "Labs" | "Vitals" | "Medications";

export interface FactRow {
  key: string;
  group: FactGroup;
  label: string;
  value: string;
  date: string | null;
  quote: FactQuote;
}

const yesNo = (b: boolean) => (b ? "yes" : "no");

export function patientFactRows(
  patient: PatientFacts,
  provenance: ParseProvenance | null,
): FactRow[] {
  const fromRecord = provenance?.source === "record";
  const quoteOf = (span: string | null | undefined): FactQuote =>
    fromRecord ? { kind: "record" } : span ? { kind: "verified", text: span } : { kind: "none" };
  const scalarQuote = (path: string) => quoteOf(provenance?.scalarQuotes[path]);

  const kept: FactRow[] = [];
  const scalar = (key: string, label: string, value: string, quotePath = key) =>
    kept.push({ key, group: "Patient", label, value, date: null, quote: scalarQuote(quotePath) });
  if (patient.age != null) scalar("age", "Age", String(patient.age));
  if (patient.sex != null) scalar("sex", "Sex", patient.sex);
  if (patient.pregnant != null) scalar("pregnant", "Pregnant", yesNo(patient.pregnant));
  if (patient.smoker != null) scalar("smoker", "Smoker", yesNo(patient.smoker));
  // Runs from before PatientFacts had `place` only have the coordinates.
  const where = patient.place ?? coordinates(patient.lat, patient.lon);
  if (where != null) scalar("place", "Lives in", where, "location");

  patient.conditions.forEach((f, i) =>
    kept.push({
      key: `conditions[${i}]`,
      group: "Conditions",
      label: "Condition",
      value: String(f.value),
      date: f.date ?? null,
      quote: quoteOf(f.source_span),
    }),
  );
  const measures = (head: "labs" | "vitals", group: FactGroup) => {
    for (const [name, f] of Object.entries(patient[head])) {
      kept.push({
        key: `${head}.${name}`,
        group,
        label: measureLabel(name),
        value: factValue(f),
        date: f.date ?? null,
        quote: quoteOf(f.source_span),
      });
    }
  };
  measures("labs", "Labs");
  measures("vitals", "Vitals");
  patient.meds.forEach((f, i) =>
    kept.push({
      key: `meds[${i}]`,
      group: "Medications",
      label: "Medication",
      value: String(f.value),
      date: f.date ?? null,
      quote: quoteOf(f.source_span),
    }),
  );
  const dropped = (provenance?.unverified ?? [])
    .map(unverifiedRow)
    .filter((r): r is FactRow => r !== null);
  // Each group: the kept facts, then the ones whose quote failed verification.
  return GROUPS.flatMap((g) => [
    ...kept.filter((r) => r.group === g),
    ...dropped.filter((r) => r.group === g),
  ]);
}

const GROUPS: FactGroup[] = ["Patient", "Conditions", "Labs", "Vitals", "Medications"];

const SCALARS: Record<string, string> = {
  age: "Age",
  sex: "Sex",
  pregnant: "Pregnant",
  smoker: "Smoker",
  location: "Lives in",
};

function coordinates(lat: unknown, lon: unknown): string | null {
  if (typeof lat !== "number" || typeof lon !== "number") return null;
  return `${lat.toFixed(2)}, ${lon.toFixed(2)}`;
}

const str = (v: unknown) => (typeof v === "boolean" ? yesNo(v) : String(v ?? ""));

function unverifiedRow({ path, fact }: UnverifiedFact, i: number): FactRow | null {
  const quote: FactQuote = { kind: "unverified", text: str(fact.source_span) };
  // Indexed: a note can hold two readings of one lab whose quotes both fail.
  const base = { key: `unverified-${i}:${path}`, quote };
  if (path in SCALARS) {
    const value =
      path === "location"
        ? (typeof fact.place === "string" && fact.place) || coordinates(fact.lat, fact.lon) || ""
        : str(fact.value);
    return { ...base, group: "Patient", label: SCALARS[path], value, date: null };
  }
  const list = /^(conditions|meds)\[\d+\]$/.exec(path);
  if (list) {
    const isCondition = list[1] === "conditions";
    return {
      ...base,
      group: isCondition ? "Conditions" : "Medications",
      label: isCondition ? "Condition" : "Medication",
      // As the parse stores the kept ones.
      value: str(fact.value).trim().toLowerCase(),
      date: null,
    };
  }
  const measure = /^(labs|vitals)\.(.+)$/.exec(path);
  if (measure) {
    const unit = typeof fact.unit === "string" ? fact.unit : null;
    return {
      ...base,
      group: measure[1] === "labs" ? "Labs" : "Vitals",
      label: measureLabel(measure[2]),
      value: factValue({ value: str(fact.value), unit }),
      date: typeof fact.date === "string" ? fact.date : null,
    };
  }
  return null;
}

/** The panel heading's count: "8 facts · 1 unverified, not used", "12 facts from the record". */
export function factsSummary(rows: FactRow[]): string {
  if (rows.length === 0) return "No facts extracted";
  const used = rows.filter((r) => r.quote.kind !== "unverified");
  const dropped = rows.length - used.length;
  const fromRecord = used.length > 0 && used.every((r) => r.quote.kind === "record");
  return (
    countNoun(used.length, "fact", "facts") +
    (fromRecord ? " from the record" : "") +
    (dropped ? ` · ${formatCount(dropped)} unverified, not used` : "")
  );
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** Where the run's patient facts came from, read off its `parse_patient` trace step: a FHIR
 *  bundle (`input.source`), or a quoted text input, whose step output holds the scalar facts'
 *  verified quotes (`scalar_spans`) and whose `span:<path>` guardrail events are the facts
 *  dropped because their quote was not found. Null until the parse step is in the trace. */
export function parseProvenance(events: TraceEvent[]): ParseProvenance | null {
  const step = events.find((e) => e.kind === "step" && e.name === "parse_patient");
  if (!step) return null;
  if (step.input?.source === "fhir_bundle") {
    return { source: "record", scalarQuotes: {}, unverified: [] };
  }
  const spans = step.output?.scalar_spans;
  const scalarQuotes: Record<string, string> = {};
  if (isRecord(spans)) {
    for (const [path, text] of Object.entries(spans)) {
      if (typeof text === "string") scalarQuotes[path] = text;
    }
  }
  const unverified: UnverifiedFact[] = [];
  for (const e of events) {
    if (e.kind !== "guardrail" || e.parent_id !== step.id || !e.name.startsWith("span:")) continue;
    const path = e.input?.path;
    const fact = e.input?.fact;
    if (typeof path === "string" && isRecord(fact)) unverified.push({ path, fact });
  }
  return { source: "quoted", scalarQuotes, unverified };
}
