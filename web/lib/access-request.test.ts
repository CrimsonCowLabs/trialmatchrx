// Unit tests for the request-access form helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { ACCESS_REQUEST_SENT, ACCESS_ROLES, EMPTY_ACCESS_REQUEST } from "./access-request.ts";

test("the four roles the spec names, in its order", () => {
  assert.deepEqual(
    ACCESS_ROLES.map((r) => r.value),
    ["sponsor", "cro", "site", "other"],
  );
});

test("the success message is the spec's wording", () => {
  assert.equal(ACCESS_REQUEST_SENT, "Thanks, we'll be in touch.");
});

test("a fresh form has no role chosen and an empty honeypot", () => {
  assert.equal(EMPTY_ACCESS_REQUEST.role, "");
  assert.equal(EMPTY_ACCESS_REQUEST.website, "");
});
