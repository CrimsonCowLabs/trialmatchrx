// Unit tests for the replay bar's state (lib/replay.ts). Run with `pnpm test` (node:test).
import assert from "node:assert/strict";
import { test } from "node:test";

import type { TraceEvent } from "./api.ts";
import {
  INITIAL_REPLAY,
  replayPlayback,
  replayPosition,
  replayReducer,
  type ReplayState,
} from "./replay.ts";

function ev(id: string, seq: number, status: TraceEvent["status"] = "ok"): TraceEvent {
  return {
    id,
    seq,
    run_id: "r1",
    parent_id: null,
    kind: "step",
    name: id,
    status,
    started_at: "2026-11-12T09:00:00Z",
    ended_at: status === "started" ? null : "2026-11-12T09:00:01Z",
    input: null,
    output: null,
    model: null,
    tokens_in: null,
    tokens_out: null,
    cost_usd: null,
    cache_hit: false,
    note: null,
  };
}

// "a" opens at seq 1 and closes at seq 3; "b" is a one-shot at seq 2.
const EMISSIONS = [ev("a", 1, "started"), ev("b", 2), ev("a", 3)];

const play = (actions: Parameters<typeof replayReducer>[1][], from: ReplayState = INITIAL_REPLAY) =>
  actions.reduce(replayReducer, from);

const tick = { type: "tick", emissions: EMISSIONS } as const;

test("a replay starts empty, playing, at 1x", () => {
  assert.deepEqual(INITIAL_REPLAY, { index: 0, events: [], playing: true, speed: 1 });
});

test("each tick shows the next emission, folding a close into its open event", () => {
  const two = play([tick, tick]);
  assert.equal(two.index, 2);
  assert.deepEqual(
    two.events.map((e) => [e.id, e.status]),
    [
      ["a", "started"],
      ["b", "ok"],
    ],
  );
  const three = play([tick], two);
  assert.deepEqual(
    three.events.map((e) => [e.id, e.status]),
    [
      ["a", "ok"],
      ["b", "ok"],
    ],
  );
});

test("a tick past the last emission changes nothing", () => {
  const done = play([tick, tick, tick]);
  assert.equal(play([tick], done), done);
});

test("a tick while paused changes nothing", () => {
  const paused = play([tick, { type: "toggle" }]);
  assert.equal(paused.playing, false);
  assert.equal(play([tick], paused), paused);
});

test("toggle resumes a paused replay", () => {
  assert.equal(play([{ type: "toggle" }, { type: "toggle" }]).playing, true);
});

test("skip to end shows every emission folded, as the finished trace", () => {
  const end = play([tick, { type: "skip", emissions: EMISSIONS }]);
  assert.equal(end.index, 3);
  assert.deepEqual(
    end.events.map((e) => [e.id, e.status]),
    [
      ["a", "ok"],
      ["b", "ok"],
    ],
  );
});

test("restart goes back to the start and plays, keeping the speed", () => {
  const restarted = play([
    { type: "speed", speed: 16 },
    tick,
    { type: "toggle" },
    { type: "restart" },
  ]);
  assert.deepEqual(restarted, { index: 0, events: [], playing: true, speed: 16 });
});

test("the position is the last shown emission's seq out of the run's last seq", () => {
  assert.deepEqual(replayPosition(EMISSIONS, 0), { seq: 0, lastSeq: 3, fraction: 0 });
  assert.deepEqual(replayPosition(EMISSIONS, 2), { seq: 2, lastSeq: 3, fraction: 2 / 3 });
  assert.deepEqual(replayPosition(EMISSIONS, 3), { seq: 3, lastSeq: 3, fraction: 1 });
});

test("an empty trace sits at seq 0 / 0 with an empty progress bar", () => {
  assert.deepEqual(replayPosition([], 0), { seq: 0, lastSeq: 0, fraction: 0 });
});

test("the progress bar fills by seq, so it agrees with seq N / M when seqs have gaps", () => {
  const gappy = [ev("a", 2), ev("b", 8)];
  assert.deepEqual(replayPosition(gappy, 1), { seq: 2, lastSeq: 8, fraction: 0.25 });
});

test("a replay is running while playing with emissions left, and finished past the last", () => {
  assert.deepEqual(replayPlayback(INITIAL_REPLAY, EMISSIONS), { finished: false, running: true });
  assert.deepEqual(replayPlayback(play([{ type: "toggle" }]), EMISSIONS), {
    finished: false,
    running: false,
  });
  assert.deepEqual(replayPlayback(play([tick, tick, tick]), EMISSIONS), {
    finished: true,
    running: false,
  });
});

test("speed changes keep the position", () => {
  const fast = play([tick, { type: "speed", speed: 4 }]);
  assert.equal(fast.speed, 4);
  assert.equal(fast.index, 1);
});
