// Unit tests for the invite page's helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { inviteProblem } from "./invite.ts";

test("a refused link shows the API's message and offers sign-in", () => {
  for (const status of [404, 409, 410]) {
    assert.deepEqual(inviteProblem({ status, detail: "This invite link has expired." }), {
      kind: "link",
      message: "This invite link has expired.",
    });
  }
});

test("a password that breaks the rules stays on the form with the rule", () => {
  assert.deepEqual(inviteProblem({ status: 422, detail: "Use at least 12 characters." }), {
    kind: "password",
    message: "Use at least 12 characters.",
  });
});

test("anything else is a connection problem, not a dead link", () => {
  const offline = { kind: "retry", message: "Couldn't reach the server. Try again." };
  assert.deepEqual(inviteProblem(new TypeError("fetch failed")), offline);
  assert.deepEqual(inviteProblem({ status: 500, detail: null }), offline);
  assert.deepEqual(inviteProblem({ status: 410, detail: null }), offline);
});
