"use client";

// The trace drawer on every run page: a totals strip, then the timeline tree (run > trial >
// criterion > llm call) with one row per event. Clicking a row selects it (highlighting the
// verdict it produced) and expands its prompt, raw output, parsed output and errors.
// Selection state lives in the page (`useTraceSelection`) so "Why?" on a verdict can drive it.
import {
  Brain,
  ChevronDown,
  ChevronRight,
  Download,
  ListTree,
  Play,
  Scale,
  ShieldCheck,
  TriangleAlert,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, errorMessage, type TraceEvent } from "@/lib/api";
import type { StreamState } from "@/lib/sse";
import { computeTotals, latencyMs, traceRows, type TraceRow } from "@/lib/trace";
import type { TraceSelection } from "@/lib/use-trace-selection";

const KIND_ICON: Record<TraceEvent["kind"], LucideIcon> = {
  run: Play,
  step: ListTree,
  llm: Brain,
  tool: Wrench,
  rule: Scale,
  guardrail: ShieldCheck,
  error: TriangleAlert,
};

export type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

/** The status badge of a live run page, by SSE stream state. */
export const STREAM_VARIANT: Record<StreamState, BadgeVariant> = {
  connecting: "outline",
  open: "outline",
  done: "secondary",
  error: "destructive",
};

const STATUS_VARIANT: Record<TraceEvent["status"], BadgeVariant> = {
  started: "outline",
  ok: "secondary",
  failed: "destructive",
  skipped: "outline",
};

const usd = (n: number) => `$${n.toFixed(n < 1 ? 4 : 2)}`;

/** Re-renders every `ms` while `active`, so the wall clock ticks between events. */
function useNow(active: boolean, ms = 500): number | undefined {
  const [now, setNow] = useState<number | undefined>(undefined);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(timer);
  }, [active, ms]);
  return active ? now : undefined;
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex flex-col">
      <span className="text-sm font-medium tabular-nums">{value}</span>
      <span className="text-[0.65rem] uppercase tracking-wide text-muted-foreground">{label}</span>
    </div>
  );
}

function TotalsStrip({ events, live }: { events: TraceEvent[]; live: boolean }) {
  const now = useNow(live);
  const t = computeTotals(events, now);
  return (
    <div
      data-testid="trace-totals"
      className="grid grid-cols-3 gap-x-4 gap-y-2 border-b px-3 py-2 sm:grid-cols-6"
    >
      <Stat label="LLM calls" value={t.llmCalls} />
      <Stat label="tokens" value={(t.tokensIn + t.tokensOut).toLocaleString()} />
      <Stat label="cost" value={usd(t.costUsd)} />
      <Stat label="wall time" value={t.wallTimeS === null ? "–" : `${t.wallTimeS.toFixed(1)} s`} />
      <Stat label="cache hits" value={t.cacheHits} />
      <Stat label="guardrails" value={t.guardrailTrips} />
    </div>
  );
}

function Json({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto rounded bg-muted p-2 text-xs whitespace-pre-wrap break-words">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <h4 className="text-[0.65rem] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      {children}
    </div>
  );
}

interface PromptMessage {
  role?: string;
  content?: unknown;
  tool_calls?: unknown;
}

/** LangChain chat input is `{messages: [[{role, content}, ...]]}` (one batch per call). */
function promptMessages(input: TraceEvent["input"]): PromptMessage[] | null {
  const batches = input?.messages;
  if (!Array.isArray(batches)) return null;
  return batches.flatMap((b) => (Array.isArray(b) ? b : [b])) as PromptMessage[];
}

function Messages({ messages }: { messages: PromptMessage[] }) {
  return (
    <ol className="flex flex-col gap-1">
      {messages.map((m, i) => (
        <li key={i} className="rounded bg-muted p-2 text-xs">
          <span className="font-mono font-semibold">{m.role ?? "message"}</span>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words">
            {typeof m.content === "string" ? m.content : JSON.stringify(m.content, null, 2)}
          </pre>
          {m.tool_calls !== undefined && <Json value={m.tool_calls} />}
        </li>
      ))}
    </ol>
  );
}

