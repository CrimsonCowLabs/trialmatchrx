// Unit tests for the Patient facts panel helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { Schemas, TraceEvent } from "./api.ts";
import { factsSummary, parseProvenance, patientFactRows, type FactRow } from "./patient-facts.ts";

type PatientFacts = Schemas["PatientFacts"];

function patient(over: Partial<PatientFacts> = {}): PatientFacts {
  return {
    age: null,
    sex: null,
    conditions: [],
    labs: {},
    vitals: {},
    meds: [],
    pregnant: null,
    smoker: null,
    lat: null,
    lon: null,
    place: null,
    ...over,
  };
}

const quoted = { source: "quoted" as const, scalarQuotes: {}, unverified: [] };

const pick = (rows: FactRow[], label: string) => {
  const row = rows.find((r) => r.label === label);
  assert.ok(row, `no row labelled ${label}`);
  return row;
};

test("a parsed condition shows its quote as verified", () => {
  const rows = patientFactRows(
    patient({ conditions: [{ value: "type 2 diabetes", source_span: "T2DM since 2015" }] }),
    quoted,
  );
  assert.deepEqual(rows, [
    {
      key: "conditions[0]",
      group: "Conditions",
      label: "Condition",
      value: "type 2 diabetes",
      date: null,
      quote: { kind: "verified", text: "T2DM since 2015" },
    },
  ]);
});

test("the demo patient reads as rows in panel order, scalars quoted from the parse step", () => {
  const rows = patientFactRows(
    patient({
      age: 61,
      sex: "male",
      smoker: false,
      place: "Sacramento, CA",
      lat: 38.58,
      lon: -121.49,
      conditions: [{ value: "type 2 diabetes", source_span: "type 2 diabetes" }],
      labs: {
        hba1c: { value: 8.4, unit: "%", date: "2026-09-02", source_span: "HbA1c 8.4% (9/2)" },
        egfr: { value: 48, unit: "mL/min/1.73m2", source_span: "eGFR 48" },
      },
      vitals: { sbp: { value: 142, unit: "mmHg", source_span: "BP 142/88" } },
      meds: [{ value: "metformin", source_span: "metformin 1000 mg BID" }],
    }),
    {
      source: "quoted",
      scalarQuotes: { age: "61-year-old", sex: "man", location: "lives in Sacramento" },
      unverified: [],
    },
  );
  assert.deepEqual(
    rows.map((r) => [r.group, r.label, r.value, r.date, r.quote.kind]),
    [
      ["Patient", "Age", "61", null, "verified"],
      ["Patient", "Sex", "male", null, "verified"],
      ["Patient", "Smoker", "no", null, "none"],
      ["Patient", "Lives in", "Sacramento, CA", null, "verified"],
      ["Conditions", "Condition", "type 2 diabetes", null, "verified"],
      ["Labs", "HbA1c", "8.4%", "2026-09-02", "verified"],
      ["Labs", "eGFR", "48 mL/min/1.73m2", null, "verified"],
      ["Vitals", "Systolic BP", "142 mmHg", null, "verified"],
      ["Medications", "Medication", "metformin", null, "verified"],
    ],
  );
  assert.deepEqual(pick(rows, "Lives in").quote, {
    kind: "verified",
    text: "lives in Sacramento",
  });
});

test("a fact whose quote failed verification is listed in its group, marked unverified", () => {
  const rows = patientFactRows(
    patient({ conditions: [{ value: "hypertension", source_span: "HTN" }] }),
    {
      source: "quoted",
      scalarQuotes: {},
      unverified: [
        { path: "conditions[1]", fact: { value: "heart failure", source_span: "CHF" } },
        {
          path: "labs.egfr",
          fact: { name: "egfr", value: 48, unit: "mL/min/1.73m2", date: null, source_span: "GFR 48" },
        },
        { path: "age", fact: { value: 62, source_span: "62 yo" } },
        {
          path: "location",
          fact: { place: "Davis, CA", lat: 38.5, lon: -121.7, source_span: "in Davis" },
        },
      ],
    },
  );
  assert.deepEqual(
    rows.map((r) => [r.key, r.group, r.label, r.value, r.quote]),
    [
      ["unverified-2:age", "Patient", "Age", "62", { kind: "unverified", text: "62 yo" }],
      ["unverified-3:location", "Patient", "Lives in", "Davis, CA", { kind: "unverified", text: "in Davis" }],
      ["conditions[0]", "Conditions", "Condition", "hypertension", { kind: "verified", text: "HTN" }],
      ["unverified-0:conditions[1]", "Conditions", "Condition", "heart failure", { kind: "unverified", text: "CHF" }],
      ["unverified-1:labs.egfr", "Labs", "eGFR", "48 mL/min/1.73m2", { kind: "unverified", text: "GFR 48" }],
    ],
  );
});

test("a location without a place name (older runs) shows its coordinates", () => {
  const rows = patientFactRows(patient({ lat: 38.5816, lon: -121.4944 }), {
    source: "quoted",
    scalarQuotes: { location: "Lives in Sacramento, CA" },
    unverified: [],
  });
  assert.deepEqual(pick(rows, "Lives in"), {
    key: "place",
    group: "Patient",
    label: "Lives in",
    value: "38.58, -121.49",
    date: null,
    quote: { kind: "verified", text: "Lives in Sacramento, CA" },
  });
});

