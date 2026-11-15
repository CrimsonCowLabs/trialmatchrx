"use client";

// The trace panel on every run page (design section 03, right-hand column): a header with the
// stream status and Export JSON, the run totals, then the event tree (run > trial >
// criterion > llm call) with one row per event, coloured by kind. Clicking a row selects it
// (highlighting the verdict it produced) and opens its details inline: model, tokens, cost,
// parsed output, and the prompt, raw output and errors behind disclosures. Selection state
// lives in the page (`useTraceSelection`) so "Why?" on a verdict can drive it.
//
// Below `lg` (the mobile Trace tab) the tree drops the tokens and cost columns under `sm`, and
// a selected event's details open in a bottom sheet instead of inline, with "View verdict"
// back to the criterion it produced.
//
// The panel fills its container's height (capped at the viewport) and scrolls the tree inside,
// so a tall sticky column keeps it in view.
import { ChevronDown, ChevronRight, Download, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, errorMessage, type TraceEvent } from "@/lib/api";
import type { StreamState } from "@/lib/sse";
import {
  eventDetail,
  formatLatency,
  formatTokens,
  formatUsd,
  kindStyle,
  latencyMs,
  statusStyle,
  totalsStrip,
  traceRows,
  verdictEventFor,
  type PromptMessage,
  type RunTotals,
  type TraceRow,
} from "@/lib/trace";
import type { TraceSelection } from "@/lib/use-trace-selection";

export type BadgeVariant = "default" | "secondary" | "destructive" | "outline";

/** The status badge of a live run page, by SSE stream state. */
export const STREAM_VARIANT: Record<StreamState, BadgeVariant> = {
  connecting: "outline",
  open: "outline",
  done: "secondary",
  error: "destructive",
};

/** Re-renders every `ms` while `active`, so the elapsed clock ticks between events. */
function useNow(active: boolean, ms = 500): number | undefined {
  const [now, setNow] = useState<number | undefined>(undefined);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(timer);
  }, [active, ms]);
  return active ? now : undefined;
}

