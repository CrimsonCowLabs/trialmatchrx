// Unit tests for the new-password form helper. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { confirmPasswordProblem } from "./password.ts";

test("nothing to say until both fields are filled", () => {
  assert.equal(confirmPasswordProblem("", ""), null);
  assert.equal(confirmPasswordProblem("a long enough passphrase", ""), null);
});

test("the two fields must match", () => {
  assert.equal(
    confirmPasswordProblem("a long enough passphrase", "a long enough passphrasf"),
    "The passwords don't match.",
  );
});

test("matching passwords are left to the API's rules", () => {
  // Length and the common-password list are checked by the API, the one place the rules live.
  assert.equal(confirmPasswordProblem("short", "short"), null);
  assert.equal(confirmPasswordProblem("a long enough passphrase", "a long enough passphrase"), null);
});
