"use client";

// Basic trace timeline (M0): a tree by parent_id, one row per event, click to expand the
// raw input/output. M3 adds grouping by trial/criterion, "Why?" linking and JSON export.
import {
  Brain,
  ListTree,
  Play,
  Scale,
  ShieldCheck,
  TriangleAlert,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import type { TraceEvent } from "@/lib/api";
import type { StreamState } from "@/lib/sse";

const KIND_ICON: Record<TraceEvent["kind"], LucideIcon> = {
  run: Play,
  step: ListTree,
  llm: Brain,
  tool: Wrench,
  rule: Scale,
  guardrail: ShieldCheck,
  error: TriangleAlert,
};

const STATUS_VARIANT: Record<
  TraceEvent["status"],
  "default" | "secondary" | "destructive" | "outline"
> = {
  started: "outline",
  ok: "secondary",
  failed: "destructive",
  skipped: "outline",
};

function latencyMs(e: TraceEvent): number | null {
  if (!e.ended_at) return null;
  return new Date(e.ended_at).getTime() - new Date(e.started_at).getTime();
}

interface Node {
  event: TraceEvent;
  depth: number;
}

/** Depth-first order; events whose parent isn't in the list are treated as roots. */
function flattenTree(events: TraceEvent[]): Node[] {
  const ids = new Set(events.map((e) => e.id));
  const children = new Map<string | null, TraceEvent[]>();
  for (const e of events) {
    const parent = e.parent_id && ids.has(e.parent_id) ? e.parent_id : null;
    children.set(parent, [...(children.get(parent) ?? []), e]);
  }
  const out: Node[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const event of children.get(parent) ?? []) {
      out.push({ event, depth });
      walk(event.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

function Totals({ events }: { events: TraceEvent[] }) {
  const llm = events.filter((e) => e.kind === "llm");
  const tokens = llm.reduce((n, e) => n + (e.tokens_in ?? 0) + (e.tokens_out ?? 0), 0);
  const cost = events.reduce((n, e) => n + (e.cost_usd ?? 0), 0);
  const cacheHits = events.filter((e) => e.cache_hit).length;
  return (
    <div className="flex flex-wrap gap-4 border-b px-3 py-2 text-xs text-muted-foreground">
      <span>{events.length} events</span>
      <span>{llm.length} LLM calls</span>
      <span>{tokens} tokens</span>
      <span>${cost.toFixed(4)}</span>
      <span>{cacheHits} cache hits</span>
    </div>
  );
}

function Row({ node }: { node: Node }) {
  const [open, setOpen] = useState(false);
  const { event, depth } = node;
  const Icon = KIND_ICON[event.kind];
  const ms = latencyMs(event);
  const tokens = (event.tokens_in ?? 0) + (event.tokens_out ?? 0);

  return (
    <li data-testid="trace-row" data-event-id={event.id} className="border-b last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-muted"
        style={{ paddingLeft: `${0.75 + depth * 1.25}rem` }}
      >
        <Icon className="size-4 shrink-0 text-muted-foreground" aria-label={event.kind} />
        <span className="flex-1 truncate font-mono text-xs">{event.name}</span>
        <Badge variant={STATUS_VARIANT[event.status]}>{event.status}</Badge>
        <span className="w-14 text-right text-xs tabular-nums text-muted-foreground">
          {ms === null ? "…" : `${ms} ms`}
        </span>
        <span className="w-16 text-right text-xs tabular-nums text-muted-foreground">
          {tokens ? `${tokens} tok` : ""}
        </span>
      </button>
      {event.note && (
        <p
          className="px-3 pb-1 text-xs text-muted-foreground"
          style={{ paddingLeft: `${2.5 + depth * 1.25}rem` }}
        >
          {event.note}
        </p>
      )}
      {open && (
        <pre className="mx-3 mb-2 max-h-64 overflow-auto rounded bg-muted p-2 text-xs">
          {JSON.stringify(
            { input: event.input, output: event.output, model: event.model, seq: event.seq },
            null,
            2,
          )}
        </pre>
      )}
    </li>
  );
}

export function TracePanel({ events, state }: { events: TraceEvent[]; state: StreamState }) {
  const nodes = useMemo(() => flattenTree(events), [events]);
  return (
    <section className="flex flex-col rounded-lg border bg-card" aria-label="Trace">
      <header className="flex items-center justify-between border-b px-3 py-2">
        <h2 className="text-sm font-semibold">Trace</h2>
        <Badge variant={state === "error" ? "destructive" : "outline"}>{state}</Badge>
      </header>
      <Totals events={events} />
      {nodes.length === 0 ? (
        <p className="px-3 py-6 text-center text-sm text-muted-foreground">Waiting for events…</p>
      ) : (
        <ol>
          {nodes.map((node) => (
            <Row key={node.event.id} node={node} />
          ))}
        </ol>
      )}
    </section>
  );
}