test("unverified facts read like kept ones: names normalised, coordinates for a nameless place, unique keys", () => {
  const rows = patientFactRows(patient(), {
    source: "quoted",
    scalarQuotes: {},
    unverified: [
      { path: "conditions[0]", fact: { value: " Heart Failure ", source_span: "CHF" } },
      { path: "location", fact: { place: null, lat: 38.5, lon: -121.7, source_span: "near Davis" } },
      { path: "labs.egfr", fact: { value: 52, unit: "mL/min/1.73m2", source_span: "GFR 52" } },
      { path: "labs.egfr", fact: { value: 48, unit: "mL/min/1.73m2", source_span: "GFR 48" } },
    ],
  });
  assert.deepEqual(pick(rows, "Condition").value, "heart failure");
  assert.deepEqual(pick(rows, "Lives in").value, "38.50, -121.70");
  assert.equal(new Set(rows.map((r) => r.key)).size, rows.length);
});

test("facts from a FHIR record say so instead of quoting", () => {
  const rows = patientFactRows(
    patient({ conditions: [{ value: "type 2 diabetes" }], meds: [{ value: "metformin" }] }),
    { source: "record", scalarQuotes: {}, unverified: [] },
  );
  assert.deepEqual(
    rows.map((r) => r.quote),
    [{ kind: "record" }, { kind: "record" }],
  );
});

test("a quoted-input fact with no quote is shown as unquoted, never verified", () => {
  const rows = patientFactRows(patient({ meds: [{ value: "metformin" }] }), quoted);
  assert.deepEqual(pick(rows, "Medication").quote, { kind: "none" });
});

test("without the parse step (trace not loaded) quotes still show, but unquoted facts are not verified", () => {
  const rows = patientFactRows(
    patient({ age: 61, meds: [{ value: "metformin", source_span: "on metformin" }] }),
    null,
  );
  assert.deepEqual(pick(rows, "Age").quote, { kind: "none" });
  assert.deepEqual(pick(rows, "Medication").quote, { kind: "verified", text: "on metformin" });
});

test("the panel heading counts the facts used and the ones dropped as unverified", () => {
  const row = (kind: FactRow["quote"]["kind"]): FactRow => ({
    key: kind,
    group: "Patient",
    label: "Age",
    value: "61",
    date: null,
    quote: kind === "verified" || kind === "unverified" ? { kind, text: "61" } : { kind },
  });
  assert.equal(factsSummary([]), "No facts extracted");
  assert.equal(factsSummary([row("verified")]), "1 fact");
  assert.equal(
    factsSummary([row("verified"), row("none"), row("unverified")]),
    "2 facts · 1 unverified, not used",
  );
  assert.equal(factsSummary([row("record"), row("record")]), "2 facts from the record");
});

const at = "2026-11-14T12:00:00Z";

function ev(over: Partial<TraceEvent> & Pick<TraceEvent, "id" | "seq">): TraceEvent {
  return {
    run_id: "r1",
    parent_id: null,
    kind: "step",
    name: over.id,
    status: "ok",
    started_at: at,
    ended_at: at,
    input: null,
    output: null,
    model: null,
    tokens_in: null,
    tokens_out: null,
    cost_usd: null,
    cache_hit: false,
    note: null,
    ...over,
  };
}

const dropEvent = (id: string, seq: number, check: string, path: string, parent = "p") =>
  ev({
    id,
    seq,
    parent_id: parent,
    kind: "guardrail",
    status: "failed",
    name: `${check}:${path}`,
    input: { path, fact: { value: "x", source_span: `quote of ${path}` } },
  });

test("a note run's parse step gives the scalar quotes and the facts whose quote failed", () => {
  const events = [
    ev({ id: "run", seq: 1, kind: "run", name: "match" }),
    ev({
      id: "p",
      seq: 2,
      parent_id: "run",
      name: "parse_patient",
      input: { note_chars: 300, prompt: "parse_patient", prompt_version: "3" },
      output: { facts: 8, scalar_spans: { age: "61-year-old", sex: "man" } },
    }),
    dropEvent("g1", 3, "span", "conditions[1]"),
    dropEvent("g2", 4, "unit", "labs.ldl"), // dropped for its unit, not its quote
    dropEvent("g3", 5, "span", "meds[0]", "judge-step"), // some other step's guardrail
  ];
  assert.deepEqual(parseProvenance(events), {
    source: "quoted",
    scalarQuotes: { age: "61-year-old", sex: "man" },
    unverified: [
      { path: "conditions[1]", fact: { value: "x", source_span: "quote of conditions[1]" } },
    ],
  });
});

test("a FHIR bundle run's parse step reads as from the record", () => {
  const events = [
    ev({
      id: "p",
      seq: 1,
      name: "parse_patient",
      input: { source: "fhir_bundle", resources: { Patient: 1 } },
      output: { patient: {}, missing: [], dropped: [] },
    }),
  ];
  assert.deepEqual(parseProvenance(events), { source: "record", scalarQuotes: {}, unverified: [] });
});

test("no parse step yet means no provenance; a still-running one has no scalar quotes", () => {
  assert.equal(parseProvenance([ev({ id: "run", seq: 1, kind: "run" })]), null);
  const running = ev({
    id: "p",
    seq: 1,
    name: "parse_patient",
    status: "started",
    ended_at: null,
    input: { note_chars: 300 },
  });
  assert.deepEqual(parseProvenance([running]), {
    source: "quoted",
    scalarQuotes: {},
    unverified: [],
  });
});