/** Structured output of an `llm` event: the args of each tool call in its returned messages
 *  (`with_structured_output` answers with a tool call). */
function toolCallArgs(output: TraceEvent["output"]): unknown[] {
  const messages = output?.messages;
  if (!Array.isArray(messages)) return [];
  return (messages as PromptMessage[]).flatMap((m) =>
    Array.isArray(m.tool_calls) ? m.tool_calls.map((c: { args?: unknown }) => c.args ?? c) : [],
  );
}

const ERROR_KEYS =["error", "errors", "failed"];

/** Whatever an event's output says went wrong: `error`, `errors`, or guardrail `failed`. */
function errorsOf(output: TraceEvent["output"]): unknown[] {
  if (!output) return [];
  return ERROR_KEYS.map((k) => output[k]).filter(
    (v) => v !== undefined && v !== null && !(Array.isArray(v) && v.length === 0),
  );
}

function Details({ event }: { event: TraceEvent }) {
  const messages = promptMessages(event.input);
  const errors = errorsOf(event.output);
  const parsed = toolCallArgs(event.output);
  const output = Object.fromEntries(
    Object.entries(event.output ?? {}).filter(([k]) => !ERROR_KEYS.includes(k)),
  );
  const meta = [
    event.model && `model ${event.model}`,
    `seq ${event.seq}`,
    event.tokens_in !== null && `${event.tokens_in} in / ${event.tokens_out ?? 0} out tokens`,
    event.cost_usd !== null && usd(event.cost_usd),
    event.cache_hit && "cache hit",
  ].filter(Boolean);
  return (
    <div data-testid="trace-details" className="mx-3 mb-2 flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">{meta.join(" · ")}</p>
      {messages ? (
        <Section title="Prompt messages">
          <Messages messages={messages} />
        </Section>
      ) : (
        event.input && (
          <Section title="Input">
            <Json value={event.input} />
          </Section>
        )
      )}
      {event.kind === "llm" && event.output ? (
        <>
          <Section title="Raw model output">
            <Json value={output} />
          </Section>
          {parsed.length > 0 && (
            <Section title="Parsed output">
              <Json value={parsed.length === 1 ? parsed[0] : parsed} />
            </Section>
          )}
        </>
      ) : (
        Object.keys(output).length > 0 && (
          <Section title="Output">
            <Json value={output} />
          </Section>
        )
      )}
      {errors.length > 0 && (
        <Section title="Errors">
          <div className="rounded border border-destructive/40 text-destructive">
            <Json value={errors.length === 1 ? errors[0] : errors} />
          </div>
        </Section>
      )}
    </div>
  );
}

