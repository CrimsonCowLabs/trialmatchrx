// Unit tests for the admin page's rules. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  firstName,
  grantOutcome,
  isNotFound,
  NOT_FOUND,
  notePrefill,
  pendingNote,
  rowActions,
  stateBadge,
  visibleRequests,
} from "./admin.ts";

const date = (iso: string) => iso.slice(0, 10);

test("the page reads Not found, nothing about admin, when the API answers 404", () => {
  assert.equal(isNotFound(404), true);
  assert.equal(isNotFound(500), false);
  assert.equal(isNotFound(null), false);
  assert.equal(NOT_FOUND, "Not found");
  assert.doesNotMatch(NOT_FOUND, /admin/i);
});

test("the note starts with Hi and the first word of the name", () => {
  assert.equal(notePrefill("Ada Lovelace"), "Hi Ada,");
  assert.equal(notePrefill("  Grace   Brewster Hopper "), "Hi Grace,");
  assert.equal(notePrefill("Cher"), "Hi Cher,");
  assert.equal(notePrefill("Dr.\tJane Roe"), "Hi Dr.,");
  assert.equal(notePrefill("   "), "Hi,");
  assert.equal(firstName("Ada Lovelace"), "Ada");
});

test("a sent invite says where it went, with no link", () => {
  assert.deepEqual(grantOutcome("ada@example.com", { email_status: "sent" }), {
    tone: "ok",
    text: "Invite emailed to ada@example.com",
    link: null,
  });
});

test("a logged invite (email not configured) gives the link to copy", () => {
  assert.deepEqual(
    grantOutcome("ada@example.com", { email_status: "logged", link: "http://x/invite/t" }),
    { tone: "warn", text: "Email isn't configured — copy this link:", link: "http://x/invite/t" },
  );
});

test("a failed send shows the error and the link to copy", () => {
  assert.deepEqual(
    grantOutcome("ada@example.com", {
      email_status: "failed",
      error: "Couldn't send: 500",
      link: "http://x/invite/t",
    }),
    { tone: "error", text: "Couldn't send: 500", link: "http://x/invite/t" },
  );
  assert.match(
    grantOutcome("a@b.c", { email_status: "failed", error: null, link: "l" }).text,
    /Couldn't send/,
  );
});

const row = {
  state: "pending" as const,
  has_account: false,
  has_open_invite: false,
  invite_expires_at: null,
  joined_at: null,
};

test("each state has its badge, with the invite's expiry and the join date", () => {
  assert.deepEqual(stateBadge(row, date), { label: "Pending", tone: "pending" });
  assert.equal(stateBadge({ ...row, state: "dismissed" }, date).label, "Dismissed");
  assert.equal(
    stateBadge({ ...row, state: "invited", invite_expires_at: "2026-11-23T10:00:00Z" }, date).label,
    "Invited (expires 2026-11-23)",
  );
  assert.equal(stateBadge({ ...row, state: "invite_expired" }, date).label, "Invite expired");
  assert.equal(
    stateBadge({ ...row, state: "joined", joined_at: "2026-11-17T09:00:00Z" }, date).label,
    "Joined 2026-11-17",
  );
});

test("a pending request notes an existing account or an open invite", () => {
  assert.equal(pendingNote(row), null);
  assert.equal(pendingNote({ ...row, has_account: true }), "already has an account");
  assert.equal(pendingNote({ ...row, has_open_invite: true }), "invite already sent");
  assert.equal(pendingNote({ ...row, state: "invited", has_open_invite: true }), null);
});

test("actions: grant + dismiss while pending, resend once invited, none after", () => {
  assert.equal(rowActions({ state: "pending" }), "grant");
  assert.equal(rowActions({ state: "invited" }), "resend");
  assert.equal(rowActions({ state: "invite_expired" }), "resend");
  assert.equal(rowActions({ state: "joined" }), "none");
  assert.equal(rowActions({ state: "dismissed" }), "none");
});

test("Pending only hides the handled requests; All keeps the API's order", () => {
  const rows = [{ state: "pending" as const }, { state: "joined" as const }, { state: "pending" as const }];
  assert.equal(visibleRequests(rows, true).length, 2);
  assert.deepEqual(visibleRequests(rows, false), rows);
});
