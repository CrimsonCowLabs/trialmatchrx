// Unit tests for the reset-password form helper. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { resetFormProblem } from "./reset.ts";

test("nothing to say until both fields are filled", () => {
  assert.equal(resetFormProblem("", ""), null);
  assert.equal(resetFormProblem("a long enough passphrase", ""), null);
});

test("the two fields must match", () => {
  assert.equal(
    resetFormProblem("a long enough passphrase", "a long enough passphrasf"),
    "The passwords don't match.",
  );
});

test("matching passwords are left to the API's rules", () => {
  // Length and the common-password list are checked by the API, the one place the rules live.
  assert.equal(resetFormProblem("short", "short"), null);
  assert.equal(resetFormProblem("a long enough passphrase", "a long enough passphrase"), null);
});
