// Unit tests for the request-access form helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { ACCESS_REQUEST_SENT, ACCESS_ROLES, toAccessRequest } from "./access-request.ts";

test("the four roles the spec names, in its order", () => {
  assert.deepEqual(
    ACCESS_ROLES.map((r) => r.value),
    ["sponsor", "cro", "site", "other"],
  );
});

test("the success message is the spec's wording", () => {
  assert.equal(ACCESS_REQUEST_SENT, "Thanks, we'll be in touch.");
});

test("the body trims fields and sends a blank message as null", () => {
  assert.deepEqual(
    toAccessRequest({
      name: "  Ana Silva ",
      email: " ana@acme.example ",
      organization: "Acme Pharma",
      role: "cro",
      message: "   ",
      website: "",
    }),
    {
      name: "Ana Silva",
      email: "ana@acme.example",
      organization: "Acme Pharma",
      role: "cro",
      message: null,
      website: "",
    },
  );
});

test("the honeypot is passed through, so the API can drop the send", () => {
  const body = toAccessRequest({
    name: "Bot",
    email: "bot@spam.example",
    organization: "Spam",
    role: "other",
    message: "Buy now",
    website: "https://spam.example",
  });
  assert.equal(body.website, "https://spam.example");
  assert.equal(body.message, "Buy now");
});
