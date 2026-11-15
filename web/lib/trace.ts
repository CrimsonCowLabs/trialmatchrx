// Pure helpers over a run's trace events, shared by the live run page and the replay page.
// No React here, so `lib/trace.test.ts` can run them under node:test.
import type { Schemas, TraceEvent } from "./api.ts";

export type RunTotals = Schemas["RunTotals"];

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
  /** Tokens (in + out) and cost of the llm calls in this event's subtree, itself included
   *  (the same events `computeTotals` counts), so a collapsed trial still shows its spend. */
  tokens: number;
  costUsd: number;
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
  const spend = new Map<string, { tokens: number; costUsd: number }>();
  const spendOf = (e: TraceEvent, seen: Set<string>): { tokens: number; costUsd: number } => {
    const cached = spend.get(e.id);
    if (cached) return cached;
    seen.add(e.id);
    const own =
      e.kind === "llm"
        ? { tokens: (e.tokens_in ?? 0) + (e.tokens_out ?? 0), costUsd: e.cost_usd ?? 0 }
        : { tokens: 0, costUsd: 0 };
    for (const c of children.get(e.id) ?? []) {
      if (seen.has(c.id)) continue; // a parent_id cycle
      const s = spendOf(c, seen);
      own.tokens += s.tokens;
      own.costUsd += s.costUsd;
    }
    spend.set(e.id, own);
    return own;
  };
  const out: TraceRow[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const event of children.get(parent) ?? []) {
      const hasChildren = children.has(event.id);
      out.push({ event, depth, hasChildren, ...spendOf(event, new Set()) });
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

/** The run's totals derived from the events seen so far, counted by the same rules as the
 *  API's `compute_totals` (both are held to `api/tests/fixtures/trace/totals.json`). Only
 *  wall time differs: the API measures the run row (null until it ends), this runs from the
 *  first event's start to `now` (pass it while the run is live) or else to the last
 *  timestamp seen. */
export function computeTotals(events: TraceEvent[], now?: number): RunTotals {
  const llm = events.filter((e) => e.kind === "llm");
  let first = Infinity;
  let last = -Infinity;
  for (const e of events) {
    first = Math.min(first, ms(e.started_at));
    last = Math.max(last, ms(e.ended_at ?? e.started_at));
  }
  return {
    llm_calls: llm.length,
    tokens_in: llm.reduce((n, e) => n + (e.tokens_in ?? 0), 0),
    tokens_out: llm.reduce((n, e) => n + (e.tokens_out ?? 0), 0),
    cost_usd: llm.reduce((n, e) => n + (e.cost_usd ?? 0), 0),
    cache_hits: events.filter((e) => e.cache_hit).length,
    guardrail_trips: events.filter((e) => e.kind === "guardrail" && e.status === "failed").length,
    wall_time_s: events.length ? (Math.max(last, now ?? -Infinity) - first) / 1000 : null,
  };
}

type Kind = TraceEvent["kind"];

// Literal class names so Tailwind sees them; colours are the trace-kind tokens in globals.css.
const KIND_STYLE: Record<Kind, { label: string; className: string }> = {
  run: { label: "run", className: "text-kind-run bg-kind-run-bg" },
  step: { label: "step", className: "text-kind-step bg-kind-step-bg" },
  llm: { label: "llm", className: "text-kind-llm bg-kind-llm-bg" },
  tool: { label: "tool", className: "text-kind-tool bg-kind-tool-bg" },
  rule: { label: "rule", className: "text-kind-rule bg-kind-rule-bg" },
  guardrail: { label: "guard", className: "text-kind-guardrail bg-kind-guardrail-bg" },
  error: { label: "error", className: "text-kind-error bg-kind-error-bg" },
};

/** The kind chip on a trace row: a short label and its trace-kind colour tokens. */
export const kindStyle = (kind: Kind) => KIND_STYLE[kind];

export interface PromptMessage {
  role?: string;
  content?: unknown;
  tool_calls?: unknown;
}

/** What the trace panel shows for a selected event. */
export interface EventDetail {
  /** `model …`, `seq …`, tokens, cost, `cache hit`: whichever the event has. */
  meta: string[];
  /** The headline output: an llm call's parsed tool-call args (or its text), else the
   *  event's output without its error keys. Null when there is none. */
  primary: { title: string; value: unknown } | null;
  /** LangChain chat input `{messages: [[{role, content}, ...]]}`, flattened; else null. */
  messages: PromptMessage[] | null;
  /** The input when it isn't prompt messages. */
  input: Record<string, unknown> | null;
  /** An llm call's raw model output (null for other kinds, shown as `primary` there). */
  raw: Record<string, unknown> | null;
  /** Whatever the output says went wrong: `error`, `errors`, or guardrail `failed`. */
  errors: unknown[];
}

const ERROR_KEYS = ["error", "errors", "failed"];

function promptMessages(input: TraceEvent["input"]): PromptMessage[] | null {
  const batches = input?.messages;
  if (!Array.isArray(batches)) return null;
  return batches.flatMap((b) => (Array.isArray(b) ? b : [b])) as PromptMessage[];
}

/** `with_structured_output` answers with a tool call: the args of each one returned. */
function toolCallArgs(output: TraceEvent["output"]): unknown[] {
  const messages = output?.messages;
  if (!Array.isArray(messages)) return [];
  return (messages as PromptMessage[]).flatMap((m) =>
    Array.isArray(m.tool_calls) ? m.tool_calls.map((c: { args?: unknown }) => c.args ?? c) : [],
  );
}

const nonEmpty = (o: Record<string, unknown>) => (Object.keys(o).length ? o : null);

export function eventDetail(event: TraceEvent): EventDetail {
  const out = event.output ?? {};
  const errors = ERROR_KEYS.map((k) => out[k]).filter(
    (v) => v !== undefined && v !== null && !(Array.isArray(v) && v.length === 0),
  );
  const rest = nonEmpty(
    Object.fromEntries(Object.entries(out).filter(([k]) => !ERROR_KEYS.includes(k))),
  );
  const messages = promptMessages(event.input);
  const meta = [
    event.model && `model ${event.model}`,
    `seq ${event.seq}`,
    event.tokens_in !== null &&
      `${count(event.tokens_in)} in / ${count(event.tokens_out ?? 0)} out tokens`,
    event.cost_usd !== null && formatUsd(event.cost_usd),
    event.cache_hit && "cache hit",
  ].filter((m): m is string => Boolean(m));

  let primary: EventDetail["primary"] = null;
  if (event.kind === "llm") {
    const parsed = toolCallArgs(event.output);
    const text = typeof out.text === "string" ? out.text : "";
    if (parsed.length) {
      primary = { title: "Parsed output", value: parsed.length === 1 ? parsed[0] : parsed };
    } else if (text) primary = { title: "Model output", value: text };
  } else if (rest) primary = { title: "Output", value: rest };

  return {
    meta,
    primary,
    messages,
    input: messages ? null : (event.input ?? null),
    raw: event.kind === "llm" ? rest : null,
    errors,
  };
}

/** A row's latency:`1 ms`, `2.2 s`, or `…` while the event is still running. */
export function formatLatency(ms: number | null): string {
  if (ms === null) return "…";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** A row's tokens: `96`, `1.9k`; blank when there are none. */
export function formatTokens(n: number): string {
  if (n === 0) return "";
  return n < 1000 ? String(n) : `${(n / 1000).toFixed(1)}k`;
}

/** `$0.0053` under a dollar (per-call costs are fractions of a cent), `$1.50` above. */
export const formatUsd = (n: number) => `$${n.toFixed(n < 1 ? 4 : 2)}`;

const count = (n: number) => n.toLocaleString("en-US");

export interface TotalsCell {
  label: string;
  value: string;
}

/** The trace panel's totals strip. `runTotals` (from the run summary, once the run is done)
 *  wins; before it arrives the figures are `computeTotals` over the events seen so far and
 *  the clock reads "Elapsed" (first event to `now`), since the API has no wall time for an
 *  unfinished run. A wall time neither source has is left out. */
export function totalsStrip(
  runTotals: RunTotals | null | undefined,
  events: TraceEvent[],
  now?: number,
): { final: boolean; cells: TotalsCell[] } {
  const final = Boolean(runTotals);
  const t = runTotals ?? computeTotals(events, now);
  const cells: (TotalsCell | null)[] = [
    { label: "LLM calls", value: count(t.llm_calls) },
    { label: "Tokens", value: count(t.tokens_in + t.tokens_out) },
    { label: "Cost", value: formatUsd(t.cost_usd) },
    t.wall_time_s === null
      ? null
      : { label: final ? "Wall time" : "Elapsed", value: `${t.wall_time_s.toFixed(1)} s` },
    { label: "Cache hits", value: count(t.cache_hits) },
    { label: "Guardrails", value: count(t.guardrail_trips) },
  ];
  return { final, cells: cells.filter((c) => c !== null) };
}
