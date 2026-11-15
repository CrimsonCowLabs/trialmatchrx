// Unit tests for lab / vital labels. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { measureLabel } from "./measures.ts";

test("known lab keys read as their clinical names", () => {
  assert.equal(measureLabel("hba1c"), "HbA1c");
  assert.equal(measureLabel("fvc_pct"), "FVC (% pred)");
  assert.equal(measureLabel("fev1_pct"), "FEV1 (% pred)");
  assert.equal(measureLabel("fev1_fvc"), "FEV1/FVC");
  assert.equal(measureLabel("svc_pct"), "SVC (% pred)");
  assert.equal(measureLabel("dlco_pct"), "DLCO (% pred)");
  assert.equal(measureLabel("alsfrs_r"), "ALSFRS-R");
  assert.equal(measureLabel("six_mwd"), "6-minute walk");
  assert.equal(measureLabel("pvr"), "PVR");
  assert.equal(measureLabel("pcwp"), "PCWP");
});

test("an unknown key falls back to a readable form of itself", () => {
  assert.equal(measureLabel("nt_probnp"), "Nt probnp");
  assert.equal(measureLabel("tlc_pct"), "Tlc (% pred)");
  assert.equal(measureLabel("ferritin"), "Ferritin");
});
