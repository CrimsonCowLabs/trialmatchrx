"use client";

// Design 06. GET /api/trials once: the header's cache count, the All / Compiled / Not compiled
// chips and the rows all come from that one list, filtered here as you type (`matchingTrials`).
// A compiled trial opens its feasibility view; any other row offers Compile, which calls
// POST /api/trials/{nct}/compile and updates the row from its answer. A table from md up, a
// list of cards below.
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import { PageHeader } from "@/components/PageHeader";
import { TrialStatus } from "@/components/TrialStatus";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, errorMessage, type TrialListItem } from "@/lib/api";
import {
  filterTrials,
  matchingTrials,
  trialFilterChips,
  withCompiled,
  type TrialFilter,
} from "@/lib/browse";
import { countNoun } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

const loadTrials = () => api.listTrials();

/** Per row: the compile in flight, or the last one's error. */
type CompileState = { status: "compiling" } | { status: "failed"; error: string };

function CriteriaBadge({ trial }: { trial: TrialListItem }) {
  return trial.compiled ? (
    <span className="inline-flex h-6 w-fit items-center rounded-full bg-teal-tint px-2.5 text-xs font-medium whitespace-nowrap text-teal-strong">
      {trial.criteria_count} compiled
    </span>
  ) : (
    <span className="inline-flex h-6 w-fit items-center rounded-full border border-line-strong bg-surface px-2.5 text-xs font-medium whitespace-nowrap text-ink-2">
      Not compiled
    </span>
  );
}

function RowAction({
  trial,
  state,
  onCompile,
}: {
  trial: TrialListItem;
  state: CompileState | undefined;
  onCompile: () => void;
}) {
  if (trial.compiled) {
    return (
      <Link
        href={`/feasibility/${encodeURIComponent(trial.nct_id)}`}
        className="link text-sm font-medium whitespace-nowrap"
        data-testid="trial-feasibility"
      >
        Feasibility
      </Link>
    );
  }
  const compiling = state?.status === "compiling";
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={onCompile}
      disabled={compiling}
      className="link -mx-2.5 text-sm"
      data-testid="trial-compile"
    >
      {compiling ? (
        <>
          <Loader2 className="animate-spin" /> Compiling…
        </>
      ) : state?.status === "failed" ? (
        "Retry compile"
      ) : (
        "Compile"
      )}
    </Button>
  );
}

function CompileError({ state }: { state: CompileState | undefined }) {
  if (state?.status !== "failed") return null;
  return (
    <p role="alert" className="text-xs font-normal break-words text-destructive">
      Compile failed: {state.error}
    </p>
  );
}

function FilterChips({
  trials,
  filter,
  onFilter,
}: {
  trials: TrialListItem[];
  filter: TrialFilter;
  onFilter: (f: TrialFilter) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Show trials"
      className="flex w-fit max-w-full flex-wrap rounded-lg bg-secondary p-0.5 text-sm font-medium"
      data-testid="trial-filters"
    >
      {trialFilterChips(trials).map((chip) => {
        const selected = chip.filter === filter;
        return (
          <button
            key={chip.filter}
            type="button"
            aria-pressed={selected}
            onClick={() => onFilter(chip.filter)}
            className={`rounded-md px-3.5 py-1.5 whitespace-nowrap ${selected ? "bg-surface shadow-xs" : "text-ink-3 hover:text-foreground"}`}
          >
            {chip.label} <span className="tabular-nums">{chip.count}</span>
          </button>
        );
      })}
    </div>
  );
}

