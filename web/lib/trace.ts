// Pure helpers over a run's trace events, shared by the live run page and the replay page.
// No React here, so `lib/trace.test.ts` can run them under node:test.
import type { TraceEvent } from "./api.ts";

export interface Totals {
  llmCalls: number;
  tokensIn: number;
  tokensOut: number;
  costUsd: number;
  cacheHits: number;
  guardrailTrips: number;
  wallTimeS: number | null;
}

const ms = (iso: string) => new Date(iso).getTime();

/** How long an event took, or null while it is still running. */
export function latencyMs(e: TraceEvent): number | null {
  return e.ended_at ? ms(e.ended_at) - ms(e.started_at) : null;
}

/** Apply one emission to the list. A step arrives twice (started, then final) under one id,
 *  so events are upserted by id, kept in order of first appearance, and an emission with a
 *  seq no newer than what we hold is ignored. */
export function upsertEvent(events: TraceEvent[], next: TraceEvent): TraceEvent[] {
  const i = events.findIndex((e) => e.id === next.id);
  if (i === -1) return [...events, next];
  if (events[i].seq >= next.seq) return events; // duplicate or stale
  const copy = events.slice();
  copy[i] = next;
  return copy;
}

function startedEmission(e: TraceEvent, seq: number): TraceEvent {
  return {
    ...e,
    seq,
    status: "started",
    ended_at: null,
    output: null,
    tokens_in: null,
    tokens_out: null,
    cost_usd: null,
    cache_hit: false,
    note: null,
  };
}

/** Every emission of a run, in seq order, rebuilt from its exported trace (`GET /trace`: one
 *  entry per event in final state, ordered by first appearance).
 *
 *  Seqs are 1..N per run. Walking them in order, a seq that is some event's final seq is
 *  either that event closing (it already appeared) or a one-shot event appearing; any other
 *  seq is the `started` emission of the next event in first-appearance order. The started
 *  copy carries the final event's input and model but no output, tokens, cost or note.
 *  Relies on the recorder emitting each event once (`event`) or twice (`started`, then
 *  final); an intermediate emission would need `/trace` to export every emission instead. */
export function replayEmissions(trace: TraceEvent[]): TraceEvent[] {
  const finalBySeq = new Map(trace.map((e) => [e.seq, e]));
  const lastSeq = trace.reduce((n, e) => Math.max(n, e.seq), 0);
  const appeared = new Set<string>();
  const out: TraceEvent[] = [];
  let next = 0;
  for (let seq = 1; seq <= lastSeq; seq++) {
    const final = finalBySeq.get(seq);
    if (final) {
      // a close, a one-shot, or (in a trace not in first-appearance order) an early event
      appeared.add(final.id);
      out.push(final);
      continue;
    }
    while (next < trace.length && appeared.has(trace[next].id)) next++;
    const upcoming = trace[next];
    if (!upcoming) continue; // a seq gap
    appeared.add(upcoming.id);
    out.push(startedEmission(upcoming, seq));
  }
  return out;
}

export interface TraceRow {
  event: TraceEvent;
  depth: number;
  hasChildren: boolean;
}

function parentOf(events: TraceEvent[]): Map<string, string | null> {
  const ids = new Set(events.map((e) => e.id));
  return new Map(
    events.map((e) => [e.id, e.parent_id && ids.has(e.parent_id) ? e.parent_id : null]),
  );
}

/** The timeline tree, depth first, in order of first appearance. A match run nests
 *  trial:<nct> > rule / judge:<nct>:<criterion> > llm / guardrail, so this is the
 *  "by trial, then criterion" grouping. Children of an event not in `expanded` are hidden;
 *  events whose parent isn't in the list are roots. */
export function traceRows(events: TraceEvent[], expanded: ReadonlySet<string>): TraceRow[] {
  const parents = parentOf(events);
  const children = new Map<string | null, TraceEvent[]>();
  for (const e of events) {
    const p = parents.get(e.id) ?? null;
    const siblings = children.get(p);
    if (siblings) siblings.push(e);
    else children.set(p, [e]);
  }
  const out: TraceRow[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const event of children.get(parent) ?? []) {
      const hasChildren = children.has(event.id);
      out.push({ event, depth, hasChildren });
      if (hasChildren && expanded.has(event.id)) walk(event.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

/** Parent, grandparent, ... up to the root. */
export function ancestorIds(events: TraceEvent[], id: string): string[] {
  const parents = parentOf(events);
  const out: string[] = [];
  for (let p = parents.get(id) ?? null; p && !out.includes(p); p = parents.get(p) ?? null) {
    out.push(p);
  }
  return out;
}

/** The verdict event a selected trace event belongs to: the event itself or its nearest
 *  ancestor whose id is some verdict's `trace_event_id` (an llm call or guardrail inside a
 *  judge step highlights that judge's verdict). */
export function verdictEventFor(
  events: TraceEvent[],
  selectedId: string | null,
  verdictEventIds: ReadonlySet<string>,
): string | null {
  if (!selectedId) return null;
  return (
    [selectedId, ...ancestorIds(events, selectedId)].find((id) => verdictEventIds.has(id)) ??
    null
  );
}

const emittedAt = (e: TraceEvent) =>
  ms(e.status === "started" ? e.started_at : (e.ended_at ?? e.started_at));

/** Wait before each emission (ms): the original gap to the previous one, capped at `capMs`
 *  (SPEC's replay caps gaps at 0.2 s). The first emission waits 0. */
export function replayDelays(emissions: TraceEvent[], capMs: number): number[] {
  return emissions.map((e, i) =>
    i === 0 ? 0 : Math.min(capMs, Math.max(0, emittedAt(e) - emittedAt(emissions[i - 1]))),
  );
}

/** Same rules as the API's `compute_totals`. Wall time runs from the first event's start to
 *  `now` (pass it while the run is live) or else to the last timestamp seen. */
export function computeTotals(events: TraceEvent[], now?: number): Totals {
  const llm = events.filter((e) => e.kind === "llm");
  let first = Infinity;
  let last = -Infinity;
  for (const e of events) {
    first = Math.min(first, ms(e.started_at));
    last = Math.max(last, ms(e.ended_at ?? e.started_at));
  }
  return {
    llmCalls: llm.length,
    tokensIn: llm.reduce((n, e) => n + (e.tokens_in ?? 0), 0),
    tokensOut: llm.reduce((n, e) => n + (e.tokens_out ?? 0), 0),
    costUsd: llm.reduce((n, e) => n + (e.cost_usd ?? 0), 0),
    cacheHits: events.filter((e) => e.cache_hit).length,
    guardrailTrips: events.filter((e) => e.kind === "guardrail" && e.status === "failed").length,
    wallTimeS: events.length ? (Math.max(last, now ?? -Infinity) - first) / 1000 : null,
  };
}
