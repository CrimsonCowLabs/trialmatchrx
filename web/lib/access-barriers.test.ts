// Unit tests for the access barrier helpers (issue #53). Run with `pnpm test`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { barrierCount, barrierCountLabel, barrierTag } from "./access-barriers.ts";

test("a trial's barrier count counts flagged criteria, not categories", () => {
  const verdicts = [
    { access_barrier: "language" as const },
    { access_barrier: null },
    {},
    { access_barrier: "language" as const },
    { access_barrier: "technology" as const },
  ];
  assert.equal(barrierCount(verdicts), 3);
  assert.equal(barrierCount([]), 0);
});

test("the count reads '2 access barriers', '1 access barrier', and nothing at zero", () => {
  assert.equal(barrierCountLabel(2), "2 access barriers");
  assert.equal(barrierCountLabel(1), "1 access barrier");
  assert.equal(barrierCountLabel(0), null);
});

test("each barrier has a short tag and a sentence saying who it shuts out", () => {
  assert.deepEqual(barrierTag("language"), {
    label: "Language",
    title: "Access barrier: shuts out people who don't read or speak English",
  });
  assert.equal(barrierTag("visit_burden").label, "Visit burden");
  assert.equal(barrierTag("technology").label, "Technology");
  assert.equal(barrierTag("support").label, "Support");
  for (const b of ["visit_burden", "technology", "support"] as const) {
    assert.match(barrierTag(b).title, /^Access barrier: shuts out people who /);
  }
});
