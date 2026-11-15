// Unit tests for the pure trace helpers. Run with `pnpm test` (node:test, no extra deps).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import type { Schemas, TraceEvent } from "./api.ts";
import {
  ancestorIds,
  computeTotals,
  replayDelays,
  replayEmissions,
  totalsStrip,
  traceRows,
  upsertEvent,
  verdictEventFor,
} from "./trace.ts";

type RunTotals = Schemas["RunTotals"];

const T0 =Date.UTC(2026, 10, 12, 9, 0, 0);
const at = (ms: number) => new Date(T0 + ms).toISOString();

function ev(over: Partial<TraceEvent> & Pick<TraceEvent, "id" | "seq">): TraceEvent {
  return {
    run_id: "r1",
    parent_id: null,
    kind: "step",
    name: over.id,
    status: "ok",
    started_at: at(0),
    ended_at: at(0),
    input: null,
    output: null,
    model: null,
    tokens_in: null,
    tokens_out: null,
    cost_usd: null,
    cache_hit: false,
    note: null,
    ...over,
  };
}

test("totals count llm calls, tokens and cost from llm events only, like the API", () => {
  const events = [
    ev({ id: "s", seq: 5, started_at: at(0), ended_at: at(3000), cost_usd: 9 }),
    ev({ id: "a", seq: 2, kind: "llm", tokens_in: 100, tokens_out: 20, cost_usd: 0.01 }),
    ev({ id: "b", seq: 4, kind: "llm", tokens_in: 50, tokens_out: 5, cost_usd: 0.002 }),
    ev({ id: "c", seq: 6, kind: "tool", cache_hit: true }),
    ev({ id: "g1", seq: 7, kind: "guardrail", status: "failed" }),
    ev({ id: "g2", seq: 8, kind: "guardrail", status: "ok" }),
    ev({ id: "e", seq: 9, kind: "error", status: "failed" }),
  ];
  const t = computeTotals(events);
  assert.equal(t.llm_calls, 2);
  assert.equal(t.tokens_in, 150);
  assert.equal(t.tokens_out, 25);
  assert.ok(Math.abs(t.cost_usd - 0.012) < 1e-9);
  assert.equal(t.cache_hits, 1);
  assert.equal(t.guardrail_trips, 1);
  assert.equal(t.wall_time_s, 3);
});

test("live totals count exactly what the API's compute_totals counts (shared fixture)", () => {
  // api/tests/test_totals.py holds compute_totals to the same file.
  const doc = JSON.parse(
    readFileSync(new URL("../../api/tests/fixtures/trace/totals.json", import.meta.url), "utf8"),
  ) as { events: TraceEvent[]; expected: Omit<RunTotals, "wall_time_s"> };
  const { wall_time_s, cost_usd, ...counts } = computeTotals(doc.events);
  const { cost_usd: expectedCost, ...expectedCounts } = doc.expected;
  assert.deepEqual(counts, expectedCounts);
  assert.ok(Math.abs(cost_usd - expectedCost) < 1e-9);
  assert.equal(typeof wall_time_s, "number"); // live wall time: from the events' timestamps
});

test("while live, wall time runs from the first event to now", () => {
  const events = [ev({ id: "s", seq: 1, status: "started", started_at: at(1000), ended_at: null })];
  assert.equal(computeTotals(events, T0 + 3500).wall_time_s, 2.5);
  assert.equal(computeTotals([]).wall_time_s, null);
});

// The run as the recorder emitted it: seq 1 trial started, 2 rule (one-shot), 3 judge started,
// 4 llm started, 5 llm done, 6 judge done, 7 trial done.
const trialDone = ev({ id: "trial", seq: 7, ended_at: at(900), output: { tier: "likely" } });
const rule = ev({
  id: "rule",
  seq: 2,
  kind: "rule",
  parent_id: "trial",
  started_at: at(10),
  ended_at: at(10),
});
const judgeDone = ev({
  id: "judge",
  seq: 6,
  parent_id: "trial",
  started_at: at(20),
  ended_at: at(800),
  model: "sonnet",
});
const llmDone = ev({
  id: "llm",
  seq: 5,
  kind: "llm",
  parent_id: "judge",
  started_at: at(30),
  ended_at: at(700),
  tokens_in: 9,
});
// What GET /trace returns: final state, ordered by first appearance.
const TRACE = [trialDone, rule, judgeDone, llmDone];

test("replay rebuilds every emission in seq order from the exported trace", () => {
  const emissions = replayEmissions(TRACE);
  assert.deepEqual(
    emissions.map((e) => [e.seq, e.id, e.status]),
    [
      [1, "trial", "started"],
      [2, "rule", "ok"],
      [3, "judge", "started"],
      [4, "llm", "started"],
      [5, "llm", "ok"],
      [6, "judge", "ok"],
      [7, "trial", "ok"],
    ],
  );
  assert.equal(emissions[0].ended_at, null);
  assert.equal(emissions[0].output, null);
  assert.equal(emissions[3].tokens_in, null);
  assert.equal(emissions[2].model, "sonnet");
});