function TotalsStrip({
  totals,
  events,
  live,
}: {
  totals: RunTotals | null | undefined;
  events: TraceEvent[];
  live: boolean;
}) {
  const now = useNow(live && !totals);
  const { final, cells } = totalsStrip(totals, events, now);
  return (
    <dl
      data-testid="trace-totals"
      data-final={final || undefined}
      title={
        final
          ? "Run totals"
          : "Counted from the events so far; the run's totals replace these when it ends"
      }
      className="grid shrink-0 grid-cols-3 border-b border-line-soft"
    >
      {cells.map((c) => (
        <div
          key={c.label}
          className="flex flex-col-reverse border-r border-b border-surface-sunken px-4 py-3 nth-[3n]:border-r-0"
        >
          <dt className="mt-0.5 text-[0.6875rem] font-medium tracking-wider text-ink-4 uppercase">
            {c.label}
          </dt>
          <dd className="font-mono text-[1.0625rem] font-medium tabular-nums">{c.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Json({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto rounded-lg bg-canvas px-3 py-2.5 font-mono text-xs/relaxed whitespace-pre-wrap break-words text-ink">
      {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
    </pre>
  );
}

const SECTION_TITLE = "text-[0.625rem] font-semibold tracking-wider text-ink-4 uppercase";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <h4 className={SECTION_TITLE}>{title}</h4>
      {children}
    </div>
  );
}

/** A collapsed section: the prompt and raw output are there to audit, not to read first. */
function Disclosure({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="group flex flex-col gap-1.5">
      <summary className={`${SECTION_TITLE} flex cursor-pointer list-none items-center gap-1`}>
        <ChevronRight className="size-3 group-open:rotate-90" aria-hidden />
        {title}
      </summary>
      <div className="mt-1.5">{children}</div>
    </details>
  );
}

function Messages({ messages }: { messages: PromptMessage[] }) {
  return (
    <ol className="flex flex-col gap-1.5">
      {messages.map((m, i) => (
        <li key={i} className="flex flex-col gap-1">
          <span className="font-mono text-[0.6875rem] font-semibold text-ink-3">
            {m.role ?? "message"}
          </span>
          <Json value={m.content} />
          {m.tool_calls !== undefined && <Json value={m.tool_calls} />}
        </li>
      ))}
    </ol>
  );
}

/** A selected event's details: meta line, errors, headline output, then the prompt, input and
 *  raw output behind disclosures. Inline under its row from `lg`; in the bottom sheet below. */
function DetailsBody({ event, meta }: { event: TraceEvent; meta?: string[] }) {
  const d = eventDetail(event);
  return (
    <>
      <p className="text-xs text-ink-4">{(meta ?? d.meta).join(" · ")}</p>
      {d.errors.length > 0 && (
        <Section title="Errors">
          <div className="rounded-lg ring-1 ring-verdict-fail/40 text-verdict-fail">
            <Json value={d.errors.length === 1 ? d.errors[0] : d.errors} />
          </div>
        </Section>
      )}
      {d.headline && (
        <Section title={d.headline.title}>
          <Json value={d.headline.value} />
        </Section>
      )}
      {d.messages && (
        <Disclosure title="Prompt messages">
          <Messages messages={d.messages} />
        </Disclosure>
      )}
      {d.input && (
        <Disclosure title="Input">
          <Json value={d.input} />
        </Disclosure>
      )}
      {d.raw && (
        <Disclosure title="Raw model output">
          <Json value={d.raw} />
        </Disclosure>
      )}
    </>
  );
}

function Details({ event, indent }: { event: TraceEvent; indent: string }) {
  return (
    // Below `lg` the bottom sheet shows these instead.
    <div
      data-testid="trace-details"
      className="hidden flex-col gap-2 pr-3.5 pb-3 lg:flex"
      style={{ paddingLeft: indent }}
    >
      <DetailsBody event={event} />
    </div>
  );
}

/** Below `lg`, a tapped event's details slide up from the bottom (design 03 "Trace mobile"),
 *  with "View verdict" when the event belongs to a verdict. */
function DetailSheet({
  event,
  verdictEventId,
  onViewVerdict,
  onClose,
}: {
  event: TraceEvent;
  verdictEventId: string | null;
  onViewVerdict?: (verdictEventId: string) => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const meta = [...eventDetail(event).meta, formatLatency(latencyMs(event))];
  return (
    <div
      role="dialog"
      aria-label={`Trace event ${event.name}`}
      data-testid="trace-sheet"
      className="fixed inset-x-0 bottom-0 z-50 flex max-h-[60dvh] flex-col gap-2 overflow-y-auto rounded-t-2xl border-t border-line bg-surface px-4 pt-2 pb-[calc(1.25rem+env(safe-area-inset-bottom))] shadow-[0_-8px_24px_rgb(20_23_26/0.08)] lg:hidden"
    >
      <span aria-hidden className="h-1 w-9 shrink-0 self-center rounded-full bg-line" />
      <div className="flex items-baseline gap-3">
        <h3 className="min-w-0 flex-1 truncate font-mono text-sm font-medium" title={event.name}>
          {event.name}
        </h3>
        {verdictEventId && onViewVerdict && (
          <button
            type="button"
            onClick={() => onViewVerdict(verdictEventId)}
            className="shrink-0 text-[0.8125rem] font-medium link"
            data-testid="view-verdict"
          >
            View verdict
          </button>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close details"
          className="-mr-1 flex size-7 shrink-0 items-center justify-center self-center rounded text-ink-4 hover:text-ink"
        >
          <X className="size-4" />
        </button>
      </div>
      <DetailsBody event={event} meta={meta} />
    </div>
  );
}

const ROW_PAD_REM = 0.875; // the design's 14px row inset
const DEPTH_REM = 1; // and 16px per level

function Row({
  row,
  selection,
  producesVerdict,
}: {
  row: TraceRow;
  selection: TraceSelection;
  producesVerdict: boolean;
}) {
  const { event, depth, hasChildren, spend } = row;
  const kind = kindStyle(event.kind);
  const status = statusStyle(event.status);
  const expanded = selection.expanded.has(event.id);
  const open = selection.details.has(event.id);
  const selected = selection.selectedId === event.id;
  const indent = `${ROW_PAD_REM + depth * DEPTH_REM}rem`;

  return (
    <li
      data-testid="trace-row"
      data-event-id={event.id}
      data-selected={selected || undefined}
      className={`border-b border-surface-sunken last:border-b-0 ${selected ? "bg-teal-selected shadow-[inset_3px_0_0_var(--teal)]" : ""}`}
    >
      <div className="flex items-center gap-2 pr-3.5" style={{ paddingLeft: indent }}>
        {hasChildren ? (
          <button
            type="button"
            onClick={() => selection.toggleExpanded(event.id)}
            aria-label={`${expanded ? "Collapse" : "Expand"} ${event.name}`}
            aria-expanded={expanded}
            className="-mx-1 flex size-5 shrink-0 items-center justify-center rounded text-ink-5 hover:text-ink"
          >
            {expanded ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
          </button>
        ) : (
          <span className="-mx-1 size-5 shrink-0" />
        )}
        <button
          type="button"
          onClick={() => selection.select(event.id)}
          aria-pressed={selected}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 py-2 text-left"
        >
          <span
            className={`w-[3.25rem] shrink-0 rounded px-1.5 py-0.5 text-center font-mono text-[0.625rem] font-medium uppercase ${kind.className}`}
          >
            {kind.label}
          </span>
          <span className="flex min-w-0 flex-1 gap-1 font-mono text-[0.8125rem]">
            <span className="truncate text-ink" title={event.name}>
              {event.name}
            </span>
            {producesVerdict && <span className="shrink-0 text-teal">· verdict</span>}
          </span>
          {status && (
            <span className={`shrink-0 text-[0.6875rem] font-medium ${status.className}`}>
              {status.label}
            </span>
          )}
          <span className="w-14 shrink-0 text-right font-mono text-xs tabular-nums text-ink-4">
            {formatLatency(latencyMs(event))}
          </span>
          {/* Tokens and cost need the width; on a phone the sheet shows them. */}
          <span className="hidden w-12 shrink-0 text-right font-mono text-xs tabular-nums text-ink-4 sm:inline">
            {formatTokens(spend.tokensIn + spend.tokensOut)}
          </span>
          <span className="hidden w-14 shrink-0 text-right font-mono text-xs tabular-nums text-ink-4 sm:inline">
            {spend.costUsd ? formatUsd(spend.costUsd) : ""}
          </span>
        </button>
      </div>
      {event.note && (
        <p
          className="-mt-1 pr-3.5 pb-2 text-xs text-ink-4"
          style={{ paddingLeft: `calc(${indent} + 1.5rem)` }}
        >
          {event.note}
        </p>
      )}
      {open && <Details event={event} indent={`calc(${indent} + 1.5rem)`} />}
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
      size="sm"
      className="ml-auto"
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
  /** True while events are still arriving: the elapsed clock ticks. */
  live: boolean;
  status: { label: string; variant: BadgeVariant };
  /** The run's `RunTotals` once its summary is loaded; until then the strip counts the
   *  events seen so far by the same rules (`totalsStrip`). */
  totals?: RunTotals | null;
  /** "View verdict" in the mobile detail sheet: show the verdict this event belongs to. */
  onViewVerdict?: (verdictEventId: string) => void;
}

export function TracePanel({
  runId,
  events,
  selection,
  verdictEventIds,
  live,
  status,
  totals,
  onViewVerdict,
}: TracePanelProps) {
  const rows = useMemo(() => traceRows(events, selection.expanded), [events, selection.expanded]);
  const listRef = useRef<HTMLOListElement>(null);
  const { scrollRequest, selectedId, closeDetails } = selection;
  const sheetEvent =
    selectedId && selection.details.has(selectedId)
      ? (events.find((e) => e.id === selectedId) ?? null)
      : null;
  const closeSheet = useCallback(() => {
    if (selectedId) closeDetails(selectedId);
  }, [selectedId, closeDetails]);

  useEffect(() => {
    if (!scrollRequest) return;
    const list = listRef.current;
    const el = list?.querySelector<HTMLElement>(
      `[data-event-id="${CSS.escape(scrollRequest.id)}"]`,
    );
    if (!list || !el) return;
    // From `lg` the list scrolls inside the panel: scroll it only (not the window), so the
    // verdict stays where the user clicked. Below `lg` (the Trace tab) the page scrolls.
    if (list.scrollHeight > list.clientHeight) {
      list.scrollTo({ top: el.offsetTop, behavior: "smooth" });
    } else {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [scrollRequest]);

  return (
    <section
      className="flex min-h-0 flex-col overflow-hidden rounded-card border border-line bg-surface lg:h-full lg:max-h-[calc(100vh-2rem)]"
      aria-label="Trace"
    >
      <header className="flex shrink-0 items-center gap-2.5 border-b border-line-soft px-4 py-3">
        <h2 className="text-base font-semibold">Trace</h2>
        <Badge variant={status.variant}>{status.label}</Badge>
        <ExportButton runId={runId} />
      </header>
      <TotalsStrip totals={totals} events={events} live={live} />
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-ink-4">Waiting for events…</p>
      ) : (
        <ol
          ref={listRef}
          // While the sheet is up, room below the last row so it can scroll clear of the sheet.
          className={`relative min-h-0 flex-1 overflow-y-auto ${sheetEvent ? "pb-[60dvh] lg:pb-0" : ""}`}
        >
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
      {sheetEvent && (
        <DetailSheet
          event={sheetEvent}
          verdictEventId={verdictEventFor(events, sheetEvent.id, verdictEventIds)}
          onViewVerdict={onViewVerdict}
          onClose={closeSheet}
        />
      )}
    </section>
  );
}
