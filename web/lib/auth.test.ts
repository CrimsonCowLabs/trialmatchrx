// Unit tests for the sign-in helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { loginHref, needsSignIn, safeNextPath, signInRedirect } from "./auth.ts";

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

test("a signed-out visitor to an app page is sent to sign in, then back", () => {
  assert.equal(signInRedirect("/match/run-1", "", false), "/login?next=%2Fmatch%2Frun-1");
  assert.equal(signInRedirect("/trials", "?q=ckd", false), "/login?next=%2Ftrials%3Fq%3Dckd");
  assert.equal(signInRedirect("/app", "", false), "/login");
  assert.equal(signInRedirect("/app/account", "", false), "/login?next=%2Fapp%2Faccount");
  for (const page of ["/runs", "/eval", "/feasibility/NCT1", "/closer/run-2", "/match"]) {
    assert.ok(signInRedirect(page, "", false)?.startsWith("/login?next="), page);
  }
});

test("a visitor with a session cookie, or on a public page, is let through", () => {
  assert.equal(signInRedirect("/match/run-1", "", true), null);
  const publicPages = ["/", "/login", "/invite/tok", "/reset/tok", "/apple", "/_next/x", "/brand/a.svg"];
  for (const page of publicPages) {
    assert.equal(signInRedirect(page, "", false), null, page);
  }
});

test("a 401 from a gated API route means sign in; the auth routes' own 401s don't", () => {
  assert.equal(needsSignIn(401, "/api/runs"), true);
  assert.equal(needsSignIn(401, "/api/match"), true);
  assert.equal(needsSignIn(401, "/api/auth/me"), false);
  assert.equal(needsSignIn(401, "/api/auth/login"), false);
  assert.equal(needsSignIn(403, "/api/runs"), false);
  assert.equal(needsSignIn(404, "/api/runs/x"), false);
});