test("folding the replayed emissions gives back the exported trace", () => {
  const folded = replayEmissions(TRACE).reduce(upsertEvent, [] as TraceEvent[]);
  assert.deepEqual(folded, TRACE);
});

test("replay never drops an event, even from a trace not in first-appearance order", () => {
  const a = ev({ id: "a", seq: 2 });
  const b = ev({ id: "b", seq: 1 });
  const emissions = replayEmissions([a, b]);
  assert.deepEqual(
    emissions.map((e) => [e.seq, e.id, e.status]),
    [
      [1, "b", "ok"],
      [2, "a", "ok"],
    ],
  );
});

test("upsert ignores a stale or duplicate emission", () => {
  const started = replayEmissions(TRACE)[0];
  assert.deepEqual(upsertEvent([trialDone], started), [trialDone]);
  assert.deepEqual(upsertEvent([trialDone], trialDone), [trialDone]);
});

test("replay delays follow the original timing, capped per gap", () => {
  const delays = replayDelays(replayEmissions(TRACE), 200);
  // emission times 0, 10, 20, 30, 700 (gap capped), 800, 900
  assert.deepEqual(delays, [0, 10, 10, 10, 200, 100, 100]);
});

test("rows nest by parent and hide the children of collapsed events", () => {
  const collapsed = traceRows(TRACE, new Set());
  assert.deepEqual(
    collapsed.map((r) => [r.event.id, r.depth, r.hasChildren]),
    [["trial", 0, true]],
  );
  const open = traceRows(TRACE, new Set(["trial", "judge"]));
  assert.deepEqual(
    open.map((r) => [r.event.id, r.depth]),
    [
      ["trial", 0],
      ["rule", 1],
      ["judge", 1],
      ["llm", 2],
    ],
  );
});

test("an event whose parent is missing is shown as a root", () => {
  const rows = traceRows([llmDone], new Set());
  assert.deepEqual(
    rows.map((r) => [r.event.id, r.depth]),
    [["llm", 0]],
  );
});

test("ancestors run from the parent up to the root", () => {
  assert.deepEqual(ancestorIds(TRACE, "llm"), ["judge", "trial"]);
  assert.deepEqual(ancestorIds(TRACE, "trial"), []);
});

test("selecting an event finds the verdict it produced, walking up from nested calls", () => {
  const verdictEvents = new Set(["judge", "rule"]);
  assert.equal(verdictEventFor(TRACE, "llm", verdictEvents), "judge");
  assert.equal(verdictEventFor(TRACE, "rule", verdictEvents), "rule");
  assert.equal(verdictEventFor(TRACE, "trial", verdictEvents), null);
  assert.equal(verdictEventFor(TRACE, null, verdictEvents), null);
});

const RUN_TOTALS: RunTotals = {
  llm_calls: 14,
  tokens_in: 36000,
  tokens_out: 2412,
  cost_usd: 0.1124,
  cache_hits: 6,
  guardrail_trips: 1,
  wall_time_s: 18.4,
};

test("once the run summary is loaded, the strip shows its RunTotals, not the events", () => {
  const events = [ev({ id: "a", seq: 1, kind: "llm", tokens_in: 5, tokens_out: 5 })];
  const strip = totalsStrip(RUN_TOTALS, events);
  assert.equal(strip.final, true);
  assert.deepEqual(strip.cells, [
    { label: "LLM calls", value: "14" },
    { label: "Tokens", value: "38,412" },
    { label: "Cost", value: "$0.1124" },
    { label: "Wall time", value: "18.4 s" },
    { label: "Cache hits", value: "6" },
    { label: "Guardrails", value: "1" },
  ]);
});

test("before RunTotals arrive, the strip counts the events so far and wall time is elapsed", () => {
  const events = [
    ev({ id: "r", seq: 1, kind: "run", status: "started", started_at: at(0), ended_at: null }),
    ev({ id: "a", seq: 2, kind: "llm", tokens_in: 1200, tokens_out: 34, cost_usd: 1.5 }),
  ];
  const strip = totalsStrip(null, events, T0 + 2500);
  assert.equal(strip.final, false);
  assert.deepEqual(strip.cells, [
    { label: "LLM calls", value: "1" },
    { label: "Tokens", value: "1,234" },
    { label: "Cost", value: "$1.50" },
    { label: "Elapsed", value: "2.5 s" },
    { label: "Cache hits", value: "0" },
    { label: "Guardrails", value: "0" },
  ]);
});

test("a wall time no source provides is left out, not shown as a number", () => {
  const labels = (s: { cells: { label: string }[] }) => s.cells.map((c) => c.label);
  assert.ok(!labels(totalsStrip({ ...RUN_TOTALS, wall_time_s: null }, [])).includes("Wall time"));
  assert.ok(!labels(totalsStrip(undefined, [])).includes("Elapsed"));
});
