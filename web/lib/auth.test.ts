// Unit tests for the sign-in helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { loginHref, safeNextPath } from "./auth.ts";

test("no next goes to the app's Home", () => {
  assert.equal(safeNextPath(null), "/app");
  assert.equal(safeNextPath(undefined), "/app");
  assert.equal(safeNextPath(""), "/app");
});

test("a path on this site is kept, query and hash included", () => {
  assert.equal(safeNextPath("/match/run-123"), "/match/run-123");
  assert.equal(safeNextPath("/trials?q=ckd#top"), "/trials?q=ckd#top");
  assert.equal(safeNextPath("/"), "/");
});

test("anything that could leave the site goes to Home instead", () => {
  for (const next of [
    "https://evil.example/",
    "http:/evil.example",
    "//evil.example/path",
    "/\\evil.example",
    "\\\\evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    " //evil.example",
    "javascript:alert(1)",
    "data:text/html,hi",
    "match/run-123",
    // Dot segments that normalize into a protocol-relative `//host`.
    "/.//evil.example",
    "/x/..//evil.example",
    "/%2e//evil.example",
    "/./%2e/..//evil.example/x",
  ]) {
    assert.equal(safeNextPath(next), "/app", next);
  }
});

test("an encoded slash stays a path on this site", () => {
  assert.equal(safeNextPath("/%2F%2Fevil.example"), "/%2F%2Fevil.example");
});

test("next never points back at the login page", () => {
  assert.equal(safeNextPath("/login"), "/app");
  assert.equal(safeNextPath("/login?next=/runs"), "/app");
});

test("the sign-in link remembers where you were", () => {
  assert.equal(loginHref("/match/run-1"), "/login?next=%2Fmatch%2Frun-1");
  assert.equal(loginHref("/app"), "/login");
  assert.equal(loginHref(null), "/login");
});
