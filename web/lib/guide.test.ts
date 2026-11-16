// Unit tests for the first-time user guide: link resolution from pins, and the stored state.
// Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { GuidePin } from "./api.ts";
import {
  GUIDE_EVENT,
  GUIDE_STORAGE_KEY,
  GUIDE_STEPS,
  applyGuideAction,
  guideLinks,
  isGuideOpen,
  markGuideStep,
  readGuideState,
  resetGuide,
  setGuideOpen,
  type GuideAction,
  type GuideStorage,
} from "./guide.ts";

const pin = (p: Partial<GuidePin> & Pick<GuidePin, "step">): GuidePin => ({
  run_id: null,
  nct_id: null,
  run_exists: false,
  ...p,
});

const IPF = pin({ step: "ipf", run_id: "run-ipf", nct_id: "NCT05571059", run_exists: true });
const FLIP = pin({ step: "ipf_flip", run_id: "run-flip", nct_id: "NCT05571059", run_exists: true });

test("the five steps, in pitch order", () => {
  assert.deepEqual(
    GUIDE_STEPS.map((s) => s.id),
    ["als", "ipf", "ipf_flip", "pah", "feasibility"],
  );
});

test("no pins: every step falls back to running a card, feasibility to Trials", () => {
  const links = guideLinks([]);
  assert.deepEqual(links.als, { links: [{ label: "Go to Home", href: "/" }], fallback: null });
  assert.deepEqual(links.ipf, {
    links: [{ label: "Go to Home", href: "/" }],
    fallback: "Find trials for Richard Hale (IPF) on Home, then open ifetroban.",
  });
  assert.deepEqual(links.ipf_flip, {
    links: [{ label: "Go to Match", href: "/match" }],
    fallback:
      "On Match, pick Richard Hale (IPF) and click Find trials, then change FEV1/FVC 0.66 to 0.75 in the note and run it again.",
  });
  assert.deepEqual(links.pah, {
    links: [{ label: "Go to Home", href: "/" }],
    fallback: "Find trials for Lucía Ramírez (PAH) on Home, open the top trial and click Next steps.",
  });
  assert.deepEqual(links.feasibility, {
    links: [
      { label: "Trials", href: "/trials" },
      { label: "Eval", href: "/eval" },
    ],
    fallback: null,
  });
});

test("pinned runs that exist: each step links its run, with the trial deep link", () => {
  const links = guideLinks([
    pin({ step: "als", run_id: "run-als", nct_id: "NCT01", run_exists: true }),
    IPF,
    FLIP,
    pin({ step: "pah", run_id: "run pah", run_exists: true }),
    pin({ step: "feasibility", nct_id: "NCT04" }),
  ]);
  assert.deepEqual(links.als.links, [
    { label: "Go to Home", href: "/" },
    { label: "See a finished run", href: "/match/run-als?trial=NCT01" },
  ]);
  assert.deepEqual(links.ipf, {
    links: [{ label: "Open", href: "/match/run-ipf?trial=NCT05571059" }],
    fallback: null,
  });
  assert.deepEqual(links.ipf_flip, {
    links: [
      { label: "Before", href: "/match/run-ipf?trial=NCT05571059" },
      { label: "After", href: "/match/run-flip?trial=NCT05571059" },
    ],
    fallback: null,
  });
  assert.deepEqual(links.pah, {
    links: [{ label: "Open", href: "/closer/run%20pah" }],
    fallback: null,
  });
  assert.deepEqual(links.feasibility.links, [
    { label: "Feasibility", href: "/feasibility/NCT04" },
    { label: "Eval", href: "/eval" },
  ]);
});

test("a pinned ALS run without a trial links the run alone", () => {
  const links = guideLinks([pin({ step: "als", run_id: "run-als", run_exists: true })]);
  assert.equal(links.als.links[1].href, "/match/run-als");
});

test("pinned runs that are gone fall back as if unpinned", () => {
  const gone = guideLinks(
    (["als", "ipf", "ipf_flip", "pah"] as const).map((step) =>
      pin({ step, run_id: `run-${step}`, nct_id: "NCT05571059", run_exists: false }),
    ),
  );
  const none = guideLinks([]);
  assert.deepEqual(gone.als, none.als);
  assert.deepEqual(gone.ipf, none.ipf);
  assert.deepEqual(gone.ipf_flip, none.ipf_flip);
  assert.deepEqual(gone.pah, none.pah);
});

test("the flip falls back when only one side is available", () => {
  const none = guideLinks([]).ipf_flip;
  assert.deepEqual(guideLinks([IPF]).ipf_flip, none);
  assert.deepEqual(guideLinks([FLIP]).ipf_flip, none);
  assert.deepEqual(guideLinks([IPF, { ...FLIP, run_exists: false }]).ipf_flip, none);
  assert.deepEqual(guideLinks([{ ...IPF, run_exists: false }, FLIP]).ipf_flip, none);
});

