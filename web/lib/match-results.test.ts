// Unit tests for the match results page helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { Schemas } from "./api.ts";
import {
  countLabel,
  distanceWarning,
  formatRunDuration,
  INITIAL_RUN_TABS,
  initialView,
  locateVerdict,
  patientFactChips,
  patientTitle,
  runTabsReducer,
  shortCriteria,
  tierCounts,
  tierHint,
  traceTabLabel,
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

test("the title is the run's patient label, then its condition", () => {
  const title = patientTitle({ patient_label: "61 M", condition: "type 2 diabetes" });
  assert.equal(title, "61 M · type 2 diabetes");
});

test("the title keeps whatever is known and is null when nothing is", () => {
  assert.equal(patientTitle({ patient_label: "61", condition: null }), "61");
  assert.equal(patientTitle({ condition: "type 2 diabetes" }), "type 2 diabetes");
  assert.equal(patientTitle({}), null);
  assert.equal(patientTitle(null), null);
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

test("a trial's outcome counts read OK / disqualifying / unknown, zeros included", () => {
  assert.equal(countLabel({ pass: 7, unknown: 1 }), "7 OK · 0 disqualifying · 1 unknown");
});

test("a nearest site past 50 mi warns; 50.0 exactly is inside", () => {
  assert.equal(distanceWarning(50.1), "Outside 50 mi");
  assert.equal(distanceWarning(98.4), "Outside 50 mi");
  assert.equal(distanceWarning(50), null);
  assert.equal(distanceWarning(0.4), null);
});

test("a trial with no site coordinates gets no distance warning", () => {
  assert.equal(distanceWarning(null), null);
});

function verdicts(...outcomes: Schemas["Verdict"]["outcome"][]): Schemas["Verdict"][] {
  return outcomes.map((outcome, i) => ({
    criterion_id: `c${i + 1}`,
    outcome,
    method: "rule",
    criterion_quote: "q",
    patient_evidence: null,
    rationale: "r",
    verified: true,
    trace_event_id: `e${i + 1}`,
  }));
}

const ids = (vs: Schemas["Verdict"][]) => vs.map((v) => v.criterion_id);

test("the short criterion list leads with what decides the tier, in the trial's order", () => {
  const vs = verdicts("pass", "unknown", "pass", "fail", "pass");
  assert.deepEqual(ids(shortCriteria(vs, null, 3)), ["c1", "c2", "c4"]);
});

test("the short criterion list always includes the highlighted verdict", () => {
  const vs = verdicts("pass", "unknown", "pass", "fail", "pass");
  assert.deepEqual(ids(shortCriteria(vs, "e5", 3)), ["c2", "c4", "c5"]);
});

test("a trial with no more criteria than the limit shows them all", () => {
  const vs = verdicts("pass", "pass");
  assert.deepEqual(ids(shortCriteria(vs, null, 3)), ["c1", "c2"]);
});

test("a run page opens on the Results tab with nothing to reveal", () => {
  assert.deepEqual(INITIAL_RUN_TABS, { tab: "results", reveal: null });
});

test("Why? on a verdict switches to the Trace tab", () => {
  const next = runTabsReducer(INITIAL_RUN_TABS, { type: "why" });
  assert.equal(next.tab, "trace");
});

test("View verdict switches back to Results and asks to reveal that verdict, every time", () => {
  const onTrace = { tab: "trace" as const, reveal: null };
  const first = runTabsReducer(onTrace, { type: "view-verdict", eventId: "judge" });
  assert.equal(first.tab, "results");
  assert.equal(first.reveal?.eventId, "judge");
  const again = runTabsReducer({ ...first, tab: "trace" }, { type: "view-verdict", eventId: "judge" });
  assert.equal(again.reveal?.eventId, "judge");
  assert.notEqual(again.reveal?.nonce, first.reveal?.nonce);
});

test("a reveal is done once the verdict has been shown, and the next one still lands", () => {
  const asked = runTabsReducer(INITIAL_RUN_TABS, { type: "view-verdict", eventId: "judge" });
  const done = runTabsReducer(asked, { type: "revealed" });
  assert.deepEqual(done, { tab: "results", reveal: null });
  const again = runTabsReducer(done, { type: "view-verdict", eventId: "judge" });
  assert.equal(again.reveal?.eventId, "judge");
});

test("picking a tab shows it and keeps the last reveal", () => {
  const state = runTabsReducer(INITIAL_RUN_TABS, { type: "view-verdict", eventId: "judge" });
  const next = runTabsReducer(state, { type: "show", tab: "trace" });
  assert.deepEqual(next, { tab: "trace", reveal: state.reveal });
});

test("the trace tab counts every event of the run", () => {
  assert.equal(traceTabLabel(41), "Trace · 41");
  assert.equal(traceTabLabel(0), "Trace · 0");
});