function Row({
  row,
  selection,
  producesVerdict,
}: {
  row: TraceRow;
  selection: TraceSelection;
  producesVerdict: boolean;
}) {
  const { event, depth, hasChildren } = row;
  const Icon = KIND_ICON[event.kind];
  const ms = latencyMs(event);
  const tokens = (event.tokens_in ?? 0) + (event.tokens_out ?? 0);
  const expanded = selection.expanded.has(event.id);
  const open = selection.details.has(event.id);
  const selected = selection.selectedId === event.id;
  const indent = `${0.25 + depth * 1}rem`;

  return (
    <li
      data-testid="trace-row"
      data-event-id={event.id}
      data-selected={selected || undefined}
      className={`border-b last:border-b-0 ${selected ? "bg-sky-50 ring-1 ring-sky-400 ring-inset dark:bg-sky-950" : ""}`}
    >
      <div className="flex items-center" style={{ paddingLeft: indent }}>
        {hasChildren ? (
          <button
            type="button"
            onClick={() => selection.toggleExpanded(event.id)}
            aria-label={`${expanded ? "Collapse" : "Expand"} ${event.name}`}
            aria-expanded={expanded}
            className="flex size-5 shrink-0 items-center justify-center text-muted-foreground"
          >
            {expanded ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
          </button>
        ) : (
          <span className="size-5 shrink-0" />
        )}
        <button
          type="button"
          onClick={() => selection.select(event.id)}
          aria-pressed={selected}
          className="flex min-w-0 flex-1 items-center gap-2 py-1.5 pr-3 text-left text-sm hover:bg-muted"
        >
          <Icon
            className="size-4 shrink-0 text-muted-foreground"
            aria-label={event.kind}
            role="img"
          />
          <span className="flex-1 truncate font-mono text-xs" title={event.name}>
            {event.name}
            {producesVerdict && <span className="ml-1 text-sky-600">· verdict</span>}
          </span>
          <Badge variant={STATUS_VARIANT[event.status]}>{event.status}</Badge>
          <span className="w-14 text-right text-xs tabular-nums text-muted-foreground">
            {ms === null ? "…" : `${ms} ms`}
          </span>
          <span className="w-14 text-right text-xs tabular-nums text-muted-foreground">
            {tokens ? `${tokens} tok` : ""}
          </span>
          <span className="w-14 text-right text-xs tabular-nums text-muted-foreground">
            {event.cost_usd ? usd(event.cost_usd) : ""}
          </span>
        </button>
      </div>
      {event.note && (
        <p
          className="pb-1 pr-3 text-xs text-muted-foreground"
          style={{ paddingLeft: `calc(${indent} + 1.25rem)` }}
        >
          {event.note}
        </p>
      )}
      {open && <Details event={event} />}
    </li>
  );
}

async function downloadTrace(runId: string): Promise<void> {
  // Exactly what GET /api/runs/{run_id}/trace returns, not the page's in-memory copy.
  const events = await api.getTrace(runId);
  const blob = new Blob([JSON.stringify(events, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `trace-${runId}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function ExportButton({ runId }: { runId: string }) {
  const [error, setError] = useState<string | null>(null);
  return (
    <Button
      variant="outline"
      size="xs"
      title={error ?? "Download GET /api/runs/{run_id}/trace"}
      onClick={() =>
        downloadTrace(runId).then(
          () => setError(null),
          (err: unknown) => setError(errorMessage(err)),
        )
      }
    >
      <Download /> {error ? "Export failed" : "Export JSON"}
    </Button>
  );
}

export interface TracePanelProps {
  runId: string;
  events: TraceEvent[];
  selection: TraceSelection;
  /** Event ids some verdict points at (`trace_event_id`), marked in the tree. */
  verdictEventIds: ReadonlySet<string>;
  /** True while events are still arriving: the wall clock ticks. */
  live: boolean;
  status: { label: string; variant: BadgeVariant };
}

export function TracePanel({
  runId,
  events,
  selection,
  verdictEventIds,
  live,
  status,
}: TracePanelProps) {
  const rows = useMemo(() => traceRows(events, selection.expanded), [events, selection.expanded]);
  const listRef = useRef<HTMLOListElement>(null);
  const { scrollRequest } = selection;

  useEffect(() => {
    if (!scrollRequest) return;
    // Scroll the trace list only (not the window), so the verdict stays where the user clicked.
    const list = listRef.current;
    const el = list?.querySelector<HTMLElement>(
      `[data-event-id="${CSS.escape(scrollRequest.id)}"]`,
    );
    if (list && el) list.scrollTo({ top: el.offsetTop, behavior: "smooth" });
  }, [scrollRequest]);

  return (
    <section
      className="flex max-h-[calc(100vh-2rem)] flex-col rounded-lg border bg-card md:sticky md:top-4"
      aria-label="Trace"
    >
      <header className="flex items-center justify-between gap-2 border-b px-3 py-2">
        <h2 className="text-sm font-semibold">Trace</h2>
        <div className="flex items-center gap-2">
          <Badge variant={status.variant}>{status.label}</Badge>
          <ExportButton runId={runId} />
        </div>
      </header>
      <TotalsStrip events={events} live={live} />
      {rows.length === 0 ? (
        <p className="px-3 py-6 text-center text-sm text-muted-foreground">Waiting for events…</p>
      ) : (
        <ol ref={listRef} className="relative min-h-0 flex-1 overflow-y-auto">
          {rows.map((row) => (
            <Row
              key={row.event.id}
              row={row}
              selection={selection}
              producesVerdict={verdictEventIds.has(row.event.id)}
            />
          ))}
        </ol>
      )}
    </section>
  );
}
