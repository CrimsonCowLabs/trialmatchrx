// Unit tests for the demo patients. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { DEMO_PATIENTS, DEMO_RADIUS_MI, demoMatchRequest, demoPatientForNote } from "./demo.ts";

test("the demo lists ALS, IPF, PAH and T2D/CKD, with stable ids", () => {
  assert.deepEqual(
    DEMO_PATIENTS.map((p) => p.id),
    ["als", "ipf", "pah", "t2d"],
  );
});

test("every demo patient has a name, a one-line summary and a note naming a place", () => {
  for (const p of DEMO_PATIENTS) {
    assert.ok(p.name && p.summary && p.condition && p.searchCondition, p.id);
    assert.match(p.note, /Lives in /, p.id);
    assert.ok(p.note.startsWith(`${p.age}-year-old`), p.id);
  }
});

test("a demo request sends the exact note, the search condition and the seeded radius", () => {
  const t2d = DEMO_PATIENTS.find((p) => p.id === "t2d")!;
  assert.deepEqual(demoMatchRequest(t2d), {
    note: "61-year-old man with type 2 diabetes, HbA1c 8.4%, eGFR 48, on metformin. Lives in Sacramento.",
    condition: "type 2 diabetes",
    radius_mi: 100,
  });
  assert.equal(DEMO_RADIUS_MI, 100);
});

test("a note matches its demo patient only until it is edited", () => {
  const [als] = DEMO_PATIENTS;
  assert.equal(demoPatientForNote(als.note)?.id, "als");
  assert.equal(demoPatientForNote(`${als.note} Edited.`), null);
});
