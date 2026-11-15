// The replay bar's state (design 07): which emissions of a finished run are shown, whether it
// is playing, and at what speed. Pure, so `lib/replay.test.ts` runs it under node:test; the
// replay page drives `tick` from a timer.
import type { TraceEvent } from "./api.ts";
import { upsertEvent } from "./trace.ts";

export const REPLAY_SPEEDS = [1, 4, 16] as const;
export type ReplaySpeed = (typeof REPLAY_SPEEDS)[number];

export interface ReplayState {
  /** How many emissions are shown. */
  index: number;
  /** The shown emissions, folded with `upsertEvent` (a close replaces its open event). */
  events: TraceEvent[];
  playing: boolean;
  speed: ReplaySpeed;
}

export type ReplayAction =
  | { type: "tick"; emissions: TraceEvent[] }
  | { type: "toggle" }
  | { type: "restart" }
  | { type: "skip"; emissions: TraceEvent[] }
  | { type: "speed"; speed: ReplaySpeed };

export const INITIAL_REPLAY: ReplayState = { index: 0, events: [], playing: true, speed: 1 };

export function replayReducer(state: ReplayState, action: ReplayAction): ReplayState {
  switch (action.type) {
    case "tick": {
      if (!state.playing || state.index >= action.emissions.length) return state;
      return {
        ...state,
        index: state.index + 1,
        events: upsertEvent(state.events, action.emissions[state.index]),
      };
    }
    case "toggle":
      return { ...state, playing: !state.playing };
    case "restart":
      return { ...INITIAL_REPLAY, speed: state.speed };
    case "skip":
      return {
        ...state,
        index: action.emissions.length,
        events: action.emissions.reduce(upsertEvent, [] as TraceEvent[]),
      };
    case "speed":
      return { ...state, speed: action.speed };
  }
}

/** Whether every emission is shown, and whether the timer should be ticking. */
export function replayPlayback(
  state: ReplayState,
  emissions: TraceEvent[],
): { finished: boolean; running: boolean } {
  const finished = state.index >= emissions.length;
  return { finished, running: state.playing && !finished };
}

/** "seq N / M": the last shown emission's seq out of the last one's, and how far along the
 *  bar is in the same unit (N over M). */
export function replayPosition(
  emissions: TraceEvent[],
  index: number,
): { seq: number; lastSeq: number; fraction: number } {
  const seq = emissions[index - 1]?.seq ?? 0;
  const lastSeq = emissions.at(-1)?.seq ?? 0;
  return { seq, lastSeq, fraction: lastSeq === 0 ? 0 : seq / lastSeq };
}
