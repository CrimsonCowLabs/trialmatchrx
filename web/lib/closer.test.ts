// Unit tests for the closer page helpers. Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import { closerTitle, emailDraft, emailText, followupItems, mailtoHref, traceShown } from "./closer.ts";

test("the title names the match run's patient when the API gives one", () => {
  assert.equal(closerTitle({ patient_label: "61 M" }), "Next steps for a 61 M patient");
  assert.equal(closerTitle({ patient_label: null }), "Next steps");
  assert.equal(closerTitle(null), "Next steps");
});

test("the trace shows while the agent works and folds away for its answer, unless toggled", () => {
  assert.equal(traceShown(null, false), true); // running: the trace is all there is to watch
  assert.equal(traceShown(null, true), false); // answered: the answer gets the width
  assert.equal(traceShown(true, true), true); // Show trace
  assert.equal(traceShown(false, false), false); // Hide trace
});

test("follow-ups keep the agent's order, tagged Test or Ask with criterion id and why", () => {
  const items = followupItems([
    { criterion_id: "inc-7", kind: "test", action: "Order a UACR.", why: "No UACR on file." },
    { criterion_id: "exc-2", kind: "question", action: "Ask about dialysis.", why: "Unstated." },
  ]);
  assert.deepEqual(items, [
    { criterionId: "inc-7", tag: "Test", action: "Order a UACR.", why: "No UACR on file." },
    { criterionId: "exc-2", tag: "Ask", action: "Ask about dialysis.", why: "Unstated." },
  ]);
});

test("mailto carries the recipient, subject and body, percent-encoded", () => {
  const href = mailtoHref({
    to: "recruit@north-valley.org",
    subject: "Referral: NCT07271186 (61 M, eGFR 48) & more?",
    body: "Hello,\n\nHbA1c 8.4% + eGFR 48.\nThanks",
  });
  assert.equal(
    href,
    "mailto:recruit@north-valley.org" +
      "?subject=Referral%3A%20NCT07271186%20(61%20M%2C%20eGFR%2048)%20%26%20more%3F" +
      "&body=Hello%2C%0D%0A%0D%0AHbA1c%208.4%25%20%2B%20eGFR%2048.%0D%0AThanks",
  );
});

test("with no recipient, mailto opens a draft without one", () => {
  assert.equal(mailtoHref({ to: "  ", subject: "Hi", body: "B" }), "mailto:?subject=Hi&body=B");
});

test("Copy gives To, Subject and the body; no To line without a recipient", () => {
  assert.equal(
    emailText({ to: "a@b.org", subject: "S", body: "Hello,\n\nThanks" }),
    "To: a@b.org\nSubject: S\n\nHello,\n\nThanks",
  );
  assert.equal(emailText({ to: " ", subject: "S", body: "B" }), "Subject: S\n\nB");
});

test("the draft starts as the agent's email; no contact address leaves To empty", () => {
  assert.deepEqual(emailDraft({ to: null, subject: "S", body: "B" }), {
    to: "",
    subject: "S",
    body: "B",
  });
  assert.equal(emailDraft({ to: "a@b.org", subject: "S", body: "B" }).to, "a@b.org");
});