test("a run pinned without a trial still links the run, just without the deep link", () => {
  const links = guideLinks([
    { ...IPF, nct_id: null },
    { ...FLIP, nct_id: null },
  ]);
  assert.deepEqual(links.ipf.links, [{ label: "Open", href: "/match/run-ipf" }]);
  assert.deepEqual(links.ipf_flip.links, [
    { label: "Before", href: "/match/run-ipf" },
    { label: "After", href: "/match/run-flip" },
  ]);
});

// --- Stored state ---

function memoryStorage(
  initial: Record<string, string> = {},
): GuideStorage & { data: Record<string, string> } {
  const data = { ...initial };
  return {
    data,
    getItem: (k) => data[k] ?? null,
    setItem: (k, v) => {
      data[k] = v;
    },
  };
}

const throwing: GuideStorage = {
  getItem: () => {
    throw new Error("SecurityError");
  },
  setItem: () => {
    throw new Error("QuotaExceededError");
  },
};

/** An event target that records every guide action dispatched on it. */
function recorder(): { target: EventTarget; actions: GuideAction[] } {
  const target = new EventTarget();
  const actions: GuideAction[] = [];
  target.addEventListener(GUIDE_EVENT, (e) =>
    actions.push((e as CustomEvent<GuideAction>).detail),
  );
  return { target, actions };
}

test("first visit: nothing checked, open on a wide screen, collapsed on a narrow one", () => {
  const state = readGuideState(memoryStorage());
  assert.deepEqual(state.visited, []);
  assert.equal(isGuideOpen(state, { narrow: false }), true);
  assert.equal(isGuideOpen(state, { narrow: true }), false);
});

test("no storage at all gives the first-visit state", () => {
  assert.deepEqual(readGuideState(null), readGuideState(memoryStorage()));
});

test("storage that throws on read gives the first-visit state", () => {
  assert.deepEqual(readGuideState(throwing), readGuideState(memoryStorage()));
});

test("corrupt JSON, a wrong version or a wrong shape gives the first-visit state", () => {
  const fresh = readGuideState(memoryStorage());
  for (const raw of [
    "{not json",
    "null",
    "[]",
    '{"v":99,"open":false,"visited":["als"]}',
    '{"v":1,"visited":"als"}',
    '{"v":1,"open":"yes","visited":[]}',
  ]) {
    assert.deepEqual(readGuideState(memoryStorage({ [GUIDE_STORAGE_KEY]: raw })), fresh, raw);
  }
});

test("unknown and repeated step ids in storage are dropped", () => {
  const raw = JSON.stringify({ v: 1, open: true, visited: ["als", "nope", 3, "pah", "als"] });
  assert.deepEqual(readGuideState(memoryStorage({ [GUIDE_STORAGE_KEY]: raw })).visited, [
    "als",
    "pah",
  ]);
});

test("mark a step: stored, announced, and read back", () => {
  const storage = memoryStorage();
  const { target, actions } = recorder();
  markGuideStep("ipf", { storage, target });
  markGuideStep("ipf", { storage, target });
  markGuideStep("als", { storage, target });
  assert.deepEqual(readGuideState(storage).visited, ["ipf", "als"]);
  assert.deepEqual(actions, [
    { type: "mark", step: "ipf" },
    { type: "mark", step: "ipf" },
    { type: "mark", step: "als" },
  ]);
});

test("mark, then reset: the checks clear, the panel stays as it was", () => {
  const storage = memoryStorage();
  const { target, actions } = recorder();
  setGuideOpen(false, { storage, target });
  markGuideStep("pah", { storage, target });
  resetGuide({ storage, target });
  const state = readGuideState(storage);
  assert.deepEqual(state.visited, []);
  assert.equal(isGuideOpen(state, { narrow: false }), false);
  assert.deepEqual(actions.at(-1), { type: "reset" });
});

test("a collapse or an expand is remembered on every screen size", () => {
  const storage = memoryStorage();
  setGuideOpen(false, { storage, target: null });
  assert.equal(isGuideOpen(readGuideState(storage), { narrow: false }), false);
  setGuideOpen(true, { storage, target: null });
  assert.equal(isGuideOpen(readGuideState(storage), { narrow: true }), true);
});

test("storage that throws on write still announces the change, so the panel updates", () => {
  const { target, actions } = recorder();
  assert.doesNotThrow(() => markGuideStep("als", { storage: throwing, target }));
  assert.doesNotThrow(() => setGuideOpen(false, { storage: throwing, target }));
  assert.doesNotThrow(() => resetGuide({ storage: throwing, target }));
  assert.deepEqual(actions, [
    { type: "mark", step: "als" },
    { type: "open", open: false },
    { type: "reset" },
  ]);
});

test("a mounted panel applies each announced action to its own state", () => {
  let state = readGuideState(null);
  state = applyGuideAction(state, { type: "mark", step: "ipf_flip" });
  state = applyGuideAction(state, { type: "mark", step: "feasibility" });
  state = applyGuideAction(state, { type: "mark", step: "feasibility" });
  assert.deepEqual(state.visited, ["ipf_flip", "feasibility"]);
  state = applyGuideAction(state, { type: "open", open: false });
  assert.equal(isGuideOpen(state, { narrow: false }), false);
  state = applyGuideAction(state, { type: "reset" });
  assert.deepEqual(state.visited, []);
});