function TrialsTable({
  trials,
  compiles,
  onCompile,
}: {
  trials: TrialListItem[];
  compiles: Record<string, CompileState>;
  onCompile: (nct: string) => void;
}) {
  return (
    <Card className="hidden py-0 md:flex">
      <table className="w-full text-sm" data-testid="trials-table">
        <thead className="border-b border-line-soft text-left text-xs tracking-wide text-ink-4 uppercase">
          <tr>
            <th className="py-3 pr-5 pl-5 font-medium">NCT ID</th>
            <th className="py-3 pr-5 font-medium">Title</th>
            <th className="py-3 pr-5 font-medium">Phase</th>
            <th className="py-3 pr-5 font-medium">Status</th>
            <th className="py-3 pr-5 font-medium">Criteria</th>
            <th className="py-3 pr-5 font-medium">
              <span className="sr-only">Action</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {trials.map((trial) => (
            <tr
              key={trial.nct_id}
              className="border-t border-line-soft first:border-t-0"
              data-testid="trial-row"
            >
              <td className="py-3.5 pr-5 pl-5 font-mono text-xs font-medium whitespace-nowrap text-teal">
                {trial.nct_id}
              </td>
              <td className="py-3.5 pr-5 text-[0.9375rem] leading-snug font-medium text-pretty">
                {trial.title}
                <CompileError state={compiles[trial.nct_id]} />
              </td>
              <td className="py-3.5 pr-5 whitespace-nowrap text-ink-2">{trial.phase ?? "–"}</td>
              <td className="py-3.5 pr-5 text-ink-2">
                <TrialStatus status={trial.overall_status} />
              </td>
              <td className="py-3.5 pr-5">
                <CriteriaBadge trial={trial} />
              </td>
              <td className="py-3.5 pr-5 text-right">
                <RowAction
                  trial={trial}
                  state={compiles[trial.nct_id]}
                  onCompile={() => onCompile(trial.nct_id)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function TrialCards({
  trials,
  compiles,
  onCompile,
}: {
  trials: TrialListItem[];
  compiles: Record<string, CompileState>;
  onCompile: (nct: string) => void;
}) {
  return (
    <ul className="flex flex-col gap-3 md:hidden" data-testid="trials-list">
      {trials.map((trial) => (
        <li key={trial.nct_id}>
          <Card size="sm" className="gap-1.5 px-4">
            <div className="flex items-center justify-between gap-3">
              <span className="font-mono text-xs font-medium text-teal">{trial.nct_id}</span>
              <CriteriaBadge trial={trial} />
            </div>
            <p className="text-[0.9375rem] leading-snug font-medium">{trial.title}</p>
            <p className="flex flex-wrap items-center gap-x-1.5 text-[0.8125rem] text-ink-4">
              {trial.phase ?? "–"} <span aria-hidden>·</span>
              <TrialStatus status={trial.overall_status} />
            </p>
            <CompileError state={compiles[trial.nct_id]} />
            <div>
              <RowAction
                trial={trial}
                state={compiles[trial.nct_id]}
                onCompile={() => onCompile(trial.nct_id)}
              />
            </div>
          </Card>
        </li>
      ))}
    </ul>
  );
}

export function TrialsView() {
  const { data, error } = useLoad(loadTrials);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<TrialFilter>("all");
  // Criteria counts from compiles run on this page, by NCT ID, laid over the loaded list.
  const [compiled, setCompiled] = useState<Record<string, number>>({});
  const [compiles, setCompiles] = useState<Record<string, CompileState>>({});

  const trials = useMemo(
    () =>
      Object.entries(compiled).reduce(
        (rows, [nct, count]) => withCompiled(rows, nct, count),
        data ?? [],
      ),
    [data, compiled],
  );
  const matching = useMemo(() => matchingTrials(trials, query), [trials, query]);
  const shown = useMemo(() => filterTrials(matching, filter), [matching, filter]);

  const compile = useCallback((nct: string) => {
    setCompiles((s) => ({ ...s, [nct]: { status: "compiling" } }));
    api.compileTrial(nct).then(
      (criteria) => {
        setCompiled((c) => ({ ...c, [nct]: criteria.length }));
        setCompiles((s) => {
          const rest = { ...s };
          delete rest[nct];
          // An empty answer leaves the trial not compiled (as on the API); say why.
          if (criteria.length === 0) {
            rest[nct] = { status: "failed", error: "the compiler returned no criteria" };
          }
          return rest;
        });
      },
      (err: unknown) =>
        setCompiles((s) => ({ ...s, [nct]: { status: "failed", error: errorMessage(err) } })),
    );
  }, []);

  const description = data ? (
    <span data-testid="trials-count">
      <span className="font-mono font-semibold text-foreground tabular-nums">{data.length}</span>{" "}
      {countNoun(data.length, "trial", "trials")} in the cache
    </span>
  ) : (
    "Every trial in the local trials cache, the pool a match searches."
  );

  return (
    <>
      <PageHeader
        breadcrumb={[{ label: "Home", href: "/" }]}
        title="Trials"
        description={description}
      />
      {error ? (
        <p className="text-sm break-words text-destructive">{error}</p>
      ) : !data ? (
        <p className="text-sm text-muted-foreground">Loading trials…</p>
      ) : data.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No trials cached yet. Run <code className="font-mono">make seed</code> to fetch the
          T2D/CKD trials.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2.5 sm:flex-row sm:flex-wrap sm:items-center">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter by NCT ID or title"
              aria-label="Filter trials"
              className="h-10 bg-surface sm:max-w-sm"
            />
            <FilterChips trials={matching} filter={filter} onFilter={setFilter} />
          </div>
          {shown.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="trials-empty">
              No trials match{query.trim() ? ` “${query.trim()}”` : ""}
              {filter === "all" ? "" : ` among the ${filter === "compiled" ? "compiled" : "not compiled"} ones`}
              .
            </p>
          ) : (
            <>
              <TrialsTable trials={shown} compiles={compiles} onCompile={compile} />
              <TrialCards trials={shown} compiles={compiles} onCompile={compile} />
            </>
          )}
        </div>
      )}
    </>
  );
}
