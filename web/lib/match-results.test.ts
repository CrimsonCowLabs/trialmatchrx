// Unit tests for the match results page helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { Schemas } from "./api.ts";
import {
  countLabel,
  formatRunDuration,
  initialView,
  locateVerdict,
  patientFactChips,
  patientTitle,
  tierCounts,
  tierHint,
} from "./match-results.ts";

type PatientFacts = Schemas["PatientFacts"];

function patient(over: Partial<PatientFacts> = {}): PatientFacts {
  return {
    age: 61,
    sex: "male",
    conditions: [{ value: "type 2 diabetes" }],
    labs: {
      hba1c: { value: 8.4, unit: "%" },
      egfr: { value: 48, unit: "mL/min/1.73m2" },
    },
    vitals: {},
    meds: [{ value: "metformin" }, { value: "lisinopril" }],
    pregnant: null,
    smoker: null,
    lat: 38.58,
    lon: -121.49,
    place: "Sacramento, CA",
    ...over,
  };
}

test("the title is the patient's age and sex, then the run's condition", () => {
  assert.equal(patientTitle(patient(), "type 2 diabetes"), "61 M · type 2 diabetes");
});

test("the title keeps whatever is known and is null when nothing is", () => {
  assert.equal(patientTitle(patient({ sex: null }), null), "61");
  assert.equal(patientTitle(null, "type 2 diabetes"), "type 2 diabetes");
  assert.equal(patientTitle(patient({ age: null, sex: null }), null), null);
});

test("the facts strip shows age, HbA1c, eGFR, meds and place from the parsed facts", () => {
  assert.deepEqual(patientFactChips(patient()), [
    { label: "Age", value: "61" },
    { label: "HbA1c", value: "8.4%" },
    { label: "eGFR", value: "48 mL/min/1.73m2" },
    { label: "Meds", value: "metformin, lisinopril" },
    { label: "Near", value: "Sacramento, CA" },
  ]);
});

test("a fact the patient doesn't have is left out of the strip, not shown as a placeholder", () => {
  const sparse = patient({ age: null, labs: { egfr: { value: 48 } }, meds: [], place: null });
  assert.deepEqual(patientFactChips(sparse), [{ label: "eGFR", value: "48" }]);
  assert.deepEqual(patientFactChips(null), []);
});

test("a run's duration reads in tenths of a second under a minute, then minutes and seconds", () => {
  assert.equal(formatRunDuration(18.44), "18.4 s");
  assert.equal(formatRunDuration(0.04), "0.0 s");
  assert.equal(formatRunDuration(72.4), "1 min 12 s");
  assert.equal(formatRunDuration(120), "2 min");
});

test("each tier's hint states the rule, with the threshold the API ranked by", () => {
  assert.equal(tierHint("likely", 2), "No criterion fails, at most 2 unknown");
  assert.equal(tierHint("needs_info", 2), "No criterion fails, more than 2 unknown");
  assert.equal(tierHint("ineligible", 2), "At least one criterion fails");
});

type TrialMatch = Schemas["TrialMatch"];

function trial(nct: string, tier: TrialMatch["tier"], eventIds: string[] = []): TrialMatch {
  return {
    nct_id: nct,
    title: `Trial ${nct}`,
    phase: null,
    distance_mi: null,
    tier,
    counts: {},
    verdicts: eventIds.map((id, i) => ({
      criterion_id: `inc-${i + 1}`,
      outcome: "pass",
      method: "rule",
      criterion_quote: "q",
      patient_evidence: null,
      rationale: "r",
      verified: true,
      trace_event_id: id,
    })),
  };
}

test("the likely tab opens with its first (top-ranked) trial expanded", () => {
  const matches = [trial("A", "likely"), trial("B", "likely"), trial("C", "ineligible")];
  assert.deepEqual(initialView(matches), { tier: "likely", expanded: "A" });
});

test("with no likely trial, the first tier that has trials opens with nothing expanded", () => {
  const matches = [trial("B", "needs_info"), trial("C", "ineligible")];
  assert.deepEqual(initialView(matches), { tier: "needs_info", expanded: null });
  assert.deepEqual(initialView([]), { tier: "likely", expanded: null });
});

test("each tier tab counts its trials, in tier order", () => {
  const matches = [trial("A", "likely"), trial("C", "ineligible"), trial("D", "ineligible")];
  assert.deepEqual(tierCounts(matches), { likely: 1, needs_info: 0, ineligible: 2 });
});

test("a selected trace event is located at the tier and trial of the verdict it produced", () => {
  const matches = [trial("A", "likely", ["e1"]), trial("C", "ineligible", ["e2", "e3"])];
  assert.deepEqual(locateVerdict(matches, "e3"), { tier: "ineligible", nctId: "C" });
  assert.equal(locateVerdict(matches, "nope"), null);
  assert.equal(locateVerdict(matches, null), null);
});

test("a trial's outcome counts read OK / disqualify / unknown, zeros included", () => {
  assert.equal(countLabel({ pass: 7, unknown: 1 }), "7 OK · 0 disqualify · 1 unknown");
});
